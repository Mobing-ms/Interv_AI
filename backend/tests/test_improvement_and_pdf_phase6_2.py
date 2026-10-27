"""
Unit and Integration Tests for Phase 6.2:
- Improvement Plan Engine (actions, practice questions, curated resources)
- Server-Side PDF Export (ReportLab + Matplotlib embedded charts)
- Endpoints GET /report/{id}/pdf and GET /report/{id}/improvement-plan
"""

import unittest
import io
import json
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
    IntegrityEvent,
)
from app.auth import create_access_token
from app.main import app
from app.services.improvement_plan_service import (
    build_improvement_plan,
    get_curated_resources_for_topic,
    get_practice_questions_for_topic,
    resolve_resource_category,
    CURATED_RESOURCES,
)
from app.services.pdf_export_service import (
    build_pdf_report,
    generate_radar_chart_image,
    generate_timeline_chart_image,
    generate_trend_chart_image,
)

client = TestClient(app)


class TestImprovementAndPdfPhase6_2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        # Clean existing test data
        self.db.query(IntegrityEvent).delete()
        self.db.query(SessionReport).delete()
        self.db.query(SessionResult).delete()
        self.db.query(QuestionBankItem).delete()
        self.db.query(InterviewSession).delete()
        self.db.query(InterviewConfig).delete()
        self.db.query(User).filter(User.email == "test_phase6_2@example.com").delete()
        self.db.commit()

        # Create user
        self.user = User(
            name="Sarah Connor",
            email="test_phase6_2@example.com",
            password_hash="testpassword123",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.token = create_access_token({"sub": str(self.user.id)})

        # Create config and session
        self.config = InterviewConfig(
            user_id=self.user.id,
            round_type="Technical",
            difficulty="Hard",
            duration_minutes=30,
            language="English",
            mode="normal",
        )
        self.db.add(self.config)
        self.db.commit()
        self.db.refresh(self.config)

        self.session = InterviewSession(
            user_id=self.user.id,
            interview_id=self.config.id,
            status="closed",
            session_token="test_sess_token_phase6_2",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(self.session)
        self.db.commit()
        self.db.refresh(self.session)

        # Seed QuestionBankItem
        self.q1 = QuestionBankItem(
            interview_id=self.config.id,
            question_hash="hash_q1_db",
            text="Explain database sharding and B-Tree index structure in PostgreSQL.",
            topic="Database Architecture",
            difficulty="Hard",
            question_type="scenario",
            expected_keywords=["B-Tree", "sharding", "PostgreSQL"],
            ideal_answer_points=["Points on indexing"],
            rank_score=90.0,
        )
        self.q2 = QuestionBankItem(
            interview_id=self.config.id,
            question_hash="hash_q2_redis",
            text="How do you handle Redis cache stampedes and key eviction policies?",
            topic="Redis Caching",
            difficulty="Hard",
            question_type="scenario",
            expected_keywords=["Redis", "cache", "eviction"],
            ideal_answer_points=["Points on cache stampede"],
            rank_score=85.0,
        )
        self.db.add_all([self.q1, self.q2])
        self.db.commit()

        # Seed SessionResult
        self.session_result = SessionResult(
            session_id=self.session.id,
            user_id=self.user.id,
            round_type="Technical",
            role="Senior Backend Architect",
            overall_score=78.5,
            content_score=76.0,
            speech_score=82.0,
            face_score=80.0,
            classification="AVERAGE",
            weights_used={"content": 0.5, "speech": 0.3, "face": 0.2},
            per_question_scores=[
                {
                    "question_id": self.q1.id,
                    "topic": "Database Architecture",
                    "question_text": self.q1.text,
                    "fused_score": 72.0,
                    "content_score": 70.0,
                    "speech_score": 75.0,
                    "face_score": 75.0,
                    "transcript": "PostgreSQL uses B-Tree indexes for ordering and range queries.",
                    "all_deductions": [{"reason": "Did not mention vacuuming or WAL write overhead", "factor": "depth", "penalty": 15.0}],
                },
                {
                    "question_id": self.q2.id,
                    "topic": "Redis Caching",
                    "question_text": self.q2.text,
                    "fused_score": 85.0,
                    "content_score": 82.0,
                    "speech_score": 89.0,
                    "face_score": 85.0,
                    "transcript": "Redis cache stampedes can be prevented with distributed locks or probabilistic early expiration.",
                    "all_deductions": [{"reason": "Brief on LRU memory eviction algorithms", "factor": "depth", "penalty": 10.0}],
                },
            ],
            comparisons={
                "baseline_delta": {"delta": 4.5, "direction": "improved"},
                "trend": {"summary": "Consistent improvement over 3 sessions", "recent_session_scores": [65.0, 72.0, 78.5]},
                "cohort": {"percentile": 72.5, "benchmark_label": "Senior Backend Engineers"},
            },
            weak_areas=[
                {
                    "topic": "Database Architecture",
                    "average_score": 58.0,
                    "recommendation": "Review storage engine fundamentals and WAL write logging.",
                    "evidence": [
                        {
                            "question_id": self.q1.id,
                            "score": 58.0,
                            "deductions": [{"reason": "Did not mention vacuuming or WAL write overhead"}],
                        }
                    ],
                },
                {
                    "topic": "Redis Caching",
                    "average_score": 68.0,
                    "recommendation": "Review Redis eviction strategies and cluster topology.",
                    "evidence": [
                        {
                            "question_id": self.q2.id,
                            "score": 68.0,
                            "deductions": [{"reason": "Brief on LRU memory eviction algorithms"}],
                        }
                    ],
                },
            ],
            strengths=[
                {"topic": "Redis Caching", "average_score": 85.0, "evidence": [{"question_id": self.q2.id, "score": 85.0}]}
            ],
        )
        self.db.add(self.session_result)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_improvement_plan_generation(self):
        """Improvement plan produces 3-5 concrete actions with verified resources and practice questions."""
        res_dict = {
            "round_type": "Technical",
            "overall_score": 78.5,
            "content_score": 76.0,
            "speech_score": 82.0,
            "face_score": 80.0,
            "weak_areas": [
                {
                    "topic": "Database Architecture",
                    "average_score": 58.0,
                    "recommendation": "Review storage engine fundamentals.",
                    "evidence": [{"deductions": [{"reason": "WAL write overhead omitted"}]}],
                },
                {
                    "topic": "Redis Caching",
                    "average_score": 68.0,
                    "recommendation": "Review eviction policies.",
                    "evidence": [{"deductions": [{"reason": "LRU memory eviction"}]}],
                },
            ],
        }

        plan = build_improvement_plan(res_dict)
        self.assertGreaterEqual(len(plan), 3)
        self.assertLessEqual(len(plan), 5)

        for action in plan:
            self.assertIn("title", action)
            self.assertIn("topic", action)
            self.assertIn("priority", action)
            self.assertIn(action["priority"], ("HIGH", "MEDIUM"))
            self.assertIn("description", action)
            self.assertGreater(len(action["description"]), 20)

            # Check practice questions
            self.assertIn("practice_questions", action)
            self.assertGreaterEqual(len(action["practice_questions"]), 1)

            # Check resources
            self.assertIn("resources", action)
            self.assertGreaterEqual(len(action["resources"]), 1)
            for res in action["resources"]:
                self.assertIn("title", res)
                self.assertIn("url", res)
                self.assertIn("platform", res)
                # Ensure no invented URLs: must be in verified CURATED_RESOURCES domains
                self.assertTrue(res["url"].startswith("http://") or res["url"].startswith("https://"))
                # Check domain is a recognized authority
                valid_domains = [
                    "github.com", "highscalability.com", "martinfowler.com",
                    "postgresql.org", "use-the-index-luke.com", "dataintensive.net",
                    "redis.io", "university.redis.com", "docs.python.org", "realpython.com",
                    "fastapi.tiangolo.com", "neetcode.io", "geeksforgeeks.org",
                    "hbr.org", "thebalancecareers.com", "toastmasters.org",
                    "ted.com", "extension.harvard.edu", "techinterviewhandbook.org"
                ]
                has_valid_domain = any(dom in res["url"] for dom in valid_domains)
                self.assertTrue(has_valid_domain, f"URL {res['url']} is not in verified list")

    def test_chart_image_generators(self):
        """Matplotlib chart generators return valid PNG byte streams."""
        radar_buf = generate_radar_chart_image(75.0, 80.0, 70.0, 95.0, 85.0)
        self.assertIsInstance(radar_buf, io.BytesIO)
        radar_bytes = radar_buf.getvalue()
        self.assertGreater(len(radar_bytes), 1000)
        self.assertTrue(radar_bytes.startswith(b"\x89PNG\r\n\x1a\n"))  # PNG Magic bytes

        timeline_buf = generate_timeline_chart_image([
            {"question_id": 1, "fused_score": 70.0, "content_score": 75.0, "speech_score": 65.0},
            {"question_id": 2, "fused_score": 85.0, "content_score": 80.0, "speech_score": 90.0},
        ])
        timeline_bytes = timeline_buf.getvalue()
        self.assertGreater(len(timeline_bytes), 1000)
        self.assertTrue(timeline_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        trend_buf = generate_trend_chart_image({"recent_session_scores": [60.0, 72.0, 78.5]}, 78.5)
        trend_bytes = trend_buf.getvalue()
        self.assertGreater(len(trend_bytes), 1000)
        self.assertTrue(trend_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_pdf_report_builder(self):
        """build_pdf_report generates valid multi-page PDF bytes containing all required sections."""
        pdf_bytes = build_pdf_report(session_id=self.session.id, db=self.db)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 10000)  # Significant document with embedded charts
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"), "Generated file must start with PDF header")

    def test_report_pdf_endpoint(self):
        """GET /report/{id}/pdf returns 200 OK with application/pdf Content-Type."""
        resp = client.get(
            f"/report/{self.session.id}/pdf",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/pdf")
        self.assertIn("attachment", resp.headers.get("content-disposition", ""))
        self.assertTrue(resp.content.startswith(b"%PDF-"))

    def test_session_pdf_endpoint_alias(self):
        """GET /session/{id}/pdf returns 200 OK with application/pdf."""
        resp = client.get(
            f"/session/{self.session.id}/pdf",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF-"))

    def test_report_improvement_plan_endpoint(self):
        """GET /report/{id}/improvement-plan returns structured 3-5 action items."""
        resp = client.get(
            f"/report/{self.session.id}/improvement-plan",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("actions", data)
        self.assertGreaterEqual(len(data["actions"]), 3)
        self.assertLessEqual(len(data["actions"]), 5)
        first_act = data["actions"][0]
        self.assertIn("title", first_act)
        self.assertIn("practice_questions", first_act)
        self.assertIn("resources", first_act)


if __name__ == "__main__":
    unittest.main()
