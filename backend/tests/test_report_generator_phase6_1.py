"""
Unit Tests for Phase 6.1: Grounded Report Generator & Regeneration Loop.
Tests:
1. Report Writer Structure: Overall summary, strengths, gaps, per-question feedback.
2. Grounding Check: Extracts claims, validates against scores & transcripts, attaches references.
3. Grounding Verifier Flags Deliberately Wrong Score Claim.
4. Grounding Verifier Flags Deliberately Wrong Transcript Claim.
5. Flagged-Section Regeneration Path: Recovers grounded content with evidence attached (tested with deliberately wrong claim).
6. Dropping Persistently Unsupported Claims after max 2 rounds.
7. Database Persistence & REST Endpoint: GET /session/{id}/report and POST /session/{id}/generate-report.
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
    SessionReport,
)
from app.services.report_generator_service import (
    generate_initial_report,
    GroundingVerifier,
    generate_grounded_report_with_recovery,
    generate_and_persist_report,
)
from app.routers.auth import create_access_token
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestReportGeneratorPhase61(unittest.TestCase):
    """Test suite for Phase 6.1 report generator and grounding verifier."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        email = f"report_tester_{int(time.time() * 1000)}@example.com"
        self.user = User(
            email=email,
            name="Report Tester",
            password_hash="testpasshash",
            auth_provider="email",
            is_verified=True,
            onboarding_status="completed",
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.token = create_access_token({"sub": str(self.user.id)})

        self.config = InterviewConfig(
            user_id=self.user.id,
            round_type="Technical",
            difficulty="Medium",
            duration_minutes=20,
        )
        self.db.add(self.config)
        self.db.commit()
        self.db.refresh(self.config)

        self.session = InterviewSession(
            user_id=self.user.id,
            interview_id=self.config.id,
            session_token=f"token_rep_{int(time.time() * 1000)}",
            status="CLOSED",
        )
        self.db.add(self.session)
        self.db.commit()
        self.db.refresh(self.session)

        # Seed sample session result
        self.sample_result = {
            "session_id": self.session.id,
            "user_id": self.user.id,
            "overall_score": 78.5,
            "content_score": 82.0,
            "speech_score": 75.0,
            "face_score": 72.0,
            "classification": "AVERAGE",
            "round_type": "Technical",
            "role": "Backend Engineer",
            "weights_used": {"content": 0.60, "speech": 0.25, "face": 0.15},
            "per_question_scores": [
                {
                    "question_id": 1,
                    "topic": "PostgreSQL",
                    "question_text": "Explain MVCC and transaction isolation in PostgreSQL.",
                    "transcript": "PostgreSQL implements multi-version concurrency control using snapshot isolation and row tuple versions.",
                    "fused_score": 84.0,
                    "all_deductions": [
                        {"factor": "keyword_coverage", "deduction": -6.0, "reason": "Did not explain write skew anomalies in repeatable read."}
                    ],
                },
                {
                    "question_id": 2,
                    "topic": "System Design",
                    "question_text": "How would you design a distributed cache?",
                    "transcript": "I would use Redis with consistent hashing across cache nodes.",
                    "fused_score": 73.0,
                    "all_deductions": [
                        {"factor": "speech_pace", "deduction": -8.0, "reason": "Speaking pace was 95 WPM (below ideal range)."}
                    ],
                },
            ],
            "weak_areas": [
                {
                    "topic": "System Design",
                    "average_score": 73.0,
                    "severity": "MEDIUM",
                    "recommendation": "Review consistent hashing virtual nodes and cache stampede mitigations.",
                    "evidence": [{"question_id": 2, "score": 73.0}],
                }
            ],
            "comparisons": {
                "cohort": {
                    "percentile": 72.5,
                    "benchmark_label": "Industry Standard Benchmark (Technical Cohort)",
                },
                "trend": {"summary": "Performance is stable (+1.2 pts across sessions)."},
            },
        }

    def tearDown(self):
        self.db.close()

    # =========================================================================
    # 1. REPORT WRITER STRUCTURE
    # =========================================================================

    def test_report_writer_structure(self):
        """Tests that report writer produces overall summary, strengths, gaps, and per-question feedback."""
        report = generate_initial_report(self.sample_result)

        self.assertIn("overall_summary", report)
        self.assertIn("strengths", report)
        self.assertIn("gaps", report)
        self.assertIn("per_question_feedback", report)

        # Check summary mentions score
        self.assertIn("78.5", report["overall_summary"])
        self.assertIn("Technical", report["overall_summary"])

        # Check strengths and gaps
        self.assertGreater(len(report["strengths"]), 0)
        self.assertGreater(len(report["gaps"]), 0)

        # Check per-question feedback has what_was_good, what_was_missing, and sample_answer_outline
        self.assertEqual(len(report["per_question_feedback"]), 2)
        q1_fb = report["per_question_feedback"][0]
        self.assertIn("what_was_good", q1_fb)
        self.assertIn("what_was_missing", q1_fb)
        self.assertIn("sample_answer_outline", q1_fb)
        self.assertEqual(q1_fb["topic"], "PostgreSQL")

    # =========================================================================
    # 2. GROUNDING VERIFIER (SUPPORTED CLAIMS)
    # =========================================================================

    def test_grounding_verifier_valid_claims(self):
        """Tests that a well-formed report passes grounding check with attached references."""
        ground_truth = {
            "overall_score": 78.5,
            "content_score": 82.0,
            "speech_score": 75.0,
            "face_score": 72.0,
            "classification": "AVERAGE",
            "round_type": "Technical",
            "transcripts": {
                1: "PostgreSQL implements multi-version concurrency control using snapshot isolation and row tuple versions.",
                2: "I would use Redis with consistent hashing across cache nodes.",
            },
            "per_q_scores": {1: 84.0, 2: 73.0},
            "topics": {1: "PostgreSQL", 2: "System Design"},
        }
        report = generate_initial_report(self.sample_result)
        verifier = GroundingVerifier(ground_truth)
        is_grounded, verified, flagged = verifier.verify_report(report)

        self.assertTrue(is_grounded)
        self.assertEqual(len(flagged), 0)
        self.assertGreater(len(verified), 0)

        # Check that strength has reference attached
        self.assertIn("reference", report["strengths"][0])
        self.assertEqual(report["strengths"][0]["reference"]["question_id"], 1)

    # =========================================================================
    # 3. GROUNDING CHECK FLAGS CONTRADICTORY SCORE CLAIM
    # =========================================================================

    def test_grounding_verifier_flags_deliberately_wrong_score_claim(self):
        """Tests that a deliberately wrong score claim is detected and flagged."""
        ground_truth = {
            "overall_score": 45.0,
            "content_score": 48.0,
            "speech_score": 42.0,
            "face_score": 40.0,
            "classification": "WEAK",
            "transcripts": {1: "Simple loop."},
            "per_q_scores": {1: 45.0},
            "topics": {1: "Python"},
        }
        wrong_report = {
            "overall_summary": "Candidate attained an extraordinary overall composite score of 98.0/100, receiving STRONG classification.",
            "strengths": [{"claim": "Achieved 98.0/100.", "question_id": 1}],
            "gaps": [],
            "per_question_feedback": [],
        }

        verifier = GroundingVerifier(ground_truth)
        is_grounded, verified, flagged = verifier.verify_report(wrong_report)

        self.assertFalse(is_grounded)
        self.assertGreater(len(flagged), 0)

        flagged_reasons = " ".join([f["reason"] for f in flagged])
        self.assertIn("contradicts ground truth scores", flagged_reasons)
        self.assertIn("Claims STRONG performance", flagged_reasons)

    # =========================================================================
    # 4. GROUNDING CHECK FLAGS CONTRADICTORY TRANSCRIPT CLAIM
    # =========================================================================

    def test_grounding_verifier_flags_deliberately_wrong_transcript_claim(self):
        """Tests that claiming candidate discussed concepts absent from transcript is flagged."""
        ground_truth = {
            "overall_score": 75.0,
            "content_score": 75.0,
            "speech_score": 75.0,
            "face_score": 75.0,
            "classification": "AVERAGE",
            "transcripts": {
                1: "I wrote a basic Python script using pandas to parse csv files.",
            },
            "per_q_scores": {1: 75.0},
            "topics": {1: "Data Engineering"},
        }

        hallucinated_report = {
            "overall_summary": "Candidate completed interview with 75.0/100 score.",
            "strengths": [
                {
                    "title": "Kubernetes Mastery",
                    "claim": "Demonstrated deep mastery of Kubernetes pod topology and etcd raft clustering protocol.",
                    "question_id": 1,
                }
            ],
            "gaps": [],
            "per_question_feedback": [],
        }

        verifier = GroundingVerifier(ground_truth)
        is_grounded, verified, flagged = verifier.verify_report(hallucinated_report)

        self.assertFalse(is_grounded)
        self.assertGreater(len(flagged), 0)

        flagged_strength = next(f for f in flagged if f["section"] == "strengths")
        self.assertIn("do not appear in transcript", flagged_strength["reason"])

    # =========================================================================
    # 5. REGENERATION PATH RECOVERS GROUNDED CONTENT (TESTED WITH WRONG CLAIM)
    # =========================================================================

    def test_regeneration_path_recovers_grounded_content_with_evidence(self):
        """
        Validates core requirement:
        'Done when: reports contain no statements that contradict the transcript or scores,
        and the flagged-section regeneration path works (test it with a deliberately wrong claim).'
        """
        deliberate_wrong_claim = "Demonstrated deep mastery of Kubernetes pod topology and etcd raft clustering protocol."

        # Run full 3-pass pipeline with deliberately injected wrong claim
        final_report = generate_grounded_report_with_recovery(
            session_result=self.sample_result,
            max_rounds=2,
            deliberate_wrong_claim_section="strengths",
            deliberate_wrong_claim_text=deliberate_wrong_claim,
        )

        audit = final_report.get("grounding_audit", {})

        # 1. Flagged initially
        self.assertGreaterEqual(audit["initial_flagged_claims"], 1)

        # 2. Regeneration rounds performed
        self.assertGreaterEqual(audit["regeneration_rounds_performed"], 1)

        # 3. Final report is fully grounded
        self.assertTrue(audit["is_fully_grounded"])
        self.assertEqual(audit["unsupported_remaining"], 0)

        # 4. Verified that the hallucinated claim does NOT appear in final report
        all_strength_claims = " ".join([s.get("claim", "") for s in final_report["strengths"]])
        self.assertNotIn("Kubernetes", all_strength_claims)
        self.assertNotIn("etcd", all_strength_claims)

        # 5. Verified that legitimate strengths remain
        self.assertGreater(len(final_report["strengths"]), 0)

    # =========================================================================
    # 6. DROPPING PERSISTENTLY UNSUPPORTED CLAIMS AFTER MAX ROUNDS
    # =========================================================================

    def test_regeneration_drops_persistently_unsupported_claims_after_max_rounds(self):
        """Tests that if an unsupported claim persists across 2 rounds, it is dropped from the published report."""
        deliberate_wrong_summary = "Candidate attained an extraordinary overall composite score of 99.0/100, receiving STRONG classification."

        final_report = generate_grounded_report_with_recovery(
            session_result=self.sample_result,
            max_rounds=2,
            deliberate_wrong_claim_section="overall_summary",
            deliberate_wrong_claim_text=deliberate_wrong_summary,
        )

        audit = final_report.get("grounding_audit", {})
        self.assertTrue(audit["is_fully_grounded"])
        self.assertNotIn("99.0", final_report["overall_summary"])
        self.assertIn(str(round(self.sample_result["overall_score"], 1)), final_report["overall_summary"])

    # =========================================================================
    # 7. DATABASE PERSISTENCE & REST ENDPOINTS
    # =========================================================================

    def test_database_persistence_and_rest_endpoints(self):
        """Tests generate_and_persist_report, SessionReport table persistence, and GET /session/{id}/report."""
        # 1. Generate and persist
        res = generate_and_persist_report(session_id=self.session.id, db=self.db)

        self.assertEqual(res["session_id"], self.session.id)
        self.assertTrue(res["is_grounded"])
        self.assertIn("report", res)
        self.assertIn("grounding_audit", res)

        # Verify DB row exists in SessionReport
        db_rep = self.db.query(SessionReport).filter(SessionReport.session_id == self.session.id).first()
        self.assertIsNotNone(db_rep)
        self.assertTrue(db_rep.is_grounded)
        self.assertIn("overall_summary", db_rep.report_data)

        # 2. Test GET /session/{id}/report
        resp = client.get(
            f"/session/{self.session.id}/report",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["session_id"], self.session.id)
        self.assertTrue(data["is_grounded"])
        self.assertIn("report", data)
        self.assertIn("overall_summary", data["report"])
        self.assertIn("strengths", data["report"])
        self.assertIn("gaps", data["report"])
        self.assertIn("per_question_feedback", data["report"])

        # 3. Test POST /session/{id}/generate-report
        resp_post = client.post(
            f"/session/{self.session.id}/generate-report",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp_post.status_code, 200)
        self.assertEqual(resp_post.json()["session_id"], self.session.id)


if __name__ == "__main__":
    unittest.main()
