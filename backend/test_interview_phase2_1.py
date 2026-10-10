import sys
import os
import unittest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.database import SessionLocal, Base, engine
from app.models import User, InterviewConfig, UserMemory, AskedQuestion
from app.auth import hash_password, create_access_token

Base.metadata.create_all(bind=engine)
client = TestClient(app)

NEW_USER_EMAIL = "interview_new_candidate@example.com"
RETURNING_USER_EMAIL = "interview_returning_candidate@example.com"
TEST_PASSWORD = "Password123!"


class TestInterviewPhase2_1(unittest.TestCase):

    def setUp(self):
        self._cleanup()
        self.new_user_id, self.new_token = self._create_user(NEW_USER_EMAIL)
        self.ret_user_id, self.ret_token = self._create_user(RETURNING_USER_EMAIL)
        self._seed_returning_user_history(self.ret_user_id)

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        db = SessionLocal()
        try:
            for email in [NEW_USER_EMAIL, RETURNING_USER_EMAIL]:
                user = db.query(User).filter(User.email == email).first()
                if user:
                    db.query(InterviewConfig).filter(InterviewConfig.user_id == user.id).delete()
                    db.query(AskedQuestion).filter(AskedQuestion.user_id == user.id).delete()
                    db.query(UserMemory).filter(UserMemory.user_id == user.id).delete()
                    db.delete(user)
            db.commit()
        finally:
            db.close()

    def _create_user(self, email):
        db = SessionLocal()
        try:
            user = User(
                name="Candidate Test",
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

    def _seed_returning_user_history(self, user_id):
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            memory = UserMemory(
                user_id=user_id,
                topic_scores={
                    "React architecture": 62.0,
                    "Algorithms": 80.0,
                    "System design": 75.0,
                    "Communication": 88.0,
                },
                weak_topics=["React architecture"],
                session_count=3,
                last_session_at=now - timedelta(days=1),
                created_at=now,
                updated_at=now,
            )
            db.add(memory)

            db.add(
                AskedQuestion(
                    user_id=user_id,
                    question_hash="hash_react_hooks_01",
                    topic="React architecture",
                    question_text="Explain useMemo vs useCallback memory overhead.",
                    score=62.0,
                    asked_at=now - timedelta(days=1),
                )
            )
            db.commit()
        finally:
            db.close()

    def test_new_user_gets_default_baseline_context(self):
        headers = {"Authorization": f"Bearer {self.new_token}"}
        res = client.get("/interview/context", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertFalse(data["is_returning"])
        self.assertEqual(data["session_count"], 0)
        self.assertIsNone(data["last_session_at"])
        self.assertEqual(data["past_scores"], {})
        self.assertEqual(data["weak_areas"], [])
        self.assertEqual(len(data["history_asked_questions"]), 0)
        self.assertEqual(data["recommended_difficulty"], "Medium")

        # Equal baseline weights for new user
        weights = data["baseline_weights"]
        self.assertEqual(weights["Problem solving"], 0.25)
        self.assertEqual(weights["Architecture & design"], 0.25)
        self.assertEqual(weights["Communication"], 0.25)
        self.assertEqual(weights["Execution & clarity"], 0.25)

    def test_returning_user_gets_loaded_scores_and_weak_areas(self):
        headers = {"Authorization": f"Bearer {self.ret_token}"}
        res = client.get("/interview/context", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertTrue(data["is_returning"])
        self.assertEqual(data["session_count"], 3)
        self.assertIsNotNone(data["last_session_at"])
        self.assertEqual(data["weak_areas"], ["React architecture"])
        self.assertEqual(data["past_scores"]["React architecture"], 62.0)
        self.assertEqual(len(data["history_asked_questions"]), 1)
        self.assertEqual(data["history_asked_questions"][0]["question_hash"], "hash_react_hooks_01")

        # Weak area gets boosted baseline weight (> 0.25)
        weights = data["baseline_weights"]
        self.assertGreater(weights["React architecture"], 0.25)

    def test_create_interview_config_normal_mode(self):
        headers = {"Authorization": f"Bearer {self.new_token}"}
        payload = {
            "round_type": "Technical",
            "difficulty": "Medium",
            "duration_minutes": 30,
            "language": "English",
            "mode": "normal",
            "focus_topics": ["Data Structures", "APIs"],
        }
        res = client.post("/interview/config", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)
        data = res.json()

        self.assertEqual(data["round_type"], "Technical")
        self.assertEqual(data["difficulty"], "Medium")
        self.assertEqual(data["duration_minutes"], 30)
        self.assertEqual(data["mode"], "normal")
        self.assertEqual(data["answer_timer_seconds"], 120)  # 2 min standard timer
        self.assertEqual(data["pressure_rules"]["probing_intensity"], "standard")

    def test_create_interview_config_pressure_mode_has_shorter_timer(self):
        headers = {"Authorization": f"Bearer {self.new_token}"}
        payload = {
            "round_type": "Mixed",
            "difficulty": "Hard",
            "duration_minutes": 15,
            "language": "English",
            "mode": "pressure",
            "focus_topics": ["Rapid System Design"],
        }
        res = client.post("/interview/config", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)
        data = res.json()

        self.assertEqual(data["round_type"], "Mixed")
        self.assertEqual(data["difficulty"], "Hard")
        self.assertEqual(data["mode"], "pressure")
        self.assertEqual(data["answer_timer_seconds"], 60)  # Shorter 60s timer in pressure mode!
        self.assertEqual(data["pressure_rules"]["probing_intensity"], "high")

    def test_get_latest_interview_config(self):
        headers = {"Authorization": f"Bearer {self.new_token}"}

        # 404 before any config created
        res0 = client.get("/interview/config/latest", headers=headers)
        self.assertEqual(res0.status_code, 404)

        # Create config
        payload = {
            "round_type": "HR",
            "difficulty": "Easy",
            "duration_minutes": 15,
            "language": "English",
            "mode": "normal",
        }
        res1 = client.post("/interview/config", json=payload, headers=headers)
        self.assertEqual(res1.status_code, 201)

        # GET /interview/config/latest returns the created config
        res2 = client.get("/interview/config/latest", headers=headers)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["round_type"], "HR")
        self.assertEqual(res2.json()["duration_minutes"], 15)

    def test_invalid_interview_config_rejected(self):
        headers = {"Authorization": f"Bearer {self.new_token}"}

        # Invalid round type
        bad_round = {
            "round_type": "UnderwaterRobotics",
            "difficulty": "Medium",
            "duration_minutes": 30,
        }
        res = client.post("/interview/config", json=bad_round, headers=headers)
        self.assertEqual(res.status_code, 422)

        # Invalid duration (too short)
        bad_duration = {
            "round_type": "Technical",
            "difficulty": "Medium",
            "duration_minutes": 2,
        }
        res = client.post("/interview/config", json=bad_duration, headers=headers)
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()
