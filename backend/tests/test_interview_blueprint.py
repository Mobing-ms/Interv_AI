import sys
import os
import unittest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.database import SessionLocal, Base, engine
from app.models import User, Profile, TargetProfile, InterviewConfig, UserMemory
from app.auth import hash_password, create_access_token
from app.schemas import (
    StructuredCV,
    TargetProfileOut,
    InterviewConfigCreate,
    UserContextOut,
)
from app.services.interview_blueprint import build_interview_blueprint

Base.metadata.create_all(bind=engine)
client = TestClient(app)

SAMPLE_PROFILE = {
    "personal": {
        "name": "Sarah Chen",
        "email": "sarah.chen@example.com",
        "phone": "+1-555-0144",
        "links": ["https://github.com/sarahchen"]
    },
    "education": [
        {
            "degree": "Bachelor of Science",
            "branch": "Computer Science",
            "college": "UC Berkeley",
            "year": 2025,
            "cgpa": 3.9
        }
    ],
    "skills": {
        "languages": ["TypeScript", "Python", "Go"],
        "frameworks": ["React", "FastAPI", "Node.js"],
        "tools": ["Docker", "Kubernetes", "PostgreSQL"],
        "domains": ["Distributed Systems", "Fullstack Engineering"],
        "soft": ["Team Leadership", "Product Thinking"]
    },
    "projects": [
        {
            "title": "CloudMetrics Observability",
            "description": "High-throughput metric collection pipeline in Go and Kafka.",
            "tech_stack": ["Go", "Kafka", "PostgreSQL"],
            "role": "Lead Architect",
            "outcomes": "Processed 10M events/day with <50ms p99 latency."
        },
        {
            "title": "React Canvas Editor",
            "description": "Vector graphics editor built with React, WebGL, and Zustand.",
            "tech_stack": ["React", "TypeScript", "Zustand"],
            "role": "Frontend Engineer",
            "outcomes": "60fps rendering under heavy DOM tree loads."
        }
    ],
    "internships_experience": [],
    "certifications": [],
    "achievements": []
}

SAMPLE_TARGET = {
    "target_role": "Senior Fullstack Engineer",
    "company_type": "Product",
    "experience_level": "2-5",
    "job_description": "Building high-performance distributed web platforms."
}


class TestInterviewBlueprint(unittest.TestCase):

    def test_technical_round_blueprint(self):
        config = {
            "round_type": "Technical",
            "difficulty": "Medium",
            "duration_minutes": 30,
            "mode": "normal",
        }
        bp = build_interview_blueprint(
            profile=SAMPLE_PROFILE,
            target_profile=SAMPLE_TARGET,
            config=config,
            user_context=None,
        )

        self.assertEqual(bp.round_type, "Technical")
        self.assertEqual(bp.duration_minutes, 30)
        self.assertEqual(bp.mode, "normal")
        self.assertEqual(bp.follow_up_limit_per_topic, 2)
        self.assertEqual(bp.time_per_question_seconds, 120)

        # Topic source verification: CV skills, projects, and target role
        topic_names = [t.name for t in bp.topics]
        has_project = any("Project Deep-Dive" in t for t in topic_names)
        has_target_role = any("Senior Fullstack Engineer" in t for t in topic_names)
        has_dsa = any("Data Structures & Algorithms" in t for t in topic_names)

        self.assertTrue(has_project, "Technical blueprint must include project deep-dives from CV")
        self.assertTrue(has_target_role, "Technical blueprint must include target role architecture")
        self.assertTrue(has_dsa, "Technical blueprint must include core CS foundations")

        # Question count and math
        self.assertGreaterEqual(bp.total_question_count, 10)
        allocated_sum = sum(t.allocated_questions for t in bp.topics)
        self.assertEqual(allocated_sum, bp.total_question_count)

        # Strict duration equation
        b = bp.time_breakdown
        self.assertEqual(
            b.warm_up_seconds + b.questions_total_seconds + b.closing_seconds,
            30 * 60,
            "Total allocated seconds must exactly match 30 minutes (1800s)"
        )

    def test_hr_round_blueprint(self):
        config = {
            "round_type": "HR",
            "difficulty": "Easy",
            "duration_minutes": 15,
            "mode": "normal",
        }
        bp = build_interview_blueprint(
            profile=SAMPLE_PROFILE,
            target_profile=SAMPLE_TARGET,
            config=config,
            user_context=None,
        )

        self.assertEqual(bp.round_type, "HR")
        self.assertEqual(bp.duration_minutes, 15)

        topic_names = [t.name for t in bp.topics]
        self.assertTrue(any("Self-Introduction" in t for t in topic_names))
        self.assertTrue(any("Conflict Resolution" in t for t in topic_names))
        self.assertTrue(any("Teamwork" in t for t in topic_names))

        b = bp.time_breakdown
        self.assertEqual(
            b.warm_up_seconds + b.questions_total_seconds + b.closing_seconds,
            15 * 60,
            "Total allocated seconds must exactly match 15 minutes (900s)"
        )

    def test_managerial_round_blueprint(self):
        config = {
            "round_type": "Managerial",
            "difficulty": "Hard",
            "duration_minutes": 45,
            "mode": "normal",
        }
        bp = build_interview_blueprint(
            profile=SAMPLE_PROFILE,
            target_profile=SAMPLE_TARGET,
            config=config,
            user_context=None,
        )

        self.assertEqual(bp.round_type, "Managerial")
        self.assertEqual(bp.duration_minutes, 45)

        topic_names = [t.name for t in bp.topics]
        self.assertTrue(any("Leadership" in t for t in topic_names))
        self.assertTrue(any("Decision-Making" in t for t in topic_names))
        self.assertTrue(any("Ownership" in t for t in topic_names))
        self.assertTrue(any("Prioritization" in t for t in topic_names))

        b = bp.time_breakdown
        self.assertEqual(
            b.warm_up_seconds + b.questions_total_seconds + b.closing_seconds,
            45 * 60,
            "Total allocated seconds must exactly match 45 minutes (2700s)"
        )

    def test_mixed_round_blueprint_with_ratio(self):
        custom_ratio = {"Technical": 0.60, "HR": 0.20, "Managerial": 0.20}
        config = {
            "round_type": "Mixed",
            "difficulty": "Adaptive",
            "duration_minutes": 30,
            "mode": "normal",
        }
        bp = build_interview_blueprint(
            profile=SAMPLE_PROFILE,
            target_profile=SAMPLE_TARGET,
            config=config,
            user_context=None,
            mixed_ratio=custom_ratio,
        )

        self.assertEqual(bp.round_type, "Mixed")
        self.assertIsNotNone(bp.mixed_ratio)
        self.assertAlmostEqual(bp.mixed_ratio["Technical"], 0.60, places=2)

        categories = {t.category for t in bp.topics}
        self.assertIn("Technical", categories)
        self.assertIn("HR", categories)
        self.assertIn("Managerial", categories)

    def test_weak_areas_weight_boosting(self):
        user_context = {
            "is_returning": True,
            "weak_areas": ["React architecture", "Concurrency"],
            "past_scores": {"React architecture": 58.0},
        }
        config = {
            "round_type": "Technical",
            "difficulty": "Medium",
            "duration_minutes": 30,
            "mode": "normal",
        }
        bp = build_interview_blueprint(
            profile=SAMPLE_PROFILE,
            target_profile=SAMPLE_TARGET,
            config=config,
            user_context=user_context,
        )

        # Verify weak topics are identified and marked
        weak_topics = [t for t in bp.topics if t.is_weak_area]
        self.assertGreaterEqual(len(weak_topics), 1)

        # Verify weak topics receive boosted question allocations/weights
        non_weak_topics = [t for t in bp.topics if not t.is_weak_area]
        avg_weak_weight = sum(t.weight for t in weak_topics) / len(weak_topics)
        avg_non_weak_weight = sum(t.weight for t in non_weak_topics) / len(non_weak_topics)
        self.assertGreater(avg_weak_weight, avg_non_weak_weight)

    def test_pressure_mode_halves_timer_and_increases_questions(self):
        normal_config = {
            "round_type": "Technical",
            "difficulty": "Medium",
            "duration_minutes": 30,
            "mode": "normal",
        }
        pressure_config = {
            "round_type": "Technical",
            "difficulty": "Medium",
            "duration_minutes": 30,
            "mode": "pressure",
        }

        bp_normal = build_interview_blueprint(
            profile=SAMPLE_PROFILE,
            target_profile=SAMPLE_TARGET,
            config=normal_config,
        )
        bp_pressure = build_interview_blueprint(
            profile=SAMPLE_PROFILE,
            target_profile=SAMPLE_TARGET,
            config=pressure_config,
        )

        self.assertEqual(bp_normal.time_per_question_seconds, 120)
        self.assertEqual(bp_pressure.time_per_question_seconds, 60)

        # In pressure mode (60s timer), total question count is significantly higher
        self.assertGreater(bp_pressure.total_question_count, bp_normal.total_question_count)
        self.assertGreaterEqual(bp_pressure.total_question_count, 20)

        # Both strictly satisfy the duration math
        self.assertEqual(bp_normal.time_breakdown.total_allocated_seconds, 1800)
        self.assertEqual(bp_pressure.time_breakdown.total_allocated_seconds, 1800)

    def test_duration_math_adds_up_across_all_durations(self):
        durations = [10, 15, 20, 30, 45, 60]
        for d in durations:
            for mode in ["normal", "pressure"]:
                bp = build_interview_blueprint(
                    profile=SAMPLE_PROFILE,
                    target_profile=SAMPLE_TARGET,
                    config={"round_type": "Technical", "duration_minutes": d, "mode": mode},
                )
                expected_total = d * 60
                actual_total = (
                    bp.time_breakdown.warm_up_seconds
                    + bp.time_breakdown.questions_total_seconds
                    + bp.time_breakdown.closing_seconds
                )
                self.assertEqual(
                    actual_total,
                    expected_total,
                    f"Failed duration math for {d} minutes in {mode} mode: {actual_total} != {expected_total}"
                )


class TestInterviewBlueprintEndpoint(unittest.TestCase):

    TEST_EMAIL = "blueprint_endpoint_candidate@example.com"

    def setUp(self):
        self._cleanup()
        self.user_id, self.token = self._create_user_with_profiles()
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == self.TEST_EMAIL).first()
            if user:
                db.query(InterviewConfig).filter(InterviewConfig.user_id == user.id).delete()
                db.query(UserMemory).filter(UserMemory.user_id == user.id).delete()
                db.query(Profile).filter(Profile.user_id == user.id).delete()
                db.query(TargetProfile).filter(TargetProfile.user_id == user.id).delete()
                db.delete(user)
            db.commit()
        finally:
            db.close()

    def _create_user_with_profiles(self):
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            user = User(
                name="David Kim",
                email=self.TEST_EMAIL,
                password_hash=hash_password("Password123!"),
                auth_provider="email",
                is_verified=True,
                onboarding_status="profile_confirmed",
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            # Target Profile
            target = TargetProfile(
                user_id=user.id,
                target_role="Backend Systems Architect",
                company_type="MNC",
                experience_level="5+",
                created_at=now,
                updated_at=now,
            )
            db.add(target)

            # Confirmed Profile
            profile = Profile(
                user_id=user.id,
                structured_data=SAMPLE_PROFILE,
                version=1,
                confirmed_at=now,
                created_at=now,
            )
            db.add(profile)

            # Saved Config
            config = InterviewConfig(
                user_id=user.id,
                round_type="Technical",
                difficulty="Adaptive",
                duration_minutes=30,
                language="English",
                mode="normal",
                created_at=now,
            )
            db.add(config)

            # User Memory with weak area
            mem = UserMemory(
                user_id=user.id,
                topic_scores={"Concurrency": 52.0},
                weak_topics=["Concurrency"],
                session_count=2,
                last_session_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(mem)

            db.commit()
            token = create_access_token({"sub": str(user.id)})
            return user.id, token
        finally:
            db.close()

    def test_post_interview_blueprint_endpoint(self):
        # Call endpoint without payload (defaults to candidate's saved profile & config)
        res = client.post("/interview/blueprint", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["round_type"], "Technical")
        self.assertEqual(data["duration_minutes"], 30)
        self.assertEqual(data["follow_up_limit_per_topic"], 2)
        self.assertGreaterEqual(data["total_question_count"], 10)

        # Check weak area "Concurrency" is included and tagged
        weak_topics = [t for t in data["topics"] if t["is_weak_area"]]
        self.assertTrue(any("Concurrency" in t["name"] for t in weak_topics))

        # Check time breakdown
        tb = data["time_breakdown"]
        self.assertEqual(
            tb["warm_up_seconds"] + tb["questions_total_seconds"] + tb["closing_seconds"],
            1800
        )

    def test_post_interview_blueprint_endpoint_with_overrides(self):
        payload = {
            "round_type": "Mixed",
            "duration_minutes": 45,
            "mode": "pressure",
            "mixed_ratio": {"Technical": 0.5, "HR": 0.3, "Managerial": 0.2}
        }
        res = client.post("/interview/blueprint", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["round_type"], "Mixed")
        self.assertEqual(data["duration_minutes"], 45)
        self.assertEqual(data["mode"], "pressure")
        self.assertEqual(data["time_per_question_seconds"], 60)
        self.assertEqual(data["time_breakdown"]["total_allocated_seconds"], 45 * 60)


if __name__ == "__main__":
    unittest.main()
