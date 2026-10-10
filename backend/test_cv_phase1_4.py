import sys
import os
import json
import asyncio
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.database import SessionLocal
from app.models import User, EducationProfile, TargetProfile, CVDocument
from app.auth import hash_password, create_access_token
from app.schemas import StructuredCV, CrossCheckFlagType, SeverityLevel
from app.services.llm import llm_service
from app.services.cv_cross_check import cross_check_cv

client = TestClient(app)

SAMPLE_CV_1_TEXT = """
Alex Rivera
Email: alex.rivera@example.com | Phone: +1-555-0199
GitHub: https://github.com/alexrivera | LinkedIn: https://linkedin.com/in/alexrivera

EDUCATION
Stanford University
Bachelor of Science in Computer Science
Graduation: 2026 | GPA: 3.8 / 4.0

TECHNICAL SKILLS
Languages: TypeScript, JavaScript, Python, SQL
Frameworks: React, Next.js, FastAPI, Node.js
Tools: Docker, Git, PostgreSQL
Domains: Web Development, Distributed Systems
Soft Skills: Team Leadership, Problem Solving

PROJECTS
IntervAI - AI Mock Interview Platform
- Fullstack web app built with React, FastAPI and PostgreSQL.
- Handled audio streaming and real-time evaluation with sub-second feedback.
Role: Fullstack Developer | Outcomes: 95% test coverage, used by 200+ students.

EXPERIENCE
Acme Labs - Software Engineering Intern (June 2024 - Sept 2024)
- Developed microservices in Python and optimized GraphQL queries.
- Built reusable React components for the internal dashboard.
"""

SAMPLE_CV_1_PARSED = {
    "personal": {
        "name": "Alex Rivera",
        "email": "alex.rivera@example.com",
        "phone": "+1-555-0199",
        "links": ["https://github.com/alexrivera", "https://linkedin.com/in/alexrivera"]
    },
    "education": [
        {
            "degree": "Bachelor of Science",
            "branch": "Computer Science",
            "college": "Stanford University",
            "year": 2026,
            "cgpa": 3.8
        }
    ],
    "skills": {
        "languages": ["TypeScript", "JavaScript", "Python", "SQL"],
        "frameworks": ["React", "Next.js", "FastAPI", "Node.js"],
        "tools": ["Docker", "Git", "PostgreSQL"],
        "domains": ["Web Development", "Distributed Systems"],
        "soft": ["Team Leadership", "Problem Solving"]
    },
    "projects": [
        {
            "title": "IntervAI - AI Mock Interview Platform",
            "description": "Fullstack web app built with React, FastAPI and PostgreSQL.",
            "tech_stack": ["React", "FastAPI", "PostgreSQL"],
            "role": "Fullstack Developer",
            "outcomes": "95% test coverage, used by 200+ students."
        }
    ],
    "internships_experience": [
        {
            "company": "Acme Labs",
            "role": "Software Engineering Intern",
            "duration": "June 2024 - Sept 2024",
            "responsibilities": ["Developed microservices in Python", "Built reusable React components"]
        }
    ],
    "certifications": [],
    "achievements": []
}

SAMPLE_CV_2_TEXT = """
Jordan Lee
Email: jordan.lee@example.com
LinkedIn: https://linkedin.com/in/jordanlee

EDUCATION
Massachusetts Institute of Technology (MIT)
Bachelor of Science in Mechanical Engineering
Graduation: 2024 | CGPA: 7.2 / 10.0

EXPERIENCE
AutoCo - CAD Design Intern (Jan 2023 - July 2023)
- Designed automotive chassis components using SolidWorks and ANSYS.
"""

SAMPLE_CV_2_PARSED = {
    "personal": {
        "name": "Jordan Lee",
        "email": "jordan.lee@example.com",
        "phone": None,
        "links": ["https://linkedin.com/in/jordanlee"]
    },
    "education": [
        {
            "degree": "Bachelor of Science",
            "branch": "Mechanical Engineering",
            "college": "Massachusetts Institute of Technology (MIT)",
            "year": 2024,
            "cgpa": 7.2
        }
    ],
    "skills": {
        "languages": [],
        "frameworks": [],
        "tools": [],
        "domains": [],
        "soft": []
    },
    "projects": [],
    "internships_experience": [
        {
            "company": "AutoCo",
            "role": "CAD Design Intern",
            "duration": "Jan 2023 - July 2023",
            "responsibilities": ["Designed automotive chassis components using SolidWorks and ANSYS"]
        }
    ],
    "certifications": [],
    "achievements": []
}

SAMPLE_CV_3_TEXT = """
Priya Sharma
Email: priya.sharma@example.com | Phone: +1-555-8822
GitHub: https://github.com/priyasharma

EDUCATION
University of California, Berkeley
Master of Science in Data Science
Graduation: 2025 | GPA: 3.9 / 4.0

SKILLS
Languages: Python, SQL, R
Frameworks: PyTorch, TensorFlow, Scikit-learn, Pandas
Tools: Jupyter, Git, MLflow
Domains: Machine Learning, Natural Language Processing, Computer Vision
Soft Skills: Critical Thinking, Scientific Writing

PROJECTS
LLM RAG Engine
- Retrieval-augmented generation pipeline using FAISS and LangChain.
tech stack: Python, PyTorch, FAISS

EXPERIENCE
AI Research Labs - Machine Learning Intern (May 2024 - Aug 2024)
- Trained transformer models on biomedical text datasets.
"""

SAMPLE_CV_3_PARSED = {
    "personal": {
        "name": "Priya Sharma",
        "email": "priya.sharma@example.com",
        "phone": "+1-555-8822",
        "links": ["https://github.com/priyasharma"]
    },
    "education": [
        {
            "degree": "Master of Science",
            "branch": "Data Science",
            "college": "University of California, Berkeley",
            "year": 2025,
            "cgpa": 3.9
        }
    ],
    "skills": {
        "languages": ["Python", "SQL", "R"],
        "frameworks": ["PyTorch", "TensorFlow", "Scikit-learn", "Pandas"],
        "tools": ["Jupyter", "Git", "MLflow"],
        "domains": ["Machine Learning", "Natural Language Processing", "Computer Vision"],
        "soft": ["Critical Thinking", "Scientific Writing"]
    },
    "projects": [
        {
            "title": "LLM RAG Engine",
            "description": "Retrieval-augmented generation pipeline using FAISS and LangChain.",
            "tech_stack": ["Python", "PyTorch", "FAISS"],
            "role": "ML Engineer",
            "outcomes": "Achieved 92% retrieval accuracy"
        }
    ],
    "internships_experience": [
        {
            "company": "AI Research Labs",
            "role": "Machine Learning Intern",
            "duration": "May 2024 - Aug 2024",
            "responsibilities": ["Trained transformer models on biomedical text datasets"]
        }
    ],
    "certifications": [],
    "achievements": []
}


def test_cv_structuring_and_cross_check():
    print("--- Starting Phase 1.4 Tests ---")

    # 1. Test LLM Validation & Retry with mock handler
    retry_count = [0]

    def flaky_mock_handler(system_prompt: str, user_prompt: str):
        retry_count[0] += 1
        if retry_count[0] == 1:
            # Return invalid schema (personal must be an object/dict) on first attempt to trigger retry
            return {"personal": "invalid_string_not_dict"}
        # Return valid structured CV on second attempt
        return SAMPLE_CV_1_PARSED

    llm_service.set_mock_handler(flaky_mock_handler)

    structured_res = asyncio.run(
        llm_service.generate_structured_json(
            system_prompt="Test system prompt",
            user_prompt=SAMPLE_CV_1_TEXT,
            schema_cls=StructuredCV,
            max_retries=1,
        )
    )
    assert retry_count[0] == 2, f"Expected 2 attempts for retry, got {retry_count[0]}"
    assert structured_res.personal.name == "Alex Rivera"
    assert len(structured_res.skills.frameworks) == 4
    print("Test 1 Passed: LLM retry mechanism successfully recovered from validation failure.")

    # 2. Test Sample CV 1: Perfect Alignment
    llm_service.set_mock_handler(lambda s, u: SAMPLE_CV_1_PARSED)
    cv1_structured = asyncio.run(
        llm_service.generate_structured_json(
            system_prompt="Extract CV",
            user_prompt=SAMPLE_CV_1_TEXT,
            schema_cls=StructuredCV,
            max_retries=1,
        )
    )

    edu_profile_1 = EducationProfile(
        user_id=1,
        degree="Bachelor's degree",
        branch="Computer Science",
        college="Stanford University",
        graduation_year=2026,
        cgpa=3.8,
        cgpa_scale=4.0
    )
    target_profile_1 = TargetProfile(
        user_id=1,
        target_role="Fullstack Engineer",
        company_type="Product",
        experience_level="Fresher"
    )

    flags_1 = cross_check_cv(cv1_structured, edu_profile_1, target_profile_1)
    # CV 1 has matching degree (Bachelor), branch (Computer Science), college (Stanford), grad year (2026),
    # CGPA (3.8), target role skills (Fullstack, React, Python), projects present, skills present.
    assert len(flags_1) == 0, f"Expected 0 flags for perfectly aligned CV 1, got {flags_1}"
    print("Test 2 Passed: Sample CV 1 produces valid structured JSON with 0 mismatch flags.")

    # 3. Test Sample CV 2: Multiple Mismatches & Missing Sections
    llm_service.set_mock_handler(lambda s, u: SAMPLE_CV_2_PARSED)
    cv2_structured = asyncio.run(
        llm_service.generate_structured_json(
            system_prompt="Extract CV",
            user_prompt=SAMPLE_CV_2_TEXT,
            schema_cls=StructuredCV,
            max_retries=1,
        )
    )

    # Nothing hallucinated:
    assert len(cv2_structured.projects) == 0
    assert len(cv2_structured.skills.languages) == 0
    assert len(cv2_structured.skills.frameworks) == 0
    assert cv2_structured.personal.phone is None

    # Compare with a CS / Frontend target profile
    edu_profile_2 = EducationProfile(
        user_id=2,
        degree="Bachelor's degree",
        branch="Computer Science",
        college="Stanford University",
        graduation_year=2026,
        cgpa=8.5,
        cgpa_scale=10.0
    )
    target_profile_2 = TargetProfile(
        user_id=2,
        target_role="Frontend Engineer",
        company_type="Product",
        experience_level="Fresher"
    )

    flags_2 = cross_check_cv(cv2_structured, edu_profile_2, target_profile_2)
    flag_fields = {f.field: f for f in flags_2}

    assert "projects" in flag_fields, "Expected missing_section on projects"
    assert flag_fields["projects"].type == CrossCheckFlagType.MISSING_SECTION
    assert "skills" in flag_fields, "Expected missing_section on skills"
    assert flag_fields["skills"].type == CrossCheckFlagType.MISSING_SECTION
    assert "branch" in flag_fields, "Expected mismatch on branch"
    assert flag_fields["branch"].type == CrossCheckFlagType.MISMATCH
    assert "college" in flag_fields, "Expected mismatch on college"
    assert "graduation_year" in flag_fields, "Expected mismatch on graduation year"
    assert "target_role_skills" in flag_fields, "Expected mismatch on target_role_skills"

    print("Test 3 Passed: Sample CV 2 accurately flagged missing sections and mismatches (projects, skills, branch, college, year, role).")

    # 4. Test Sample CV 3: Degree & CGPA Mismatch with Role Alignment
    llm_service.set_mock_handler(lambda s, u: SAMPLE_CV_3_PARSED)
    cv3_structured = asyncio.run(
        llm_service.generate_structured_json(
            system_prompt="Extract CV",
            user_prompt=SAMPLE_CV_3_TEXT,
            schema_cls=StructuredCV,
            max_retries=1,
        )
    )

    edu_profile_3 = EducationProfile(
        user_id=3,
        degree="Bachelor's degree",
        branch="Information Technology",
        college="San Jose State University",
        graduation_year=2025,
        cgpa=3.2,
        cgpa_scale=4.0
    )
    target_profile_3 = TargetProfile(
        user_id=3,
        target_role="DevOps Engineer",
        company_type="MNC",
        experience_level="2-5"
    )

    flags_3 = cross_check_cv(cv3_structured, edu_profile_3, target_profile_3)
    flag_fields_3 = {f.field: f for f in flags_3}

    assert "degree" in flag_fields_3, "Expected mismatch on degree (Master vs Bachelor)"
    assert "college" in flag_fields_3, "Expected mismatch on college (UC Berkeley vs San Jose State)"
    assert "cgpa" in flag_fields_3, "Expected mismatch on cgpa (3.9 vs 3.2)"
    assert "target_role_skills" in flag_fields_3, "Expected mismatch on target_role_skills (DevOps has no Kubernetes/Docker/AWS in CV)"

    print("Test 4 Passed: Sample CV 3 accurately flagged degree, college, cgpa, and target role skill mismatches.")

    # 5. Live Test via FastAPI endpoints: POST /cv/{id}/parse and GET /cv/{id}/parsed
    db = SessionLocal()
    try:
        user_email = "cv_phase14_user@example.com"
        existing_users = db.query(User).filter(User.email == user_email).all()
        for u in existing_users:
            db.query(CVDocument).filter(CVDocument.user_id == u.id).delete()
            db.query(EducationProfile).filter(EducationProfile.user_id == u.id).delete()
            db.query(TargetProfile).filter(TargetProfile.user_id == u.id).delete()
            db.delete(u)
        db.commit()

        user = User(
            name="Alex Tester",
            email=user_email,
            password_hash=hash_password("password123"),
            auth_provider="local",
            is_verified=True,
            onboarding_status="cv_done"
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        edu = EducationProfile(
            user_id=user.id,
            degree="Bachelor's degree",
            branch="Computer Science",
            college="Stanford University",
            graduation_year=2026,
            cgpa=3.8,
            cgpa_scale=4.0
        )
        tgt = TargetProfile(
            user_id=user.id,
            target_role="Fullstack Engineer",
            company_type="Product",
            experience_level="Fresher"
        )
        db.add(edu)
        db.add(tgt)

        import uuid
        cv_doc = CVDocument(
            user_id=user.id,
            file_key=f"cv_phase14_{uuid.uuid4().hex}.pdf",
            filename="Alex_Rivera_Resume.pdf",
            file_size=1024,
            mime_type="application/pdf",
            status="extracted",
            raw_text=SAMPLE_CV_1_TEXT
        )
        db.add(cv_doc)
        db.commit()
        db.refresh(cv_doc)

        token = create_access_token({"sub": str(user.id), "email": user.email})
        headers = {"Authorization": f"Bearer {token}"}

        # Call POST /cv/{id}/parse
        llm_service.set_mock_handler(lambda s, u: SAMPLE_CV_1_PARSED)
        res_parse = client.post(f"/cv/{cv_doc.id}/parse", headers=headers)
        assert res_parse.status_code == 200, f"Expected 200, got {res_parse.status_code}: {res_parse.text}"
        data = res_parse.json()
        assert data["id"] == cv_doc.id
        assert data["structured_data"]["personal"]["name"] == "Alex Rivera"
        assert len(data["structured_data"]["projects"]) == 1
        assert len(data["cross_check_flags"]) == 0
        print(f"Test 5 Passed: POST /cv/{cv_doc.id}/parse returned valid structured JSON and flags.")

        # Call GET /cv/{id}/parsed
        res_get = client.get(f"/cv/{cv_doc.id}/parsed", headers=headers)
        assert res_get.status_code == 200
        get_data = res_get.json()
        assert get_data["structured_data"]["personal"]["name"] == "Alex Rivera"
        print(f"Test 6 Passed: GET /cv/{cv_doc.id}/parsed verified persisted structured data.")

        # Call GET /cv/latest/parsed
        res_latest = client.get("/cv/latest/parsed", headers=headers)
        assert res_latest.status_code == 200
        assert res_latest.json()["id"] == cv_doc.id
        print("Test 7 Passed: GET /cv/latest/parsed retrieved latest structured CV successfully.")

    finally:
        llm_service.set_mock_handler(None)
        db.close()

    print("\nALL PHASE 1.4 TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    test_cv_structuring_and_cross_check()
