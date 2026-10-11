"""
Unit & Integration Test Suite for Phase 4.6:
Integrity Monitor (Frontend Events, Video Worker Multi-Face/Missing Face Detection,
First-Time Gentle Warning, Configurable Threshold Flagging, and REST Query Endpoints).
"""

import time
import base64
import asyncio
import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import (
    User,
    UserConsent,
    InterviewConfig,
    InterviewSession,
    SessionCalibration,
    IntegrityEvent,
)
from app.auth import create_access_token, hash_password
from app.services.integrity_monitor import IntegrityMonitor
from app.services.signal_workers import VideoSignalWorker

client = TestClient(app)


class TestIntegrityMonitorPhase4_6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        db = SessionLocal()
        try:
            email = f"integrity_cand_{int(time.time() * 1000)}@test.com"
            self.candidate = User(
                email=email,
                name="Jordan Integrity",
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

    def _create_session(self) -> dict:
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

        # Record calibration baseline
        client.post(
            f"/session/{sess_id}/calibration",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "face_baseline": {
                    "neutral_score": 0.9,
                    "gaze_center": {"x": 0.5, "y": 0.5},
                    "head_pose": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
                },
                "voice_baseline": {
                    "average_volume_db": -22.0,
                    "pitch_range_hz": [110.0, 210.0],
                },
                "background_noise_level_db": -50.0,
                "calibration_text": "Calibration sentence text.",
            },
        )
        return sess_data

    # =========================================================================
    # 1. INTEGRITY MONITOR SERVICE: RECORD EVENTS & DATABASE PERSISTENCE
    # =========================================================================

    def test_integrity_monitor_records_events_and_persists_to_db(self):
        """IntegrityMonitor records events into DB table and computes duration and severity."""
        sess_data = self._create_session()
        sess_id = sess_data["id"]

        monitor = IntegrityMonitor(session_id=sess_id, flag_threshold_count=4)

        async def _run():
            ev1 = await monitor.record_event(
                event_type="tab_switch",
                question_id=1,
                start_time=100.0,
                end_time=102.5,
                details={"hidden": True},
            )
            self.assertEqual(ev1["type"], "tab_switch")
            self.assertEqual(ev1["duration_seconds"], 2.5)
            self.assertEqual(ev1["severity"], "MEDIUM")

            ev2 = await monitor.record_event(
                event_type="clipboard_paste",
                question_id=1,
                start_time=105.0,
                details={"length": 150},
            )
            self.assertEqual(ev2["type"], "clipboard_paste")
            self.assertEqual(ev2["severity"], "HIGH")

        asyncio.run(_run())

        # Verify persisted rows in DB
        db = SessionLocal()
        try:
            db_records = db.query(IntegrityEvent).filter(IntegrityEvent.session_id == sess_id).all()
            self.assertEqual(len(db_records), 2)
            types = {r.type for r in db_records}
            self.assertIn("tab_switch", types)
            self.assertIn("clipboard_paste", types)
        finally:
            db.close()

    # =========================================================================
    # 2. FIRST-TIME GENTLE WARNING EMISSION
    # =========================================================================

    def test_first_time_gentle_warning_emitted_only_once(self):
        """Show a gentle on-screen warning to user the first time; subsequent events do not spam warning."""
        sess_data = self._create_session()
        sess_id = sess_data["id"]

        emitted_warnings = []

        async def _fake_emit(event_type: str, payload: dict):
            if event_type == "integrity_warning":
                emitted_warnings.append(payload)

        monitor = IntegrityMonitor(session_id=sess_id, emit_callback=_fake_emit)

        async def _run():
            # First event -> triggers warning
            await monitor.record_event("tab_switch", question_id=1, start_time=10.0)
            # Second event -> logged, but does not emit a duplicate warning
            await monitor.record_event("window_blur", question_id=1, start_time=12.0)
            # Third event -> logged, no duplicate warning
            await monitor.record_event("fullscreen_exit", question_id=1, start_time=14.0)

        asyncio.run(_run())

        self.assertEqual(len(emitted_warnings), 1)
        self.assertEqual(emitted_warnings[0]["event_type"], "tab_switch")
        self.assertIn("message", emitted_warnings[0])
        self.assertEqual(emitted_warnings[0]["warning_count"], 1)

    # =========================================================================
    # 3. VIDEO WORKER TELEMETRY: SECOND PERSON & FACE MISSING
    # =========================================================================

    def test_video_metrics_detects_second_face_and_missing_face(self):
        """
        Video worker metrics trigger:
        - 'multiple_faces' event when second face is detected.
        - 'face_missing' event when candidate face is absent for > N seconds.
        """
        sess_data = self._create_session()
        sess_id = sess_data["id"]

        monitor = IntegrityMonitor(
            session_id=sess_id,
            face_missing_threshold_seconds=2.0,  # 2 seconds threshold
        )

        async def _run():
            # 1. Multiple faces detected in frame
            metrics_multi = {
                "face_present": 1.0,
                "face_count": 2.0,
                "second_face_detected": 1.0,
            }
            await monitor.on_video_metrics(question_id=1, timestamp=10.0, metrics=metrics_multi)

            # 2. Face missing simulation:
            # At t=20.0, face disappears (face_present=0.0)
            await monitor.on_video_metrics(question_id=1, timestamp=20.0, metrics={"face_present": 0.0})
            # At t=21.0, face still missing (elapsed=1.0s < 2.0s threshold) -> no event yet
            await monitor.on_video_metrics(question_id=1, timestamp=21.0, metrics={"face_present": 0.0})
            # At t=22.5, face still missing (elapsed=2.5s >= 2.0s threshold) -> triggers face_missing
            await monitor.on_video_metrics(question_id=1, timestamp=22.5, metrics={"face_present": 0.0})
            # At t=23.0, candidate returns (face_present=1.0)
            await monitor.on_video_metrics(question_id=1, timestamp=23.0, metrics={"face_present": 1.0})

        asyncio.run(_run())

        summary = monitor.get_integrity_summary()
        self.assertGreaterEqual(summary["total_events"], 2)
        by_type = summary["by_type"]
        self.assertIn("multiple_faces", by_type)
        self.assertIn("face_missing", by_type)

    # =========================================================================
    # 4. CONFIGURABLE THRESHOLD FLAGGING WITHOUT AUTO-TERMINATION
    # =========================================================================

    def test_configurable_threshold_flags_report_without_auto_termination(self):
        """Threshold marks report as flagged when exceeded, but does not terminate the interview."""
        sess_data = self._create_session()
        sess_id = sess_data["id"]

        monitor = IntegrityMonitor(session_id=sess_id, flag_threshold_count=3)

        async def _run():
            # Under threshold: 2 events
            await monitor.record_event("tab_switch", question_id=1, start_time=1.0)
            await monitor.record_event("window_blur", question_id=1, start_time=2.0)
            s_before = monitor.get_integrity_summary()
            self.assertFalse(s_before["is_flagged"])

            # Exceeding threshold: 3rd event
            await monitor.record_event("clipboard_paste", question_id=1, start_time=3.0)
            s_after = monitor.get_integrity_summary()
            self.assertTrue(s_after["is_flagged"])
            self.assertGreater(len(s_after["flag_reasons"]), 0)

        asyncio.run(_run())

    # =========================================================================
    # 5. FULL WEBSOCKET INTEGRITY EVENT FLOW (TAB SWITCH, COPY/PASTE, WARNING)
    # =========================================================================

    def test_websocket_orchestrator_integrity_monitoring(self):
        """
        WebSocket receives frontend integrity events (tab_switch, clipboard_copy),
        emits first-time warning, and responds with integrity_event_ack.
        """
        sess_data = self._create_session()
        sess_id = sess_data["id"]
        sess_token = sess_data["session_token"]

        with client.websocket_connect(f"/session/{sess_id}/live?token={sess_token}") as ws:
            ws.receive_json()  # connected
            ws.receive_json()  # greeting avatar_speak
            ws.receive_json()  # question
            ws.receive_json()  # avatar_speak

            # 1. Send client tab switch event
            ws.send_json({
                "type": "integrity_event",
                "event_type": "tab_switch",
                "question_id": 1,
                "timestamp": time.time(),
                "details": {"hidden": True},
            })

            # Check for first-time gentle warning message
            msg1 = ws.receive_json()
            if msg1.get("type") == "integrity_warning":
                self.assertEqual(msg1["event_type"], "tab_switch")
                ack = ws.receive_json()
                self.assertEqual(ack["type"], "integrity_event_ack")
            else:
                self.assertEqual(msg1["type"], "integrity_event_ack")

            # 2. Send clipboard copy attempt
            ws.send_json({
                "type": "integrity_event",
                "event_type": "clipboard_copy",
                "question_id": 1,
                "timestamp": time.time(),
            })
            ack2 = ws.receive_json()
            self.assertEqual(ack2["type"], "integrity_event_ack")

    # =========================================================================
    # 6. REST QUERY ENDPOINT: GET /session/{id}/integrity-events
    # =========================================================================

    def test_rest_endpoint_returns_logged_integrity_events(self):
        """GET /session/{id}/integrity-events returns logged events and flagging status."""
        sess_data = self._create_session()
        sess_id = sess_data["id"]

        # Seed integrity events into DB
        db = SessionLocal()
        try:
            ev1 = IntegrityEvent(
                session_id=sess_id,
                question_id=1,
                type="tab_switch",
                start_time=100.0,
                end_time=101.0,
                duration_seconds=1.0,
                severity="MEDIUM",
                details={"hidden": True},
            )
            ev2 = IntegrityEvent(
                session_id=sess_id,
                question_id=1,
                type="multiple_faces",
                start_time=105.0,
                end_time=105.0,
                duration_seconds=0.0,
                severity="HIGH",
                details={"face_count": 2},
            )
            ev3 = IntegrityEvent(
                session_id=sess_id,
                question_id=1,
                type="face_missing",
                start_time=110.0,
                end_time=115.0,
                duration_seconds=5.0,
                severity="MEDIUM",
                details={"duration_seconds": 5.0},
            )
            db.add_all([ev1, ev2, ev3])
            db.commit()
        finally:
            db.close()

        resp = client.get(
            f"/session/{sess_id}/integrity-events",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["session_id"], sess_id)
        self.assertEqual(data["total_events"], 3)
        self.assertIn("events", data)
        self.assertIn("by_type", data)
        self.assertEqual(data["by_type"]["tab_switch"], 1)
        self.assertEqual(data["by_type"]["multiple_faces"], 1)
        self.assertEqual(data["by_type"]["face_missing"], 1)
        self.assertTrue(data["is_flagged"])  # threshold reached (3 events)
        self.assertGreater(len(data["flag_reasons"]), 0)

        # Also verify convenience alias /session/{id}/integrity
        alias_resp = client.get(
            f"/session/{sess_id}/integrity",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(alias_resp.status_code, 200)
        self.assertEqual(alias_resp.json()["total_events"], 3)


if __name__ == "__main__":
    unittest.main()
