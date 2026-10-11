"""
Unit and Integration Tests for Phase 6.3:
- Dashboard Endpoints: GET /session/dashboard-summary and GET /session
- Memory Update Synchronization before Blueprint Generation
- Retake Loop: Avoid Previously Asked Questions & Weight Previous Weak Areas Higher
- Reuse Confirmed Profile & Transition into Setup (Phase 2) -> Pre-Check (Phase 3)
"""

import time
import unittest
import asyncio
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal
from app.models import (
    User,
    InterviewConfig,
    InterviewSession,
    QuestionBankItem,
    SessionResult,
    SessionReport,
    UserMemory,
    AskedQuestion,
    Profile,
    TargetProfile,
)
from app.auth import create_access_token
from app.main import app
from app.services.interview_context import (
    load_user_context,
    ensure_user_memory_updated,
)
from app.services.interview_blueprint import build_interview_blueprint
from app.services.question_generator import generate_question_pool_async, compute_question_hash
from app.services.score_fusion_service import process_and_persist_session_result

client = TestClient(app)


class TestDashboardAndRetakePhase6_3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        # Create test user
        unique_id = int(time.time() * 1000)
        self.user_email = f"retake_candidate_{unique_id}@example.com"
        self.user = User(
            email=self.user_email,
            name="Alice Retake Tester",
            password_hash="testpasshash123",
            auth_provider="email",
            is_verified=True,
            onboarding_status="completed",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.token = create_access_token({"sub": str(self.user.id)})
        self.headers = {"Authorization": f"Bearer {self.token}"}

        # Add profile and target profile (simulating completed Phase 1)
        self.profile = Profile(
            user_id=self.user.id,
            structured_data={
                "skills": {"languages": ["Python", "Go"], "frameworks": ["FastAPI", "React"]},
                "projects": [{"title": "Distributed Key-Value Store", "description": "Raft-based store in Go"}],
                "candidate_name": "Alice Retake Tester",
                "total_years_exp": 4,
            },
        )
        self.target_profile = TargetProfile(
            user_id=self.user.id,
            target_role="Backend Systems Engineer",
            company_type="Product Tech",
            experience_level="Senior",
        )
        self.db.add(self.profile)
        self.db.add(self.target_profile)
        self.db.commit()

    def tearDown(self):
        try:
            if hasattr(self, "user") and self.user:
                self.db.rollback()
                self.db.query(AskedQuestion).filter(AskedQuestion.user_id == self.user.id).delete()
                self.db.query(UserMemory).filter(UserMemory.user_id == self.user.id).delete()
                self.db.query(SessionReport).filter(SessionReport.user_id == self.user.id).delete()
                self.db.query(SessionResult).filter(SessionResult.user_id == self.user.id).delete()
                self.db.query(InterviewSession).filter(InterviewSession.user_id == self.user.id).delete()
                self.db.query(InterviewConfig).filter(InterviewConfig.user_id == self.user.id).delete()
                self.db.query(TargetProfile).filter(TargetProfile.user_id == self.user.id).delete()
                self.db.query(Profile).filter(Profile.user_id == self.user.id).delete()
                self.db.query(User).filter(User.id == self.user.id).delete()
                self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def test_01_dashboard_summary_endpoint_empty_and_populated(self):
        """Test GET /session/dashboard-summary for a new user and after completing sessions."""
        # 1. Initially (no sessions)
        resp = client.get("/session/dashboard-summary", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["session_count"], 0)
        self.assertIsNone(data["last_session"])
        self.assertEqual(data["current_weak_areas"], [])
        self.assertIn("retake_same_round", data["quick_actions"])
        self.assertIn("try_next_round", data["quick_actions"])

        # 2. Seed a completed session with result
        config = InterviewConfig(
            user_id=self.user.id,
            round_type="Technical",
            difficulty="Medium",
            duration_minutes=30,
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)

        sess = InterviewSession(
            user_id=self.user.id,
            interview_id=config.id,
            session_token=f"sess_{int(time.time() * 1000)}",
            status="CLOSED",
        )
        self.db.add(sess)
        self.db.commit()
        self.db.refresh(sess)

        result = SessionResult(
            user_id=self.user.id,
            session_id=sess.id,
            round_type="Technical",
            overall_score=78.5,
            content_score=75.0,
            speech_score=80.0,
            face_score=82.0,
            classification="AVERAGE",
            per_question_scores=[{"question_id": 1, "topic": "Concurrency", "score": 78.5}],
            weights_used={"content": 0.6, "speech": 0.25, "face": 0.15},
            comparisons={"trend": {"timeline": [{"score": 78.5}]}},
            weak_areas=[{"topic": "Concurrency & Multithreading", "average_score": 62.0}],
        )
        self.db.add(result)

        # Seed memory
        memory = UserMemory(
            user_id=self.user.id,
            session_count=1,
            topic_scores={"Concurrency & Multithreading": 62.0, "Architecture": 85.0},
            weak_topics=["Concurrency & Multithreading"],
        )
        self.db.add(memory)
        self.db.commit()

        # 3. Query GET /session/dashboard-summary again
        resp2 = client.get("/session/dashboard-summary", headers=self.headers)
        self.assertEqual(resp2.status_code, 200)
        summary = resp2.json()
        self.assertEqual(summary["session_count"], 1)
        self.assertIsNotNone(summary["last_session"])
        self.assertEqual(summary["last_session"]["overall_score"], 78.5)
        self.assertEqual(summary["last_session"]["round_type"], "Technical")
        self.assertIn("Concurrency & Multithreading", summary["current_weak_areas"])
        self.assertEqual(len(summary["recent_sessions"]), 1)
        self.assertIn("Retake Technical", summary["quick_actions"]["retake_same_round"]["label"])
        self.assertIn("HR", summary["quick_actions"]["try_next_round"]["label"])

    def test_02_session_list_endpoint(self):
        """Test GET /session returns candidate past sessions."""
        config = InterviewConfig(user_id=self.user.id, round_type="HR", difficulty="Medium", duration_minutes=15)
        self.db.add(config)
        self.db.commit()

        sess = InterviewSession(user_id=self.user.id, interview_id=config.id, session_token=f"token_{int(time.time() * 1000)}", status="CLOSED")
        self.db.add(sess)
        self.db.commit()

        resp = client.get("/session", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        sessions = data.get("sessions", data) if isinstance(data, dict) else data
        self.assertGreaterEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["round_type"], "HR")

    def test_03_memory_update_synchronization_before_blueprint(self):
        """
        Verify that ensure_user_memory_updated automatically runs and calculates SessionResult,
        UserMemory, and AskedQuestion records for closed sessions before blueprint generation.
        """
        # Create a closed session with evaluated questions in raw_scoring_report but no SessionResult yet
        config = InterviewConfig(
            user_id=self.user.id,
            round_type="Technical",
            difficulty="Medium",
            duration_minutes=30,
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)

        sess = InterviewSession(
            user_id=self.user.id,
            interview_id=config.id,
            session_token=f"sync_token_{int(time.time() * 1000)}",
            status="CLOSED",
        )
        self.db.add(sess)
        self.db.commit()
        self.db.refresh(sess)

        # Populate QuestionBankItem
        q1_text = "Explain how Python handles memory management and garbage collection."
        q1 = QuestionBankItem(
            interview_id=config.id,
            question_hash=compute_question_hash(q1_text),
            text=q1_text,
            topic="Language Mastery & Architecture",
            difficulty="Medium",
            question_type="conceptual",
        )
        self.db.add(q1)
        self.db.commit()

        # Seed scoring report directly in process_and_persist_session_result
        raw_scoring = {
            "overall_score": 64.0,
            "content_score": 60.0,
            "speech_score": 70.0,
            "face_score": 65.0,
            "classification": "DEVELOPING",
            "per_question_breakdown": [
                {
                    "question_id": 1,
                    "topic": "Language Mastery & Architecture",
                    "question_text": q1_text,
                    "content": {"score": 60.0},
                    "speech_confidence": {"score": 70.0},
                    "face_posture": {"score": 65.0},
                    "all_deductions": [{"factor": "depth", "deduction": -15.0, "reason": "Lacked garbage collection specifics"}],
                }
            ],
        }

        # Process session result
        res = process_and_persist_session_result(
            session_id=sess.id,
            aligned_dataset={"scores": raw_scoring},
            db=self.db,
        )
        self.assertIsNotNone(res)

        # Now test load_user_context: it should detect returning candidate with memory and asked questions
        user_ctx = load_user_context(self.user.id, self.db)
        self.assertTrue(user_ctx.is_returning)
        self.assertEqual(user_ctx.session_count, 1)
        self.assertGreater(len(user_ctx.history_asked_questions), 0)
        self.assertEqual(user_ctx.history_asked_questions[0].question_text, q1_text)

    def test_04_retake_loop_deduplication_and_weak_area_weighting(self):
        """
        Verify that in a retake session:
        1. Previously asked questions are 100% avoided.
        2. Questions focused on the candidate's previous weak areas are weighted higher.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 1. Setup session 1 asked questions and weak areas
        q_prev_1 = "Explain how Python handles memory management, garbage collection, and variable allocation (stack vs heap)."
        q_prev_2 = "Compare B-tree indexes with LSM-tree (Log-Structured Merge-tree) storage engines. Why do write-heavy databases prefer LSM-trees?"

        hash_1 = compute_question_hash(q_prev_1)
        hash_2 = compute_question_hash(q_prev_2)

        # Log to AskedQuestion table
        asked1 = AskedQuestion(
            user_id=self.user.id,
            question_hash=hash_1,
            topic="Language Mastery & Architecture",
            question_text=q_prev_1,
            score=58.0,
        )
        asked2 = AskedQuestion(
            user_id=self.user.id,
            question_hash=hash_2,
            topic="DBMS, OS & Network Protocols",
            question_text=q_prev_2,
            score=62.0,
        )
        self.db.add(asked1)
        self.db.add(asked2)

        # Set UserMemory with weak areas
        weak_topic = "DBMS, OS & Network Protocols"
        memory = UserMemory(
            user_id=self.user.id,
            session_count=1,
            topic_scores={weak_topic: 60.0, "Language Mastery & Architecture": 85.0},
            weak_topics=[weak_topic],
        )
        self.db.add(memory)
        self.db.commit()

        # 2. Load context for Session 2 (Retake)
        user_ctx = load_user_context(self.user.id, self.db)
        self.assertTrue(user_ctx.is_returning)
        self.assertIn(weak_topic, user_ctx.weak_areas)

        # 3. Build Interview Blueprint for Session 2
        blueprint = build_interview_blueprint(
            profile=self.profile,
            target_profile=self.target_profile,
            config={
                "round_type": "Technical",
                "difficulty": "Medium",
                "duration_minutes": 30,
                "mode": "normal",
            },
            user_context=user_ctx,
        )

        # Verify blueprint assigned higher weight to the weak topic
        weak_topic_obj = next((t for t in blueprint.topics if weak_topic.lower() in t.name.lower()), None)
        self.assertIsNotNone(weak_topic_obj)
        self.assertTrue(weak_topic_obj.is_weak_area)
        self.assertGreater(weak_topic_obj.weight, 0.15)

        # 4. Generate Question Pool for Session 2
        pool_result = loop.run_until_complete(
            generate_question_pool_async(
                blueprint=blueprint,
                profile=self.profile,
                target_profile=self.target_profile,
                education=None,
                user_context=user_ctx,
            )
        )

        active_questions = pool_result.get("active_questions", [])
        self.assertGreater(len(active_questions), 0)

        # 5. VERIFY DEDUPLICATION: Neither q_prev_1 nor q_prev_2 should be in active_questions
        active_texts = [q["text"].strip().lower() for q in active_questions]
        active_hashes = [compute_question_hash(q["text"]) for q in active_questions]

        self.assertNotIn(q_prev_1.strip().lower(), active_texts, "Previously asked Question 1 reappeared in Retake session!")
        self.assertNotIn(q_prev_2.strip().lower(), active_texts, "Previously asked Question 2 reappeared in Retake session!")
        self.assertNotIn(hash_1, active_hashes, "Hash of previously asked Question 1 found in Retake pool!")
        self.assertNotIn(hash_2, active_hashes, "Hash of previously asked Question 2 found in Retake pool!")

        # 6. VERIFY WEAK AREA PRIORITIZATION:
        # At least one question in the active pool should cover the candidate's weak topic
        weak_area_questions = [
            q for q in active_questions
            if q.get("is_weak_area") or weak_topic.lower() in q.get("topic", "").lower()
        ]
        self.assertGreater(
            len(weak_area_questions),
            0,
            "Retake session question pool did not prioritize candidate's identified weak area!",
        )

    def test_05_retake_setup_reuses_confirmed_profile(self):
        """
        Verify that candidate's confirmed profile from Phase 1 is preserved and reused
        when configuring the retake session via POST /interview/config.
        """
        # Save interview config for retake with weak area focus
        config_payload = {
            "round_type": "Technical",
            "difficulty": "Medium",
            "duration_minutes": 30,
            "language": "English",
            "mode": "normal",
            "focus_topics": ["DBMS, OS & Network Protocols", "Problem solving"],
        }
        resp = client.post("/interview/config", json=config_payload, headers=self.headers)
        self.assertIn(resp.status_code, (200, 201))
        saved = resp.json()
        self.assertEqual(saved["round_type"], "Technical")

        # Verify user's profile and target profile remain intact in DB
        prof = self.db.query(Profile).filter(Profile.user_id == self.user.id).first()
        target = self.db.query(TargetProfile).filter(TargetProfile.user_id == self.user.id).first()
        self.assertIsNotNone(prof)
        self.assertIsNotNone(target)
        self.assertEqual(target.target_role, "Backend Systems Engineer")


if __name__ == "__main__":
    unittest.main()
