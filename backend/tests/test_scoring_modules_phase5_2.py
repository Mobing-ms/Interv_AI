"""
Unit Tests for Phase 5.2: Three Pure Function Scoring Modules & Configurable Engine.
Tests:
1. Face & Posture Scorer: Eye contact vs baseline, pose stability, posture, fidgeting penalty.
2. Speech Confidence Scorer: Speaking pace (120-160 WPM), filler rate, pauses, pitch/volume, clarity.
3. Content Scorer: Accuracy, depth, keywords, STAR completeness for behavioral answers, use of examples.
4. Configurable weights and thresholds via ScoringConfig.
5. Three distinct sample sessions (Strong, Average, Weak):
   - Clearly different scores (strong > average > weak) across all three modules and overall composite.
   - Every deduction has an actionable explanation citing factor and score reduction.
6. Pure function determinism (no side effects).
7. REST endpoint GET /session/{id}/scores integration.
"""

import unittest
from typing import Dict, Any

from app.services.scoring_config import (
    ScoringConfig,
    FacePostureConfig,
    SpeechConfidenceConfig,
    ContentRubricConfig,
    DEFAULT_SCORING_CONFIG,
)
from app.services.scoring_engine import (
    compute_face_and_posture_score,
    compute_speech_confidence_score,
    compute_content_score,
    compute_question_score,
    compute_session_scores,
)
from app.database import SessionLocal
from app.models import User, InterviewSession
from app.routers.auth import create_access_token
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestScoringModulesPhase52(unittest.TestCase):
    """Test suite for Phase 5.2 scoring modules and configuration."""

    def setUp(self):
        self.db = SessionLocal()
        # Ensure a test user and session exist for REST tests
        self.user = self.db.query(User).filter(User.email == "scoring_test@example.com").first()
        if not self.user:
            self.user = User(
                email="scoring_test@example.com",
                name="Scoring Tester",
                password_hash="testpasshash",
                auth_provider="email",
            )
            self.db.add(self.user)
            self.db.commit()
            self.db.refresh(self.user)

        self.token = create_access_token({"sub": str(self.user.id)})

        from app.models import InterviewConfig
        cfg = self.db.query(InterviewConfig).filter(InterviewConfig.user_id == self.user.id).first()
        if not cfg:
            cfg = InterviewConfig(
                user_id=self.user.id,
                round_type="Technical",
                difficulty="Medium",
                duration_minutes=15,
            )
            self.db.add(cfg)
            self.db.commit()
            self.db.refresh(cfg)

        self.session = (
            self.db.query(InterviewSession)
            .filter(InterviewSession.user_id == self.user.id)
            .first()
        )
        if not self.session:
            self.session = InterviewSession(
                user_id=self.user.id,
                interview_id=cfg.id,
                session_token="test_session_token_123",
                status="CLOSED",
            )
            self.db.add(self.session)
            self.db.commit()
            self.db.refresh(self.session)

    def tearDown(self):
        self.db.close()

    # =========================================================================
    # 1. FACE AND POSTURE SCORER (PURE FUNCTION)
    # =========================================================================

    def test_face_and_posture_strong_composure(self):
        """Tests that high eye contact, centered head pose, and good posture score ~95+."""
        face_signals = {
            "avg_eye_contact": 0.93,
            "avg_head_yaw": 1.2,
            "avg_head_pitch": 0.8,
            "avg_head_roll": 0.5,
            "avg_emotion_valence": 0.20,
            "avg_posture_alignment": 0.94,
            "avg_movement_level": 0.03,
        }
        baseline = {"face_baseline": {"eye_contact": 0.92}}
        res = compute_face_and_posture_score(face_signals, baseline=baseline)

        self.assertGreaterEqual(res["score"], 90.0)
        self.assertLessEqual(res["score"], 100.0)
        self.assertEqual(len(res["deductions"]), 0)
        self.assertIn("eye_contact", res["sub_scores"])
        self.assertIn("head_pose_stability", res["sub_scores"])
        self.assertIn("posture", res["sub_scores"])
        self.assertIn("fidgeting", res["sub_scores"])

    def test_face_and_posture_penalties_explained(self):
        """Tests that low eye contact, turned head pose, and fidgeting incur exact deductions with explanations."""
        face_signals = {
            "avg_eye_contact": 0.45,  # Low eye contact
            "avg_head_yaw": 18.5,     # Turned head
            "avg_head_pitch": -12.0,
            "avg_head_roll": 3.0,
            "avg_emotion_valence": -0.40,  # Negative expression / tension
            "avg_posture_alignment": 0.65, # Slouching
            "avg_movement_level": 0.20,    # Fidgeting
        }
        baseline = {"face_baseline": {"eye_contact": 0.90}}
        res = compute_face_and_posture_score(face_signals, baseline=baseline)

        self.assertLess(res["score"], 60.0)
        self.assertGreater(len(res["deductions"]), 2)

        # Every deduction must have factor, deduction (< 0), and an actionable explanation
        for ded in res["deductions"]:
            self.assertLess(ded["deduction"], 0.0)
            self.assertTrue(len(ded["reason"]) > 10)
            self.assertIn("factor", ded)

    # =========================================================================
    # 2. SPEECH CONFIDENCE SCORER (PURE FUNCTION)
    # =========================================================================

    def test_speech_confidence_optimal_cadence(self):
        """Tests that pace in 120-160 WPM, low fillers, and natural pauses score ~95+."""
        speech_signals = {
            "avg_speech_pace_wpm": 142.0,
            "filler_rate": 0.012,
            "total_fillers": 1,
            "total_pauses": 2,
            "avg_pause_length": 1.1,
            "pitch_variance": 38.0,
            "volume_variability": 24.0,
            "avg_clarity_proxy": 0.92,
        }
        res = compute_speech_confidence_score(speech_signals)

        self.assertGreaterEqual(res["score"], 90.0)
        self.assertEqual(len(res["deductions"]), 0)
        self.assertEqual(res["sub_scores"]["speech_pace"], 25.0)
        self.assertEqual(res["sub_scores"]["filler_rate"], 25.0)

    def test_speech_confidence_slow_pace_and_high_fillers_deductions(self):
        """Tests that slow pace (<120 WPM), high fillers (>2%), and long pauses deduct points with explanations."""
        speech_signals = {
            "avg_speech_pace_wpm": 85.0,   # Slow pace
            "filler_rate": 0.075,          # 7.5% fillers (um, like)
            "total_fillers": 12,
            "total_pauses": 7,
            "avg_pause_length": 3.8,       # Long hesitant pauses
            "pitch_variance": 8.0,         # Monotone
            "volume_variability": 6.0,     # Flat
            "avg_clarity_proxy": 0.65,
        }
        res = compute_speech_confidence_score(speech_signals)

        self.assertLess(res["score"], 50.0)
        ded_factors = [d["factor"] for d in res["deductions"]]
        self.assertIn("speech_pace", ded_factors)
        self.assertIn("filler_rate", ded_factors)
        self.assertIn("pause_pattern", ded_factors)

        # Check explanation cites pace and range
        pace_ded = next(d for d in res["deductions"] if d["factor"] == "speech_pace")
        self.assertIn("too slow", pace_ded["reason"].lower())

    # =========================================================================
    # 3. CONTENT SCORER (RUBRIC) (PURE FUNCTION)
    # =========================================================================

    def test_content_technical_strong_vs_weak(self):
        """Tests technical question scoring: accuracy, depth, keyword coverage, examples."""
        strong_eval = {
            "correctness": 9.5,
            "depth": 9.0,
            "keyword_coverage": {"coverage_ratio": 0.95, "matched": ["redis", "ttl", "atomic", "lock"]},
            "classification": "STRONG",
            "justification": "Candidate clearly explained Redis distributed locking semantics.",
        }
        strong_transcript = "In our project, we achieved 99.99% uptime by using Redis with a Redlock algorithm."

        weak_eval = {
            "correctness": 4.0,
            "depth": 3.0,
            "keyword_coverage": {"coverage_ratio": 0.20, "matched": ["cache"], "missing": ["ttl", "lock", "cluster"]},
            "classification": "WEAK_VAGUE",
            "justification": "Very brief answer with no architectural depth.",
        }
        weak_transcript = "Redis is fast because it is in memory."

        res_strong = compute_content_score(strong_eval, transcript=strong_transcript)
        res_weak = compute_content_score(weak_eval, transcript=weak_transcript)

        self.assertGreaterEqual(res_strong["score"], 88.0)
        self.assertLess(res_weak["score"], 45.0)
        self.assertGreater(res_strong["score"] - res_weak["score"], 40.0)

    def test_content_behavioral_star_structure_completeness(self):
        """Tests that behavioral questions evaluate STAR completeness and penalize missing components."""
        # Complete STAR
        complete_star_eval = {
            "relevance": 9.0,
            "depth": 8.5,
            "star_completeness": {
                "is_behavioral": True,
                "situation": True,
                "task": True,
                "action": True,
                "result": True,
                "star_score": 10.0,
            },
            "keyword_coverage": {"coverage_ratio": 0.85},
            "classification": "STRONG",
        }
        transcript_complete = (
            "At my previous company, our team faced a production outage. "
            "I was tasked with identifying the root cause. "
            "I investigated the database logs and deployed a hotfix. "
            "As a result, we reduced latency by 45% and prevented further downtime."
        )

        # Incomplete STAR (missing Situation and Result)
        incomplete_star_eval = {
            "relevance": 6.5,
            "depth": 6.0,
            "star_completeness": {
                "is_behavioral": True,
                "situation": False,
                "task": True,
                "action": True,
                "result": False,
                "star_score": 5.0,
            },
            "keyword_coverage": {"coverage_ratio": 0.60},
            "classification": "OK",
        }
        transcript_incomplete = "I wrote some code and handled the ticket."

        res_complete = compute_content_score(complete_star_eval, transcript=transcript_complete)
        res_incomplete = compute_content_score(incomplete_star_eval, transcript=transcript_incomplete)

        self.assertGreaterEqual(res_complete["score"], 85.0)
        self.assertLess(res_incomplete["score"], 65.0)

        # Incomplete STAR must have star_structure deduction citing missing Situation and Result
        star_ded = next(d for d in res_incomplete["deductions"] if d["factor"] == "star_structure")
        self.assertIn("Situation", star_ded["reason"])
        self.assertIn("Result", star_ded["reason"])
        self.assertLess(star_ded["deduction"], -10.0)

    # =========================================================================
    # 4. CONFIGURABLE WEIGHTS & THRESHOLDS (CONFIG FILE)
    # =========================================================================

    def test_configurable_weights_and_thresholds(self):
        """Tests that custom configuration alters module weights and thresholds as expected."""
        # Custom config where pace weight is increased to 50%
        custom_cfg = ScoringConfig(
            speech_confidence=SpeechConfidenceConfig(
                weight_pace=0.50,
                weight_fillers=0.10,
                ideal_pace_min_wpm=130.0,
                ideal_pace_max_wpm=150.0,
            )
        )
        speech_sigs = {"avg_speech_pace_wpm": 140.0, "filler_rate": 0.05}

        res_default = compute_speech_confidence_score(speech_sigs, config=DEFAULT_SCORING_CONFIG.speech_confidence)
        res_custom = compute_speech_confidence_score(speech_sigs, config=custom_cfg.speech_confidence)

        self.assertEqual(res_custom["max_sub_scores"]["speech_pace"], 50.0)
        self.assertEqual(res_default["max_sub_scores"]["speech_pace"], 25.0)

    # =========================================================================
    # 5. THREE SAMPLE SESSIONS (STRONG, AVERAGE, WEAK) WITH EXPLANATIONS
    # =========================================================================

    def test_three_sample_sessions_scores_and_explanations(self):
        """
        Validates requirement:
        'Done when: for 3 sample sessions (strong, average, weak) the scores are clearly different
        and every score can be explained.'
        """
        # 1. STRONG SESSION (High eye-contact, crisp pace, deep answers, full STAR)
        strong_session_data = {
            "session_id": 101,
            "calibration": {"face_baseline": {"eye_contact": 0.95}},
            "questions": [
                {
                    "question_id": 1,
                    "topic": "System Design",
                    "type": "technical",
                    "transcript": "In our payment service, we implemented idempotency keys with Redis to prevent duplicate charges, scaling to 10k RPS with 99.99% uptime.",
                    "face_signals": {
                        "avg_eye_contact": 0.94,
                        "avg_head_yaw": 1.5,
                        "avg_head_pitch": 1.0,
                        "avg_head_roll": 0.5,
                        "avg_emotion_valence": 0.25,
                        "avg_posture_alignment": 0.95,
                        "avg_movement_level": 0.03,
                    },
                    "speech_signals": {
                        "avg_speech_pace_wpm": 140.0,
                        "filler_rate": 0.01,
                        "total_fillers": 1,
                        "total_pauses": 2,
                        "avg_pause_length": 1.1,
                        "pitch_variance": 40.0,
                        "volume_variability": 25.0,
                        "avg_clarity_proxy": 0.94,
                    },
                    "evaluator_scores": {
                        "correctness": 9.5,
                        "depth": 9.2,
                        "keyword_coverage": {"coverage_ratio": 0.95, "matched": ["idempotency", "redis", "duplicate"]},
                        "classification": "STRONG",
                    },
                },
                {
                    "question_id": 2,
                    "topic": "Leadership",
                    "type": "behavioral",
                    "transcript": "When our team faced tight release deadlines, I organized daily standups and unblocked the backend engineers. Resulting in a 20% on-time delivery boost.",
                    "face_signals": {
                        "avg_eye_contact": 0.92,
                        "avg_head_yaw": 2.0,
                        "avg_head_pitch": 1.2,
                        "avg_head_roll": 0.8,
                        "avg_emotion_valence": 0.20,
                        "avg_posture_alignment": 0.92,
                        "avg_movement_level": 0.04,
                    },
                    "speech_signals": {
                        "avg_speech_pace_wpm": 145.0,
                        "filler_rate": 0.015,
                        "total_fillers": 1,
                        "total_pauses": 2,
                        "avg_pause_length": 1.2,
                        "pitch_variance": 35.0,
                        "volume_variability": 22.0,
                        "avg_clarity_proxy": 0.90,
                    },
                    "evaluator_scores": {
                        "relevance": 9.0,
                        "depth": 8.8,
                        "star_completeness": {"is_behavioral": True, "situation": True, "task": True, "action": True, "result": True, "star_score": 10.0},
                        "keyword_coverage": {"coverage_ratio": 0.90},
                        "classification": "STRONG",
                    },
                },
            ],
        }

        # 2. AVERAGE SESSION (Moderate eye-contact, acceptable pace with minor fillers, OK answers)
        average_session_data = {
            "session_id": 102,
            "calibration": {"face_baseline": {"eye_contact": 0.90}},
            "questions": [
                {
                    "question_id": 1,
                    "topic": "System Design",
                    "type": "technical",
                    "transcript": "We used Redis for caching to make things faster. Sometimes we cached user sessions.",
                    "face_signals": {
                        "avg_eye_contact": 0.72,
                        "avg_head_yaw": 8.5,
                        "avg_head_pitch": 5.0,
                        "avg_head_roll": 2.5,
                        "avg_emotion_valence": 0.05,
                        "avg_posture_alignment": 0.80,
                        "avg_movement_level": 0.07,
                    },
                    "speech_signals": {
                        "avg_speech_pace_wpm": 112.0,  # Slightly slow
                        "filler_rate": 0.045,          # 4.5% fillers
                        "total_fillers": 4,
                        "total_pauses": 4,
                        "avg_pause_length": 2.2,
                        "pitch_variance": 22.0,
                        "volume_variability": 16.0,
                        "avg_clarity_proxy": 0.80,
                    },
                    "evaluator_scores": {
                        "correctness": 7.0,
                        "depth": 6.2,
                        "keyword_coverage": {"coverage_ratio": 0.60, "matched": ["caching", "redis"], "missing": ["ttl", "eviction"]},
                        "classification": "OK",
                    },
                },
                {
                    "question_id": 2,
                    "topic": "Leadership",
                    "type": "behavioral",
                    "transcript": "I had a disagreement with a team member on PR review. I talked with them and we came to an agreement.",
                    "face_signals": {
                        "avg_eye_contact": 0.70,
                        "avg_head_yaw": 9.0,
                        "avg_head_pitch": 6.0,
                        "avg_head_roll": 3.0,
                        "avg_emotion_valence": 0.0,
                        "avg_posture_alignment": 0.78,
                        "avg_movement_level": 0.08,
                    },
                    "speech_signals": {
                        "avg_speech_pace_wpm": 115.0,
                        "filler_rate": 0.040,
                        "total_fillers": 4,
                        "total_pauses": 3,
                        "avg_pause_length": 2.0,
                        "pitch_variance": 20.0,
                        "volume_variability": 18.0,
                        "avg_clarity_proxy": 0.78,
                    },
                    "evaluator_scores": {
                        "relevance": 7.0,
                        "depth": 6.5,
                        "star_completeness": {"is_behavioral": True, "situation": True, "task": True, "action": True, "result": False, "star_score": 7.5},
                        "keyword_coverage": {"coverage_ratio": 0.65},
                        "classification": "OK",
                    },
                },
            ],
        }

        # 3. WEAK SESSION (Looking away, slow hesitant pace, many fillers, vague answers, no STAR)
        weak_session_data = {
            "session_id": 103,
            "calibration": {"face_baseline": {"eye_contact": 0.90}},
            "questions": [
                {
                    "question_id": 1,
                    "topic": "System Design",
                    "type": "technical",
                    "transcript": "Um, like, basically you put a database and, uh, query it. I don't know much about locking.",
                    "face_signals": {
                        "avg_eye_contact": 0.38,  # Looking down/away
                        "avg_head_yaw": 22.0,
                        "avg_head_pitch": -16.0,
                        "avg_head_roll": 8.0,
                        "avg_emotion_valence": -0.45,
                        "avg_posture_alignment": 0.58,
                        "avg_movement_level": 0.22, # Heavy fidgeting
                    },
                    "speech_signals": {
                        "avg_speech_pace_wpm": 78.0,   # Very slow
                        "filler_rate": 0.095,          # 9.5% fillers
                        "total_fillers": 14,
                        "total_pauses": 8,
                        "avg_pause_length": 4.1,       # Hesitant silences
                        "pitch_variance": 6.0,         # Monotone
                        "volume_variability": 5.0,     # Muffled
                        "avg_clarity_proxy": 0.55,
                    },
                    "evaluator_scores": {
                        "correctness": 3.0,
                        "depth": 2.5,
                        "keyword_coverage": {"coverage_ratio": 0.15, "missing": ["idempotency", "redis", "ttl", "atomic"]},
                        "classification": "WEAK_VAGUE",
                        "justification": "Response did not explain distributed locking or idempotency.",
                    },
                },
                {
                    "question_id": 2,
                    "topic": "Leadership",
                    "type": "behavioral",
                    "transcript": "Uh, yeah, like, sometimes people disagree. It's whatever.",
                    "face_signals": {
                        "avg_eye_contact": 0.35,
                        "avg_head_yaw": 24.0,
                        "avg_head_pitch": -14.0,
                        "avg_head_roll": 7.0,
                        "avg_emotion_valence": -0.40,
                        "avg_posture_alignment": 0.55,
                        "avg_movement_level": 0.24,
                    },
                    "speech_signals": {
                        "avg_speech_pace_wpm": 72.0,
                        "filler_rate": 0.11,
                        "total_fillers": 16,
                        "total_pauses": 7,
                        "avg_pause_length": 4.5,
                        "pitch_variance": 5.0,
                        "volume_variability": 6.0,
                        "avg_clarity_proxy": 0.52,
                    },
                    "evaluator_scores": {
                        "relevance": 3.5,
                        "depth": 2.0,
                        "star_completeness": {"is_behavioral": True, "situation": False, "task": False, "action": True, "result": False, "star_score": 2.5},
                        "keyword_coverage": {"coverage_ratio": 0.20},
                        "classification": "WEAK_VAGUE",
                    },
                },
            ],
        }

        # Run scoring on all three sample sessions
        report_strong = compute_session_scores(strong_session_data)
        report_average = compute_session_scores(average_session_data)
        report_weak = compute_session_scores(weak_session_data)

        # 1. VERIFY SCORES ARE CLEARLY DIFFERENT
        score_strong = report_strong["overall_scores"]["composite_score"]
        score_average = report_average["overall_scores"]["composite_score"]
        score_weak = report_weak["overall_scores"]["composite_score"]

        # Strong should be >= 85
        self.assertGreaterEqual(score_strong, 85.0)
        self.assertEqual(report_strong["classification"], "STRONG")

        # Average should be in 60-75
        self.assertGreaterEqual(score_average, 60.0)
        self.assertLess(score_average, 78.0)
        self.assertEqual(report_average["classification"], "AVERAGE")

        # Weak should be <= 45
        self.assertLessEqual(score_weak, 45.0)
        self.assertEqual(report_weak["classification"], "WEAK")

        # Clear distinct margins between sessions (> 15 points separation)
        self.assertGreater(score_strong - score_average, 15.0)
        self.assertGreater(score_average - score_weak, 20.0)

        # Verify module-by-module separation
        for mod in ["face_posture_score", "speech_confidence_score", "content_score"]:
            s_val = report_strong["overall_scores"][mod]
            a_val = report_average["overall_scores"][mod]
            w_val = report_weak["overall_scores"][mod]
            self.assertGreater(s_val, a_val, f"Strong {mod} ({s_val}) not > Average ({a_val})")
            self.assertGreater(a_val, w_val, f"Average {mod} ({a_val}) not > Weak ({w_val})")

        # 2. VERIFY EVERY SCORE AND DEDUCTION CAN BE EXPLAINED
        # Weak session must have rich explanations citing factors
        self.assertGreater(len(report_weak["top_deductions"]), 3)
        for ded in report_weak["top_deductions"]:
            self.assertIn("factor", ded)
            self.assertIn("deduction", ded)
            self.assertIn("reason", ded)
            self.assertTrue(len(ded["reason"]) > 10, f"Explanation too short: {ded}")
            self.assertLess(ded["deduction"], 0.0)

        # Check areas for improvement contain cited factors and reasons
        self.assertGreater(len(report_weak["areas_for_improvement"]), 2)
        for area in report_weak["areas_for_improvement"]:
            self.assertTrue(len(area) > 15)

    # =========================================================================
    # 6. PURE FUNCTION DETERMINISM & ZERO SIDE EFFECTS
    # =========================================================================

    def test_pure_function_determinism(self):
        """Tests that calling scoring functions with identical input yields strictly identical outputs."""
        sample_input = {
            "session_id": 999,
            "calibration": {"face_baseline": {"eye_contact": 0.90}},
            "questions": [
                {
                    "question_id": 1,
                    "topic": "Databases",
                    "transcript": "PostgreSQL uses MVCC for concurrency control.",
                    "face_signals": {"avg_eye_contact": 0.88, "avg_head_yaw": 2.0},
                    "speech_signals": {"avg_speech_pace_wpm": 135.0, "filler_rate": 0.02},
                    "evaluator_scores": {"correctness": 8.5, "depth": 8.0, "classification": "STRONG"},
                }
            ],
        }

        res_1 = compute_session_scores(sample_input)
        res_2 = compute_session_scores(sample_input)

        self.assertEqual(res_1["overall_scores"], res_2["overall_scores"])
        self.assertEqual(res_1["classification"], res_2["classification"])
        self.assertEqual(len(res_1["per_question_breakdown"]), len(res_2["per_question_breakdown"]))

    # =========================================================================
    # 7. REST ENDPOINT GET /session/{id}/scores
    # =========================================================================

    def test_rest_endpoint_session_scores(self):
        """Tests that GET /session/{id}/scores returns 200 with normalized scores and explanations."""
        resp = client.get(
            f"/session/{self.session.id}/scores",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("overall_scores", data)
        self.assertIn("face_posture_score", data["overall_scores"])
        self.assertIn("speech_confidence_score", data["overall_scores"])
        self.assertIn("content_score", data["overall_scores"])
        self.assertIn("composite_score", data["overall_scores"])
        self.assertIn("classification", data)
        self.assertIn("per_question_breakdown", data)
        self.assertIn("top_deductions", data)
        self.assertIn("key_strengths", data)
        self.assertIn("areas_for_improvement", data)


if __name__ == "__main__":
    unittest.main()
