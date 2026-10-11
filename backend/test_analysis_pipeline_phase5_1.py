"""
Unit & Integration Test Suite for Phase 5.1:
Session Close, Recording Finalization, Idempotent Analysis Job Queue with Retry/Backoff,
Per-Question Dataset Alignment Engine, and Partial Failure Resilience.
"""

import os
import time
import json
import base64
import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import (
    User,
    InterviewConfig,
    InterviewSession,
    SessionCalibration,
    SignalTimeSeries,
    IntegrityEvent,
    SessionAnalysisJob,
)
from app.auth import create_access_token, hash_password
from app.services.answer_capture_service import default_storage_manager
from app.services.analysis_pipeline import (
    AlignmentEngine,
    AnalysisJobManager,
    default_analysis_manager,
    default_alignment_engine,
)
from app.services.session_state import default_state_store, SessionStateData, SessionState

client = TestClient(app)


class TestAnalysisPipelinePhase5_1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        with engine.connect() as conn:
            from sqlalchemy import text
            for col in ["audio_file_key", "video_file_key", "aligned_data_key"]:
                try:
                    conn.execute(text(f"ALTER TABLE interview_sessions ADD COLUMN {col} VARCHAR(500);"))
                    conn.commit()
                except Exception:
                    pass

    def setUp(self):
        db = SessionLocal()
        try:
            email = f"analysis_cand_{int(time.time() * 1000)}@test.com"
            self.candidate = User(
                email=email,
                name="Alex Analysis",
                password_hash=hash_password("Secret123!"),
                auth_provider="email",
                is_verified=True,
                onboarding_status="completed",
            )
            db.add(self.candidate)
            db.commit()
            db.refresh(self.candidate)
            self.candidate_id = self.candidate.id
            self.token = create_access_token(data={"sub": str(self.candidate.id), "email": self.candidate.email})
        finally:
            db.close()

        # Consent record
        client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"version": "v1.0", "accepted": True},
        )

    def _create_session_with_telemetry(self) -> dict:
        """Creates session, seeds calibration, artifacts, signals, and integrity events."""
        cfg_resp = client.post(
            "/interview/config",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"round_type": "Technical", "difficulty": "Medium", "duration_minutes": 15, "mode": "normal"},
        )
        self.assertEqual(cfg_resp.status_code, 201)
        cfg_id = cfg_resp.json()["id"]

        sess_resp = client.post(
            "/session",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"interview_id": cfg_id},
        )
        self.assertEqual(sess_resp.status_code, 201)
        sess_data = sess_resp.json()
        sess_id = sess_data["id"]

        # Calibration
        client.post(
            f"/session/{sess_id}/calibration",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "face_baseline": {"gaze_center": {"x": 0.5, "y": 0.5}, "head_pose": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}},
                "voice_baseline": {"average_volume_db": -22.0, "pitch_range_hz": [110.0, 210.0]},
                "background_noise_level_db": -50.0,
            },
        )

        # Seed recording artifacts in storage
        default_storage_manager.save_audio_chunk(sess_id, 1, 1, b"\x01\x02" * 160)
        default_storage_manager.save_audio_chunk(sess_id, 1, 2, b"\x03\x04" * 160)
        dummy_jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0JFIF").decode()
        default_storage_manager.save_video_frame(sess_id, 1, 1, dummy_jpeg)

        # Seed transcript with word timings
        default_storage_manager.save_transcript(sess_id, 1, {
            "text": "I implemented distributed caching using Redis and write-through cache pattern.",
            "words": [
                {"word": "I", "start": 0.1, "end": 0.3},
                {"word": "implemented", "start": 0.3, "end": 0.9},
                {"word": "distributed", "start": 0.9, "end": 1.5},
                {"word": "caching", "start": 1.5, "end": 2.0},
            ],
        })

        # Seed database signals and integrity events
        db = SessionLocal()
        try:
            now = time.time()
            sig1 = SignalTimeSeries(session_id=sess_id, question_id=1, timestamp=now, metric="eye_contact", value=0.94)
            sig2 = SignalTimeSeries(session_id=sess_id, question_id=1, timestamp=now + 1, metric="head_yaw", value=1.2)
            sig3 = SignalTimeSeries(session_id=sess_id, question_id=1, timestamp=now, metric="speech_pace_wpm", value=142.0)
            sig4 = SignalTimeSeries(session_id=sess_id, question_id=1, timestamp=now + 1, metric="filler_count", value=1.0)
            db.add_all([sig1, sig2, sig3, sig4])

            integ = IntegrityEvent(
                session_id=sess_id,
                question_id=1,
                type="tab_switch",
                start_time=now + 0.5,
                end_time=now + 1.5,
                duration_seconds=1.0,
                severity="MEDIUM",
                details={"hidden": True},
            )
            db.add(integ)
            db.commit()
        finally:
            db.close()

        # Seed Redis session state context
        saved_state = SessionStateData(
            session_id=sess_id,
            user_id=self.candidate_id,
            interview_id=cfg_id,
            state=SessionState.CLOSING,
            session_context=[
                {
                    "question_id": 1,
                    "question_text": "Explain distributed caching strategies and consistency models.",
                    "topic": "System Design",
                    "subtopic": "Caching",
                    "difficulty": "Medium",
                    "score": 8.5,
                    "evaluation": {
                        "relevance": 9.0,
                        "correctness": 8.5,
                        "depth": 8.0,
                        "overall_score": 8.5,
                        "classification": "STRONG",
                        "keyword_coverage": {"matched": ["distributed", "caching", "redis"], "missing": []},
                    },
                }
            ],
        )
        default_state_store.save_state(saved_state)

        return sess_data

    # =========================================================================
    # 1. SESSION CLOSE & RECORDING FINALIZATION
    # =========================================================================

    def test_session_close_and_finalize_recordings(self):
        """Finalizes recordings, updates status to CLOSED, and stores file keys."""
        sess_data = self._create_session_with_telemetry()
        sess_id = sess_data["id"]

        manager = AnalysisJobManager()
        rec_meta = manager.close_and_finalize_session(sess_id)

        self.assertEqual(rec_meta["session_id"], sess_id)
        self.assertIn("audio_file_key", rec_meta)
        self.assertIn("video_file_key", rec_meta)
        self.assertTrue(os.path.exists(rec_meta["audio_merged_path"]))
        self.assertTrue(os.path.exists(rec_meta["video_manifest_path"]))
        self.assertGreater(rec_meta["total_audio_bytes"], 0)
        self.assertGreater(rec_meta["total_video_frames"], 0)

        # Check Database updates
        db = SessionLocal()
        try:
            sess = db.query(InterviewSession).filter(InterviewSession.id == sess_id).first()
            self.assertEqual(sess.status, "CLOSED")
            self.assertIsNotNone(sess.ended_at)
            self.assertEqual(sess.audio_file_key, rec_meta["audio_file_key"])
            self.assertEqual(sess.video_file_key, rec_meta["video_file_key"])
        finally:
            db.close()

    # =========================================================================
    # 2. ALIGNMENT ENGINE: UNIFIED PER-QUESTION DATASET
    # =========================================================================

    def test_alignment_engine_produces_complete_dataset(self):
        """AlignmentEngine correlates transcript, timings, signals, integrity, and evaluator scores."""
        sess_data = self._create_session_with_telemetry()
        sess_id = sess_data["id"]

        engine_inst = AlignmentEngine()
        aligned = engine_inst.align_session(sess_id)

        self.assertEqual(aligned["session_id"], sess_id)
        self.assertFalse(aligned["is_partial"])
        self.assertEqual(len(aligned["missing_sections"]), 0)
        self.assertIn("questions", aligned)
        self.assertGreaterEqual(len(aligned["questions"]), 1)

        q1 = aligned["questions"][0]
        self.assertEqual(q1["question_id"], 1)
        self.assertIn("distributed caching", q1["transcript"])
        self.assertGreater(len(q1["word_timings"]), 0)

        # Face signals aligned
        self.assertIn("avg_eye_contact", q1["face_signals"])
        self.assertGreater(q1["face_signals"]["avg_eye_contact"], 0.8)

        # Speech signals aligned
        self.assertIn("avg_speech_pace_wpm", q1["speech_signals"])
        self.assertGreater(q1["speech_signals"]["avg_speech_pace_wpm"], 100.0)

        # Integrity events aligned
        self.assertEqual(len(q1["integrity_events"]), 1)
        self.assertEqual(q1["integrity_events"][0]["type"], "tab_switch")

        # Evaluator scores aligned
        self.assertEqual(q1["evaluator_scores"]["classification"], "STRONG")
        self.assertEqual(q1["evaluator_scores"]["overall_score"], 8.5)

        # Artifact exists on disk
        self.assertTrue(os.path.exists(aligned["file_path"]))

    # =========================================================================
    # 3. QUEUE IDEMPOTENCY
    # =========================================================================

    def test_analysis_queue_idempotency(self):
        """Duplicate job submissions for same session return existing job without duplication."""
        sess_data = self._create_session_with_telemetry()
        sess_id = sess_data["id"]

        manager = AnalysisJobManager()
        # First enqueue (synchronous)
        job1 = manager.enqueue_analysis_job(sess_id, sync=True)
        self.assertIn(job1["status"], ("completed", "partial"))
        first_job_id = job1["job_id"]

        # Second enqueue -> must return existing job
        job2 = manager.enqueue_analysis_job(sess_id, sync=False)
        self.assertEqual(job2["job_id"], first_job_id)
        self.assertEqual(job2["status"], job1["status"])

    # =========================================================================
    # 4. TRANSIENT FAILURE RETRY WITH EXPONENTIAL BACKOFF
    # =========================================================================

    def test_pipeline_retry_with_backoff_on_transient_error(self):
        """Transient error in sub-step triggers retry with backoff and finishes successfully."""
        sess_data = self._create_session_with_telemetry()
        sess_id = sess_data["id"]

        manager = AnalysisJobManager()
        job_id = f"job_retry_test_{sess_id}"

        # Simulate transient error on first attempt of finalize
        result = manager.run_analysis_pipeline_sync(
            session_id=sess_id,
            job_id=job_id,
            max_retries=2,
            simulate_failure_step="finalize",
        )

        self.assertIn(result["status"], ("completed", "partial"))
        self.assertEqual(result["progress"], 100)

    # =========================================================================
    # 5. RESILIENT PARTIAL FAILURE HANDLING
    # =========================================================================

    def test_partial_failure_continues_and_flags_missing_sections(self):
        """If one component (e.g. transcript or signals) fails, marks partial and records manifest."""
        sess_data = self._create_session_with_telemetry()
        sess_id = sess_data["id"]

        # Delete transcript file to simulate missing transcript section
        t_path = os.path.join(default_storage_manager.base_dir, str(sess_id), "1", "transcript.json")
        if os.path.exists(t_path):
            os.remove(t_path)

        # Clear session_context text to force missing transcript
        saved_state = default_state_store.load_state(sess_id)
        if saved_state and saved_state.session_context:
            saved_state.session_context[0]["answer"] = None
            default_state_store.save_state(saved_state)

        engine_inst = AlignmentEngine()
        aligned = engine_inst.align_session(sess_id)

        # Must mark as partial and flag missing section
        self.assertTrue(aligned["is_partial"])
        self.assertIn("transcript", aligned["missing_sections"])

        # Remaining sections must still be present and intact!
        q1 = aligned["questions"][0]
        self.assertTrue(q1["is_partial"])
        self.assertIn("transcript", q1["missing_sections"])
        self.assertIn("avg_eye_contact", q1["face_signals"])
        self.assertEqual(len(q1["integrity_events"]), 1)
        self.assertEqual(q1["evaluator_scores"]["classification"], "STRONG")

    # =========================================================================
    # 6. REST ENDPOINTS: POST /finalize AND GET /analysis-status
    # =========================================================================

    def test_rest_endpoints_finalize_and_poll_status(self):
        """POST /session/{id}/finalize and GET /session/{id}/analysis-status flow."""
        sess_data = self._create_session_with_telemetry()
        sess_id = sess_data["id"]

        # 1. Trigger finalize & analysis
        fin_resp = client.post(
            f"/session/{sess_id}/finalize?sync=true",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(fin_resp.status_code, 200)
        data = fin_resp.json()
        self.assertEqual(data["session_id"], sess_id)
        self.assertIn("job", data)

        # 2. Poll analysis status
        status_resp = client.get(
            f"/session/{sess_id}/analysis-status",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(status_resp.status_code, 200)
        s_data = status_resp.json()
        self.assertEqual(s_data["session_id"], sess_id)
        self.assertIn(s_data["status"], ("completed", "partial"))
        self.assertEqual(s_data["progress"], 100)

        # 3. Retrieve aligned dataset
        aligned_resp = client.get(
            f"/session/{sess_id}/aligned-data",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(aligned_resp.status_code, 200)
        al_data = aligned_resp.json()
        self.assertEqual(al_data["session_id"], sess_id)
        self.assertIn("questions", al_data)


if __name__ == "__main__":
    unittest.main()
