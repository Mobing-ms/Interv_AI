import sys
import os
import unittest
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.database import SessionLocal, Base, engine
from app.models import User, Profile, CVDocument, EducationProfile, TargetProfile
from app.auth import hash_password, create_access_token

Base.metadata.create_all(bind=engine)

client = TestClient(app)

TEST_USER_EMAIL = "profile_phase1_5_test@example.com"
TEST_USER_PASSWORD = "Password123!"

SAMPLE_STRUCTURED_DATA = {
    "personal": {
        "name": "Alex Rivera",
        "email": "alex.rivera@example.com",
        "phone": "+1-555-0199",
        "links": ["https://github.com/alexrivera"]
    },
    "education": [
        {
            "degree": "Bachelor of Technology",
            "branch": "Computer Science & Engineering",
            "college": "MIT",
            "year": 2026,
            "cgpa": 9.2
        }
    ],
    "skills": {
        "languages": ["TypeScript", "Python"],
        "frameworks": ["React", "FastAPI"],
        "tools": ["Docker", "Git"],
        "domains": ["Web Development", "AI Engineering"],
        "soft": ["Communication", "Problem Solving"]
    },
    "projects": [
        {
            "title": "IntervAI Mock Interview Platform",
            "description": "Fullstack platform for AI interview practice.",
            "tech_stack": ["React", "FastAPI", "SQLite"],
            "role": "Fullstack Engineer",
            "outcomes": "Achieved sub-second response times."
        }
    ],
    "internships_experience": [
        {
            "company": "Acme Corp",
            "role": "Software Engineering Intern",
            "duration": "May 2024 - Aug 2024",
            "responsibilities": ["Built REST APIs in FastAPI"]
        }
    ],
    "certifications": ["AWS Certified Solutions Architect"],
    "achievements": ["Hackathon 1st Place Winner"]
}


class TestProfilePhase1_5(unittest.TestCase):

    def setUp(self):
        self._cleanup()
        self.user_id, self.token = self._create_test_user()
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == TEST_USER_EMAIL).first()
            if user:
                db.query(Profile).filter(Profile.user_id == user.id).delete()
                db.query(CVDocument).filter(CVDocument.user_id == user.id).delete()
                db.query(EducationProfile).filter(EducationProfile.user_id == user.id).delete()
                db.query(TargetProfile).filter(TargetProfile.user_id == user.id).delete()
                db.delete(user)
                db.commit()
        finally:
            db.close()

    def _create_test_user(self):
        db = SessionLocal()
        try:
            user = User(
                name="Alex Tester",
                email=TEST_USER_EMAIL,
                password_hash=hash_password(TEST_USER_PASSWORD),
                auth_provider="email",
                is_verified=True,
                onboarding_status="cv_done",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            token = create_access_token({"sub": str(user.id)})
            return user.id, token
        finally:
            db.close()

    def test_profile_404_when_not_confirmed(self):
        res = client.get("/profile", headers=self.headers)
        self.assertEqual(res.status_code, 404)
        self.assertIn("No confirmed profile found", res.json()["detail"])

    def test_profile_confirm_blocks_unresolved_high_severity_flags(self):
        payload = {
            "structured_data": SAMPLE_STRUCTURED_DATA,
            "unresolved_flags": [
                {
                    "type": "MISMATCH",
                    "field": "degree",
                    "cv_value": "Bachelor of Technology",
                    "form_value": "Master of Science",
                    "severity": "HIGH",
                    "message": "Degree mismatch between CV and form"
                }
            ]
        }

        res = client.put("/profile/confirm", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("unresolved high-severity alignment note", res.json()["detail"])

    def test_profile_confirm_allows_medium_or_low_unresolved_flags(self):
        payload = {
            "structured_data": SAMPLE_STRUCTURED_DATA,
            "unresolved_flags": [
                {
                    "type": "MISSING_SECTION",
                    "field": "certifications",
                    "severity": "LOW",
                    "message": "Certifications section is optional"
                }
            ]
        }

        res = client.put("/profile/confirm", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["user_id"], self.user_id)
        self.assertIsNotNone(data["confirmed_at"])
        self.assertEqual(data["structured_data"]["personal"]["name"], "Alex Rivera")

    def test_profile_canonical_retrieval_and_versioning(self):
        # Step 1: Confirm version 1
        res1 = client.put(
            "/profile/confirm",
            json={"structured_data": SAMPLE_STRUCTURED_DATA, "unresolved_flags": []},
            headers=self.headers,
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1["version"], 1)

        # Check GET /profile
        get_res = client.get("/profile", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        canonical = get_res.json()
        self.assertEqual(canonical["version"], 1)
        self.assertEqual(canonical["structured_data"]["personal"]["name"], "Alex Rivera")

        # Verify onboarding status updated to profile_confirmed (Step 5)
        status_res = client.get("/profile/status", headers=self.headers)
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["onboarding_status"], "profile_confirmed")
        self.assertEqual(status_data["current_step"], 5)
        self.assertTrue(status_data["profile_confirmed"])

        # Step 2: Simulate re-upload or edit -> Confirm version 2
        updated_data = dict(SAMPLE_STRUCTURED_DATA)
        updated_data["personal"] = dict(SAMPLE_STRUCTURED_DATA["personal"])
        updated_data["personal"]["name"] = "Alex Rivera (Updated)"
        updated_data["skills"] = dict(SAMPLE_STRUCTURED_DATA["skills"])
        updated_data["skills"]["languages"] = list(SAMPLE_STRUCTURED_DATA["skills"]["languages"]) + ["Go"]

        res2 = client.put(
            "/profile/confirm",
            json={"structured_data": updated_data, "unresolved_flags": []},
            headers=self.headers,
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2["version"], 2)
        self.assertEqual(data2["structured_data"]["personal"]["name"], "Alex Rivera (Updated)")
        self.assertIn("Go", data2["structured_data"]["skills"]["languages"])

        # Check GET /profile returns newest version (version 2)
        get_res2 = client.get("/profile", headers=self.headers)
        self.assertEqual(get_res2.status_code, 200)
        canonical2 = get_res2.json()
        self.assertEqual(canonical2["version"], 2)
        self.assertEqual(canonical2["structured_data"]["personal"]["name"], "Alex Rivera (Updated)")

        # Check GET /profile/versions lists both versions in descending order
        versions_res = client.get("/profile/versions", headers=self.headers)
        self.assertEqual(versions_res.status_code, 200)
        versions_list = versions_res.json()
        self.assertEqual(len(versions_list), 2)
        self.assertEqual(versions_list[0]["version"], 2)
        self.assertEqual(versions_list[1]["version"], 1)


if __name__ == "__main__":
    unittest.main()
