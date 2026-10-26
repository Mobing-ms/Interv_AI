"""
Unit Tests for Phase 5.3: Score Fusion, Comparisons, Weak-Area Ranking & Memory Updates.
Tests:
1. Round-Type Score Fusion: Content-heavy for Technical, communication-heavy for HR/Behavioral, storing weights_used.
2. Comparisons:
   - User baseline comparison (first session target baseline vs subsequent personal averages).
   - Session trend trajectory (improving, declining, stable).
   - Cohort percentile rank (seeded benchmark when N < 5 vs empirical platform cohort when N >= 5).
3. Weak-Area Ranking:
   - Ranked by score deficit, repeated weakness in UserMemory, and integrity/delivery issues.
   - Top 3-5 weak areas with question IDs, scores, and exact deduction evidence.
4. U Memory Update:
   - UserMemory updated with topic averages, weak tags, session count.
   - AskedQuestion table logs question hash, topic, text, and score.
5. SessionResult Table Persistence:
   - Row persisted with complete fused and comparison payload.
6. REST API: GET /session/{id}/result integration.
"""

import time
import unittest
from typing import Dict, Any

from app.database import SessionLocal, Base, engine
from app.models import (
    User,
    InterviewConfig,
    InterviewSession,
    SessionResult,
    UserMemory,
    AskedQuestion,
    IntegrityEvent,
)
from app.services.score_fusion_service import (
    get_round_type_weights,
    fuse_session_scores,
    compute_cohort_percentile,
    compute_session_comparisons,
    rank_weak_areas,
    execute_u_memory_update,
    process_and_persist_session_result,
)
from app.routers.auth import create_access_token
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestScoreFusionPhase53(unittest.TestCase):
    """Test suite for Phase 5.3 score fusion and comparisons."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        # Seed test user
        email = f"fusion_tester_{int(time.time() * 1000)}@example.com"
        self.user = User(
            email=email,
            name="Fusion Tester",
            password_hash="testpasshash",
            auth_provider="email",
            is_verified=True,
            onboarding_status="completed",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.token = create_access_token({"sub": str(self.user.id)})

        # Seed InterviewConfig
        self.config = InterviewConfig(
            user_id=self.user.id,
            round_type="Technical",
            difficulty="Medium",
            duration_minutes=20,
        )
        self.db.add(self.config)
        self.db.commit()
        self.db.refresh(self.config)

        # Seed InterviewSession
        self.session = InterviewSession(
            user_id=self.user.id,
            interview_id=self.config.id,
            session_token=f"token_{int(time.time() * 1000)}",
            status="CLOSED",
        )
        self.db.add(self.session)
        self.db.commit()
        self.db.refresh(self.session)

    def tearDown(self):
        self.db.close()

    # =========================================================================
    # 1. SCORE FUSION & ROUND TYPE WEIGHTS
    # =========================================================================

    def test_round_type_weights_and_fusion(self):
        """Tests that Technical is content-heavy and HR is communication-heavy."""
        w_tech = get_round_type_weights("Technical")
        w_hr = get_round_type_weights("HR")
        w_sys = get_round_type_weights("System Design")

        # Technical: content >= 0.55
        self.assertGreaterEqual(w_tech["content"], 0.55)
        self.assertLess(w_tech["speech"], 0.30)

        # HR: content <= 0.40, speech + face >= 0.60
        self.assertLessEqual(w_hr["content"], 0.40)
        self.assertGreaterEqual(w_hr["speech"] + w_hr["face"], 0.60)

        # Mock question breakdown
        raw_report = {
            "per_question_breakdown": [
                {
                    "question_id": 1,
                    "topic": "Algorithms",
                    "content": {"score": 90.0},
                    "speech_confidence": {"score": 60.0},
                    "face_posture": {"score": 50.0},
                    "all_deductions": [],
                }
            ],
            "top_deductions": [],
            "key_strengths": ["Strong content knowledge"],
        }

        # Technical fusion: 90 * 0.60 + 60 * 0.25 + 50 * 0.15 = 54 + 15 + 7.5 = 76.5
        fused_tech = fuse_session_scores(raw_report, round_type="Technical")
        self.assertEqual(fused_tech["weights_used"]["content"], 0.60)
        self.assertEqual(fused_tech["per_question_breakdown"][0]["fused_score"], 76.5)

        # HR fusion: 90 * 0.35 + 60 * 0.35 + 50 * 0.30 = 31.5 + 21 + 15 = 67.5
        fused_hr = fuse_session_scores(raw_report, round_type="HR")
        self.assertEqual(fused_hr["weights_used"]["content"], 0.35)
        self.assertEqual(fused_hr["per_question_breakdown"][0]["fused_score"], 67.5)

        # Stored weights_used must be present
        self.assertIn("weights_used", fused_tech)
        self.assertIn("weights_used", fused_hr)

    # =========================================================================
    # 2. COMPARISONS (BASELINE, TREND & COHORT PERCENTILE)
    # =========================================================================

    def test_comparisons_user_baseline_and_trend(self):
        """Tests personal baseline comparison and trend trajectory across sessions."""
        # 1. First session (no prior history)
        comp_1 = compute_session_comparisons(
            user_id=self.user.id,
            session_id=self.session.id,
            current_score=82.0,
            round_type="Technical",
            db=self.db,
        )
        self.assertTrue(comp_1["baseline"]["is_first_session"])
        self.assertEqual(comp_1["baseline"]["delta"], 12.0)  # 82.0 - 70.0
        self.assertEqual(comp_1["trend"]["direction"], "baseline_established")

        # Seed 2 prior session results for this user
        s_id_1 = int(time.time() * 1000) + 100
        s_id_2 = int(time.time() * 1000) + 200
        prior_1 = SessionResult(
            session_id=s_id_1,
            user_id=self.user.id,
            round_type="Technical",
            overall_score=70.0,
            content_score=72.0,
            speech_score=68.0,
            face_score=70.0,
            classification="AVERAGE",
            weights_used={"content": 0.6, "speech": 0.25, "face": 0.15},
            per_question_scores=[],
            comparisons={},
            weak_areas=[],
            strengths=[],
        )
        prior_2 = SessionResult(
            session_id=s_id_2,
            user_id=self.user.id,
            round_type="Technical",
            overall_score=76.0,
            content_score=78.0,
            speech_score=74.0,
            face_score=76.0,
            classification="AVERAGE",
            weights_used={"content": 0.6, "speech": 0.25, "face": 0.15},
            per_question_scores=[],
            comparisons={},
            weak_areas=[],
            strengths=[],
        )
        self.db.add(prior_1)
        self.db.add(prior_2)
        self.db.commit()

        # 2. Subsequent session (score 84.0) -> baseline avg of [70.0, 76.0] = 73.0 -> delta +11.0
        comp_2 = compute_session_comparisons(
            user_id=self.user.id,
            session_id=self.session.id,
            current_score=84.0,
            round_type="Technical",
            db=self.db,
        )
        self.assertFalse(comp_2["baseline"]["is_first_session"])
        self.assertEqual(comp_2["baseline"]["user_baseline_score"], 73.0)
        self.assertEqual(comp_2["baseline"]["delta"], 11.0)
        self.assertEqual(comp_2["trend"]["direction"], "improving")
        self.assertGreater(comp_2["trend"]["trend_delta"], 0)

    def test_cohort_percentile_seeded_vs_platform(self):
        """With N < 5 no percentile is invented; with N >= 5 the platform cohort is used."""
        # Case A: too few real sessions -> no percentile, no made-up benchmark
        seeded_res = compute_cohort_percentile(score=85.0, round_type="Technical", past_cohort_scores=[])
        self.assertFalse(seeded_res["is_seeded_benchmark"])
        self.assertIsNone(seeded_res["percentile"])
        self.assertIsNone(seeded_res["delta_vs_cohort"])

        # Case B: Platform cohort (5+ scores: [60, 65, 70, 75, 80, 85, 90])
        cohort_sample = [60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0]
        platform_res = compute_cohort_percentile(score=82.0, round_type="Technical", past_cohort_scores=cohort_sample)
        self.assertFalse(platform_res["is_seeded_benchmark"])
        self.assertIn("Platform Cohort", platform_res["benchmark_label"])
        # 5 out of 7 scores are <= 82.0 -> ~71.4 percentile
        self.assertAlmostEqual(platform_res["percentile"], 71.4, delta=1.0)

    # =========================================================================
    # 3. WEAK-AREA RANKING WITH EVIDENCE
    # =========================================================================

    def test_weak_area_ranking_with_evidence(self):
        """Tests ranking topics by lowest scores, repeated weakness, and integrity issues with evidence."""
        questions_fused = [
            {
                "question_id": 1,
                "question_text": "Explain distributed caching in Redis",
                "topic": "System Design",
                "fused_score": 42.0,
                "content": {"score": 38.0},
                "speech_confidence": {"score": 50.0},
                "face_posture": {"score": 45.0},
                "all_deductions": [
                    {"factor": "keyword_coverage", "deduction": -15.0, "reason": "Missed idempotency and cache invalidation"},
                    {"factor": "speech_pace", "question_id": 1, "deduction": -8.0, "reason": "Speaking pace was 75 WPM (too slow)"},
                ],
            },
            {
                "question_id": 2,
                "question_text": "Design a rate limiter",
                "topic": "System Design",
                "fused_score": 50.0,
                "content": {"score": 48.0},
                "speech_confidence": {"score": 55.0},
                "face_posture": {"score": 52.0},
                "all_deductions": [
                    {"factor": "accuracy", "deduction": -12.0, "reason": "Did not explain sliding window log counter"},
                ],
            },
            {
                "question_id": 3,
                "question_text": "Describe a difficult conflict you resolved",
                "topic": "Leadership",
                "fused_score": 75.0,
                "content": {"score": 78.0},
                "speech_confidence": {"score": 72.0},
                "face_posture": {"score": 75.0},
                "all_deductions": [
                    {"factor": "star_structure", "question_id": 3, "deduction": -7.5, "reason": "Missing Result metric in STAR"},
                ],
            },
        ]

        past_weaks = ["System Design"]  # Repeated weak topic
        integrity_events = [{"id": 1, "type": "tab_switch"}]

        ranked = rank_weak_areas(
            per_question_fused=questions_fused,
            user_past_weak_topics=past_weaks,
            integrity_events=integrity_events,
        )

        # Must return top 3-5 weak areas
        self.assertGreaterEqual(len(ranked), 3)
        self.assertLessEqual(len(ranked), 5)

        # Top weak area should be System Design (lowest score + repeated)
        top_weak = ranked[0]
        self.assertEqual(top_weak["topic"], "System Design")
        self.assertEqual(top_weak["severity"], "HIGH")
        self.assertTrue(top_weak["is_repeated"])
        self.assertEqual(top_weak["repetition_count"], 2)

        # Must include evidence with question IDs and scores
        self.assertGreater(len(top_weak["evidence"]), 0)
        ev_q1 = next(e for e in top_weak["evidence"] if e["question_id"] == 1)
        self.assertEqual(ev_q1["score"], 42.0)
        self.assertIn("Explain distributed caching", ev_q1["question_text"])

    # =========================================================================
    # 4. U MEMORY UPDATE & ASKED QUESTION HISTORY
    # =========================================================================

    def test_u_memory_update_and_asked_question_history(self):
        """Tests that execute_u_memory_update updates UserMemory and AskedQuestion records."""
        questions = [
            {
                "question_id": 10,
                "question_text": "How do B-trees work in relational databases?",
                "topic": "Database Internals",
                "fused_score": 58.0,
            },
            {
                "question_id": 11,
                "question_text": "Explain goroutine scheduling in Go",
                "topic": "Concurrency",
                "fused_score": 82.0,
            },
        ]
        weak_areas = [
            {"topic": "Database Internals", "severity": "HIGH"},
            {"topic": "Speech Pacing", "severity": "MEDIUM"},
        ]

        update_info = execute_u_memory_update(
            user_id=self.user.id,
            session_id=self.session.id,
            per_question_fused=questions,
            ranked_weak_areas=weak_areas,
            overall_score=70.0,
            db=self.db,
        )

        # Verify UserMemory
        user_mem: UserMemory = self.db.query(UserMemory).filter(UserMemory.user_id == self.user.id).first()
        self.assertIsNotNone(user_mem)
        self.assertIn("Database Internals", user_mem.topic_scores)
        self.assertEqual(user_mem.topic_scores["Database Internals"], 58.0)
        self.assertIn("Concurrency", user_mem.topic_scores)
        self.assertEqual(user_mem.topic_scores["Concurrency"], 82.0)
        self.assertIn("Database Internals", user_mem.weak_topics)
        self.assertIn("Speech Pacing", user_mem.weak_topics)
        self.assertEqual(user_mem.session_count, 1)

        # Verify AskedQuestion history table
        asked_records = (
            self.db.query(AskedQuestion)
            .filter(AskedQuestion.user_id == self.user.id)
            .all()
        )
        self.assertEqual(len(asked_records), 2)
        q_topics = [a.topic for a in asked_records]
        self.assertIn("Database Internals", q_topics)
        self.assertIn("Concurrency", q_topics)
        # Check hashes are 64-char sha256
        for a in asked_records:
            self.assertEqual(len(a.question_hash), 64)

    # =========================================================================
    # 5. UNIFIED PIPELINE RUNNER & REST ENDPOINT
    # =========================================================================

    def test_process_and_persist_session_result_and_rest(self):
        """Tests process_and_persist_session_result and GET /session/{id}/result."""
        aligned_mock = {
            "session_id": self.session.id,
            "calibration": {"face_baseline": {"eye_contact": 0.90}},
            "questions": [
                {
                    "question_id": 1,
                    "topic": "Microservices",
                    "question_text": "What is the Saga pattern in distributed transactions?",
                    "transcript": "The Saga pattern manages distributed transactions via choreographies or orchestrators.",
                    "face_signals": {"avg_eye_contact": 0.88, "avg_head_yaw": 2.0},
                    "speech_signals": {"avg_speech_pace_wpm": 138.0, "filler_rate": 0.015},
                    "evaluator_scores": {"correctness": 8.8, "depth": 8.5, "classification": "STRONG"},
                }
            ],
        }

        # 1. Process and persist
        result = process_and_persist_session_result(
            session_id=self.session.id,
            aligned_dataset=aligned_mock,
            db=self.db,
        )

        self.assertEqual(result["session_id"], self.session.id)
        self.assertEqual(result["round_type"], "Technical")
        self.assertIn("weights_used", result)
        self.assertIn("comparisons", result)
        self.assertIn("weak_areas", result)
        self.assertIn("user_memory", result)

        # Verify DB row exists in SessionResult
        db_res = self.db.query(SessionResult).filter(SessionResult.session_id == self.session.id).first()
        self.assertIsNotNone(db_res)
        self.assertEqual(db_res.overall_score, result["overall_score"])

        # 2. REST Endpoint GET /session/{id}/result
        resp = client.get(
            f"/session/{self.session.id}/result",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["session_id"], self.session.id)
        self.assertIn("overall_score", data)
        self.assertIn("weights_used", data)
        self.assertIn("comparisons", data)
        self.assertIn("weak_areas", data)
        self.assertIn("user_memory", data)


if __name__ == "__main__":
    unittest.main()
