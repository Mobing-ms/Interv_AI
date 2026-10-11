import sys
import os
import unittest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.database import SessionLocal, Base, engine
from app.models import (
    User,
    Profile,
    TargetProfile,
    EducationProfile,
    InterviewConfig,
    UserMemory,
    AskedQuestion,
    QuestionBankItem,
)
from app.auth import hash_password, create_access_token
from app.services.interview_blueprint import build_interview_blueprint
from app.services.question_dedupe import (
    compute_question_hash,
    deduplicate_questions,
    _cosine_similarity,
    _build_sentence_vector,
    normalize_question_text,
)
from app.services.question_generator import (
    generate_question_pool_async,
    rank_and_tag_questions,
    _generate_fallback_questions,
)

Base.metadata.create_all(bind=engine)
client = TestClient(app)

TEST_USER_A = "qb_candidate_a@example.com"
TEST_USER_B = "qb_candidate_b@example.com"
TEST_PASSWORD = "Password123!"

SAMPLE_CV_PROFILE = {
    "personal": {
        "name": "Alex Mercer",
        "email": "alex.mercer@example.com",
        "phone": "+1-555-0199",
        "links": ["https://github.com/alexmercer"]
    },
    "education": [
        {
            "degree": "Bachelor of Technology",
            "branch": "Computer Science",
            "college": "MIT",
            "year": 2024,
            "cgpa": 8.9
        }
    ],
    "skills": {
        "languages": ["Go", "TypeScript", "Python"],
        "frameworks": ["FastAPI", "React", "Next.js"],
        "tools": ["Docker", "Kubernetes", "PostgreSQL", "Redis"],
        "domains": ["Distributed Systems", "Backend Architecture"],
        "soft": ["Cross-functional Leadership", "Communication"]
    },
    "projects": [
        {
            "title": "CloudTask Distributed Scheduler",
            "description": "High-throughput asynchronous distributed task runner with Redis streams and Go workers.",
            "tech_stack": ["Go", "Redis", "Docker", "PostgreSQL"],
            "role": "Lead Architect",
            "outcomes": "Processed 50,000 tasks/sec with under 25ms p99 latency."
        },
        {
            "title": "Real-time Metrics Dashboard",
            "description": "Interactive telemetry dashboard featuring WebSockets and timeseries aggregation.",
            "tech_stack": ["React", "TypeScript", "FastAPI"],
            "role": "Fullstack Developer",
            "outcomes": "Reduced incident triage time by 40% across 6 engineering teams."
        }
    ],
    "internships_experience": [
        {
            "company": "Apex Cloud Systems",
            "role": "Backend Engineering Intern",
            "duration": "6 months",
            "responsibilities": "Implemented rate-limiting proxies and gRPC service meshes."
        }
    ],
    "certifications": ["AWS Certified Solutions Architect"],
    "achievements": ["1st Place Hackathon Winner 2023"]
}


class TestQuestionBankPhase2_3(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self._cleanup()
        self.user_a_id, self.token_a = self._create_user(TEST_USER_A)
        self.user_b_id, self.token_b = self._create_user(TEST_USER_B)
        self._seed_user_a_profile()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        db = SessionLocal()
        try:
            for email in [TEST_USER_A, TEST_USER_B]:
                user = db.query(User).filter(User.email == email).first()
                if user:
                    configs = db.query(InterviewConfig).filter(InterviewConfig.user_id == user.id).all()
                    for cfg in configs:
                        db.query(QuestionBankItem).filter(QuestionBankItem.interview_id == cfg.id).delete()
                    db.query(InterviewConfig).filter(InterviewConfig.user_id == user.id).delete()
                    db.query(AskedQuestion).filter(AskedQuestion.user_id == user.id).delete()
                    db.query(UserMemory).filter(UserMemory.user_id == user.id).delete()
                    db.query(Profile).filter(Profile.user_id == user.id).delete()
                    db.query(TargetProfile).filter(TargetProfile.user_id == user.id).delete()
                    db.query(EducationProfile).filter(EducationProfile.user_id == user.id).delete()
                    db.delete(user)
            db.commit()
        finally:
            db.close()

    def _create_user(self, email: str):
        db = SessionLocal()
        try:
            user = User(
                name="Candidate Tester",
                email=email,
                password_hash=hash_password(TEST_PASSWORD),
                auth_provider="email",
                is_verified=True,
                onboarding_status="profile_confirmed",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            token = create_access_token({"sub": str(user.id)})
            return user.id, token
        finally:
            db.close()

    def _seed_user_a_profile(self):
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            # 1. Canonical Profile
            prof = Profile(
                user_id=self.user_a_id,
                structured_data=SAMPLE_CV_PROFILE,
                version=1,
                confirmed_at=now,
            )
            db.add(prof)

            # 2. Target Profile
            target = TargetProfile(
                user_id=self.user_a_id,
                target_role="Senior Backend Engineer",
                company_type="Scale-up SaaS",
                experience_level="Mid-Senior",
                job_description="Architect resilient distributed microservices in Go and Python, optimize PostgreSQL, and maintain high-volume queues.",
            )
            db.add(target)

            # 3. Education
            edu = EducationProfile(
                user_id=self.user_a_id,
                degree="Bachelor of Technology",
                branch="Computer Science",
                college="MIT",
                graduation_year=2024,
                cgpa=8.9,
            )
            db.add(edu)

            # 4. User Memory (Weak Area: System Design)
            mem = UserMemory(
                user_id=self.user_a_id,
                topic_scores={"Languages": 85.0, "System Design": 52.0, "HR": 78.0},
                weak_topics=["System Design", "Concurrency"],
                session_count=2,
                last_session_at=now,
            )
            db.add(mem)

            db.commit()
        finally:
            db.close()

    # =========================================================================
    # UNIT TESTS: Deduplication
    # =========================================================================

    def test_deduplicate_exact_and_near_duplicates(self):
        """
        Deduplication should eliminate exact hash matches and near-duplicates
        with cosine similarity >= 0.82.
        """
        candidates = [
            {
                "text": "How do database indexes improve query execution speed in PostgreSQL?",
                "topic": "Databases",
                "difficulty": "Medium",
                "question_type": "conceptual",
            },
            {
                # Exact duplicate text
                "text": "How do database indexes improve query execution speed in PostgreSQL?",
                "topic": "Databases",
                "difficulty": "Medium",
                "question_type": "conceptual",
            },
            {
                # Near duplicate (semantic rephrase with high token overlap)
                "text": "How do database indexes improve query execution latency and speed in PostgreSQL?",
                "topic": "Databases",
                "difficulty": "Medium",
                "question_type": "conceptual",
            },
            {
                # Completely distinct question
                "text": "Explain how goroutines differ from OS threads in memory and scheduling.",
                "topic": "Concurrency",
                "difficulty": "Hard",
                "question_type": "conceptual",
            },
        ]

        deduped, removed_count = deduplicate_questions(
            candidates=candidates,
            previously_asked_hashes=set(),
            similarity_threshold=0.82,
        )

        self.assertGreaterEqual(removed_count, 2)
        self.assertEqual(len(deduped), 2)
        texts = [q["text"] for q in deduped]
        self.assertIn("Explain how goroutines differ from OS threads in memory and scheduling.", texts)

    def test_deduplicate_filters_history_asked_questions(self):
        """
        Deduplication must drop any question whose hash matches the user's AskedQuestion history.
        """
        q_text = "What trade-offs exist between optimistic and pessimistic locking?"
        q_hash = compute_question_hash(q_text)

        candidates = [
            {
                "text": q_text,
                "topic": "Databases",
                "difficulty": "Hard",
                "question_type": "conceptual",
            },
            {
                "text": "How do you implement distributed tracing across microservices?",
                "topic": "Distributed Systems",
                "difficulty": "Hard",
                "question_type": "conceptual",
            },
        ]

        deduped, removed = deduplicate_questions(
            candidates=candidates,
            previously_asked_hashes={q_hash},
        )

        self.assertEqual(removed, 1)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["text"], "How do you implement distributed tracing across microservices?")

    # =========================================================================
    # UNIT TESTS: Ranking & Tagging
    # =========================================================================

    def test_rank_and_tag_questions_weak_area_boost(self):
        """
        Validates tags, attaches reserve follow-up templates, and ensures
        weak areas receive rank score boosting.
        """
        db = SessionLocal()
        try:
            target = db.query(TargetProfile).filter(TargetProfile.user_id == self.user_a_id).first()
            blueprint = build_interview_blueprint(
                profile=SAMPLE_CV_PROFILE,
                target_profile=target,
                config={"round_type": "Technical", "difficulty": "Medium", "duration_minutes": 30, "mode": "normal"},
            )
        finally:
            db.close()

        questions = [
            {
                "text": "Explain standard HTTP status codes.",
                "topic": "Networking",
                "question_type": "unknown_type",  # invalid tag to normalize
                "difficulty": "InvalidDiff",       # invalid diff to normalize
                "expected_keywords": [],           # empty to auto-populate
                "cv_reference": None,
                "is_weak_area": False,
            },
            {
                "text": "How do you design a partitioned distributed cache to handle hot keys?",
                "topic": "System Design",         # User's designated weak area
                "question_type": "scenario",
                "difficulty": "Medium",
                "expected_keywords": ["partitioning", "consistent hashing", "cache"],
                "cv_reference": "Project: CloudTask",
                "is_weak_area": True,
            },
        ]

        user_context_stub = {"weak_areas": ["System Design", "Concurrency"]}
        ranked = rank_and_tag_questions(questions, blueprint, user_context_stub)

        # 1. Normalization checks
        self.assertEqual(ranked[1]["question_type"], "conceptual")  # fell back from unknown_type
        self.assertEqual(ranked[1]["difficulty"], "Medium")         # fell back from InvalidDiff
        self.assertTrue(len(ranked[1]["expected_keywords"]) > 0)    # populated keywords
        self.assertTrue(len(ranked[0]["followup_templates"]) >= 2)   # follow-up templates attached

        # 2. Ranking check: weak area + CV reference should rank first
        self.assertEqual(ranked[0]["topic"], "System Design")
        self.assertGreater(ranked[0]["rank_score"], ranked[1]["rank_score"])

    # =========================================================================
    # UNIT TESTS: Generation Engine (Multiplier, CV Grounding, Topic Coverage)
    # =========================================================================

    async def test_generate_question_pool_async_coverage_and_multiplier(self):
        """
        Verifies:
        1. 2-3x seed pool generation relative to total_question_count.
        2. Pool covers all blueprint topics in proper proportions.
        3. Project questions reference real CV items.
        4. Every question contains expected keywords and ideal answer points.
        """
        db = SessionLocal()
        try:
            target = db.query(TargetProfile).filter(TargetProfile.user_id == self.user_a_id).first()
            blueprint = build_interview_blueprint(
                profile=SAMPLE_CV_PROFILE,
                target_profile=target,
                config={"round_type": "Technical", "difficulty": "Medium", "duration_minutes": 30, "mode": "normal"},
            )
        finally:
            db.close()

        result = await generate_question_pool_async(
            blueprint=blueprint,
            profile=SAMPLE_CV_PROFILE,
            target_profile={"target_role": "Senior Backend Engineer"},
            education=None,
            user_context={"weak_areas": ["System Design"]},
            multiplier=2.5,
        )

        total_gen = result["total_generated"]
        active_qs = result["active_questions"]
        reserve_qs = result["reserve_questions"]

        # 1. 2-3x candidate count
        expected_min = int(blueprint.total_question_count * 2.0)
        self.assertGreaterEqual(total_gen, expected_min)

        # 2. Active pool matches blueprint question count
        self.assertEqual(len(active_qs), blueprint.total_question_count)
        self.assertGreater(len(reserve_qs), 0)

        # 3. Topic coverage: all blueprint topics represented
        blueprint_topic_names = {t.name for t in blueprint.topics}
        all_pool_topics = {q["topic"] for q in (active_qs + reserve_qs)}
        for b_top in blueprint_topic_names:
            self.assertIn(b_top, all_pool_topics)

        # 4. Check keyword and answer point completeness
        for q in (active_qs + reserve_qs):
            self.assertTrue(len(q["expected_keywords"]) >= 2, f"Missing keywords for: {q['text']}")
            self.assertTrue(len(q["ideal_answer_points"]) >= 1, f"Missing ideal points for: {q['text']}")
            self.assertEqual(q["max_time_seconds"], blueprint.time_per_question_seconds)

        # 5. Check CV grounding
        cv_project_questions = [q for q in (active_qs + reserve_qs) if q.get("cv_reference")]
        self.assertTrue(len(cv_project_questions) > 0)
        valid_cv_items = (
            [p["title"] for p in SAMPLE_CV_PROFILE["projects"]]
            + SAMPLE_CV_PROFILE["skills"]["languages"]
            + SAMPLE_CV_PROFILE["skills"]["frameworks"]
            + SAMPLE_CV_PROFILE["skills"]["tools"]
            + [exp["company"] for exp in SAMPLE_CV_PROFILE["internships_experience"]]
        )
        for q in cv_project_questions:
            ref = q["cv_reference"]
            is_valid_ref = any(v.lower() in ref.lower() for v in valid_cv_items)
            self.assertTrue(is_valid_ref, f"CV reference '{ref}' does not match real items in candidate CV.")

    # =========================================================================
    # INTEGRATION TESTS: API Endpoints (POST /generate and GET /questions)
    # =========================================================================

    def test_api_post_generate_and_get_questions(self):
        """
        Tests:
        1. POST /interview/{id}/questions/generate creates QuestionBank items.
        2. GET /interview/{id}/questions retrieves the persisted question bank.
        3. Force regenerate refreshes items cleanly.
        """
        # Step 1: Create Interview Config
        create_resp = client.post(
            "/interview/config",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={
                "round_type": "Technical",
                "difficulty": "Hard",
                "duration_minutes": 30,
                "language": "English",
                "mode": "pressure",
                "focus_topics": ["Distributed Systems", "Go"],
            },
        )
        self.assertEqual(create_resp.status_code, 201)
        config_id = create_resp.json()["id"]

        # Step 2: POST /interview/{id}/questions/generate
        gen_resp = client.post(
            f"/interview/{config_id}/questions/generate",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"multiplier": 2.5, "similarity_threshold": 0.82},
        )
        self.assertEqual(gen_resp.status_code, 201)
        gen_data = gen_resp.json()

        self.assertEqual(gen_data["interview_id"], config_id)
        self.assertGreaterEqual(gen_data["total_generated"], 15)
        self.assertGreater(len(gen_data["questions"]), 0)
        self.assertGreater(len(gen_data["reserve_followups"]), 0)

        # In pressure mode, answer timer must be 60s
        for q in gen_data["questions"]:
            self.assertEqual(q["max_time_seconds"], 60)
            self.assertFalse(q["is_reserve_followup"])

        for q in gen_data["reserve_followups"]:
            self.assertTrue(q["is_reserve_followup"])

        # Step 3: GET /interview/{id}/questions
        get_resp = client.get(
            f"/interview/{config_id}/questions",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(get_resp.status_code, 200)
        get_data = get_resp.json()

        self.assertEqual(len(get_data["questions"]), len(gen_data["questions"]))
        self.assertEqual(len(get_data["reserve_followups"]), len(gen_data["reserve_followups"]))
        self.assertEqual(get_data["questions"][0]["text"], gen_data["questions"][0]["text"])

        # Step 4: Force Regenerate
        regen_resp = client.post(
            f"/interview/{config_id}/questions/generate",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"force_regenerate": True},
        )
        self.assertEqual(regen_resp.status_code, 201)
        regen_data = regen_resp.json()
        self.assertGreater(len(regen_data["questions"]), 0)

    def test_returning_candidate_never_repeats_earlier_questions(self):
        """
        Confirms that returning candidates never receive previously asked questions.
        """
        # Step 1: Create Interview Config
        create_resp = client.post(
            "/interview/config",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={
                "round_type": "Technical",
                "difficulty": "Medium",
                "duration_minutes": 15,
                "language": "English",
                "mode": "normal",
            },
        )
        self.assertEqual(create_resp.status_code, 201)
        config_id = create_resp.json()["id"]

        # Step 2: Seed asked questions into candidate history
        test_asked_text = "How do goroutines achieve low memory footprint and efficient context switches compared to OS threads?"
        test_asked_hash = compute_question_hash(test_asked_text)

        db = SessionLocal()
        try:
            asked = AskedQuestion(
                user_id=self.user_a_id,
                question_hash=test_asked_hash,
                topic="Languages: Go",
                question_text=test_asked_text,
                asked_at=datetime.now(timezone.utc),
                score=82.0,
            )
            db.add(asked)
            db.commit()
        finally:
            db.close()

        # Step 3: Generate Question Bank
        gen_resp = client.post(
            f"/interview/{config_id}/questions/generate",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"force_regenerate": True},
        )
        self.assertEqual(gen_resp.status_code, 201)
        gen_data = gen_resp.json()

        all_pool_hashes = [q["question_hash"] for q in gen_data["questions"]] + [
            q["question_hash"] for q in gen_data["reserve_followups"]
        ]

        self.assertNotIn(test_asked_hash, all_pool_hashes, "Previously asked question was repeated in the question bank!")

    def test_unauthorized_and_cross_user_isolation(self):
        """
        Ensures authentication is enforced and Candidate B cannot generate
        or access Candidate A's interview questions.
        """
        # 1. Unauthenticated request
        unauth_resp = client.post("/interview/1/questions/generate")
        self.assertEqual(unauth_resp.status_code, 401)

        # 2. Candidate A creates config
        create_resp = client.post(
            "/interview/config",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"round_type": "HR", "difficulty": "Easy", "duration_minutes": 15, "mode": "normal"},
        )
        self.assertEqual(create_resp.status_code, 201)
        config_id = create_resp.json()["id"]

        # 3. Candidate B attempts to generate questions for Candidate A's config
        b_gen_resp = client.post(
            f"/interview/{config_id}/questions/generate",
            headers={"Authorization": f"Bearer {self.token_b}"},
        )
        self.assertEqual(b_gen_resp.status_code, 404)

        # 4. Candidate B attempts to read Candidate A's questions
        b_get_resp = client.get(
            f"/interview/{config_id}/questions",
            headers={"Authorization": f"Bearer {self.token_b}"},
        )
        self.assertEqual(b_get_resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
