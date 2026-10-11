import sys
import os
import unittest
import json
from datetime import datetime, timezone
from fastapi.testclient import TestClient

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.database import SessionLocal, Base, engine
from app.models import (
    User,
    InterviewConfig,
    UserConsent,
    InterviewSession,
    SessionCalibration,
)
from app.auth import hash_password, create_access_token

Base.metadata.create_all(bind=engine)
client = TestClient(app)

TEST_USER_A = "preinterview_candidate_a@example.com"
TEST_USER_B = "preinterview_candidate_b@example.com"
TEST_PASSWORD = "Password123!"


class TestPreinterviewPhase3_1(unittest.TestCase):

    def setUp(self):
        self._cleanup()
        self.user_a_id, self.token_a = self._create_user(TEST_USER_A)
        self.user_b_id, self.token_b = self._create_user(TEST_USER_B)

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        db = SessionLocal()
        try:
            for email in [TEST_USER_A, TEST_USER_B]:
                user = db.query(User).filter(User.email == email).first()
                if user:
                    sessions = db.query(InterviewSession).filter(InterviewSession.user_id == user.id).all()
                    for s in sessions:
                        db.query(SessionCalibration).filter(SessionCalibration.session_id == s.id).delete()
                    db.query(InterviewSession).filter(InterviewSession.user_id == user.id).delete()
                    db.query(UserConsent).filter(UserConsent.user_id == user.id).delete()
                    db.query(InterviewConfig).filter(InterviewConfig.user_id == user.id).delete()
                    db.delete(user)
            db.commit()
        finally:
            db.close()

    def _create_user(self, email: str):
        db = SessionLocal()
        try:
            user = User(
                name="Preinterview Candidate",
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

    # =========================================================================
    # 1. CONSENT TESTS
    # =========================================================================

    def test_record_and_get_consent(self):
        """
        Tests storing and querying Candidate Consent with configurable retention days
        and deletion rights. Rejects unaccepted consent requests.
        """
        # 1. Attempt unaccepted consent -> 400
        bad_resp = client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"version": "v1.0", "accepted": False},
        )
        self.assertEqual(bad_resp.status_code, 400)

        # 2. Accept consent -> 201
        res = client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"version": "v1.0", "accepted": True},
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["user_id"], self.user_a_id)
        self.assertEqual(data["version"], "v1.0")
        self.assertEqual(data["retention_days"], 30)
        self.assertTrue(data["accepted"])
        self.assertTrue(data["can_delete"])

        # 3. GET /session/consent -> 200
        get_res = client.get(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["id"], data["id"])

    # =========================================================================
    # 2. SESSION CREATION & CONSENT GATE
    # =========================================================================

    def test_session_creation_blocks_without_consent(self):
        """
        Creating an interview session MUST be blocked (HTTP 403) if the candidate
        has not explicitly accepted consent.
        """
        resp = client.post(
            "/session",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Consent is required", resp.json()["detail"])

    def test_session_creation_succeeds_with_consent(self):
        """
        Once consent is recorded, POST /session creates the session, returns session ID,
        WebSocket URL, and unique session token.
        """
        # Step 1: Record consent
        client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"version": "v1.0", "accepted": True},
        )

        # Step 2: Create config
        cfg_resp = client.post(
            "/interview/config",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"round_type": "Technical", "difficulty": "Medium", "duration_minutes": 30, "mode": "normal"},
        )
        cfg_id = cfg_resp.json()["id"]

        # Step 3: Create session
        sess_resp = client.post(
            "/session",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"interview_id": cfg_id},
        )
        self.assertEqual(sess_resp.status_code, 201)
        s_data = sess_resp.json()

        self.assertEqual(s_data["user_id"], self.user_a_id)
        self.assertEqual(s_data["interview_id"], cfg_id)
        self.assertEqual(s_data["status"], "created")
        self.assertTrue(len(s_data["session_token"]) > 20)
        self.assertIn(f"/session/{s_data['id']}/stream?token={s_data['session_token']}", s_data["ws_url"])

        # Step 4: GET /session/{id}
        get_sess = client.get(
            f"/session/{s_data['id']}",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(get_sess.status_code, 200)
        self.assertEqual(get_sess.json()["id"], s_data["id"])

    # =========================================================================
    # 3. NETWORK DIAGNOSTICS (Ping & Speed Test)
    # =========================================================================

    def test_network_ping_and_speed_test(self):
        """
        Verifies lightweight ping for round-trip latency measurement and
        speed test calculation in Mbps.
        """
        # 1. Ping
        ping_resp = client.get("/session/ping?client_ts=1700000000.123")
        self.assertEqual(ping_resp.status_code, 200)
        p_data = ping_resp.json()
        self.assertEqual(p_data["status"], "ok")
        self.assertEqual(p_data["client_timestamp"], 1700000000.123)
        self.assertIn("server_time", p_data)

        # 2. Upload Speed Test
        sample_payload = b"X" * 102400  # 100 KB
        speed_resp = client.post(
            "/session/speed-test",
            content=sample_payload,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(speed_resp.status_code, 200)
        sp_data = speed_resp.json()
        self.assertEqual(sp_data["bytes_received"], 102400)
        self.assertGreater(sp_data["duration_ms"], 0)
        self.assertGreater(sp_data["upload_mbps"], 0)

    # =========================================================================
    # 4. CALIBRATION (Face, Voice, Background Noise)
    # =========================================================================

    def test_session_calibration_lifecycle(self):
        """
        Verifies storing and retrieving 30-second baseline metrics for face, voice level,
        and background noise floor.
        """
        # Step 1: Consent & Session
        client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"version": "v1.0", "accepted": True},
        )
        sess_resp = client.post(
            "/session",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={},
        )
        session_id = sess_resp.json()["id"]

        # Step 2: POST /session/{id}/calibration
        cal_payload = {
            "face_baseline": {
                "neutral_score": 0.96,
                "gaze_center": {"x": 0.50, "y": 0.49},
                "head_pose": {"pitch": 1.2, "yaw": -0.8, "roll": 0.3},
            },
            "voice_baseline": {
                "average_volume_db": -22.4,
                "pitch_range_hz": [115.0, 218.0],
                "speaking_rate_wpm": 138.0,
            },
            "background_noise_level_db": -48.5,
            "calibration_text": "I am ready to begin my interview with IntervAI.",
        }

        cal_resp = client.post(
            f"/session/{session_id}/calibration",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json=cal_payload,
        )
        self.assertEqual(cal_resp.status_code, 201)
        c_data = cal_resp.json()
        self.assertEqual(c_data["session_id"], session_id)
        self.assertEqual(c_data["face_baseline"]["neutral_score"], 0.96)
        self.assertEqual(c_data["voice_baseline"]["average_volume_db"], -22.4)
        self.assertEqual(c_data["background_noise_level_db"], -48.5)

        # Verify session status is updated to "calibrated"
        sess_get = client.get(
            f"/session/{session_id}",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(sess_get.json()["status"], "calibrated")

        # Step 3: GET /session/{id}/calibration
        get_cal = client.get(
            f"/session/{session_id}/calibration",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(get_cal.status_code, 200)
        self.assertEqual(get_cal.json()["id"], c_data["id"])

    # =========================================================================
    # 5. WEBSOCKET STREAMING (Tokens, Ping/Pong, Media Chunks)
    # =========================================================================

    def test_websocket_streaming_and_media_chunks(self):
        """
        Tests WebSocket handshake with authentication token, ping/pong,
        and media chunk reception and acknowledgments.
        """
        # Step 1: Consent & Session
        client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"version": "v1.0", "accepted": True},
        )
        sess_resp = client.post(
            "/session",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={},
        )
        s_data = sess_resp.json()
        session_id = s_data["id"]
        valid_token = s_data["session_token"]

        # Step 2: Connect with invalid token -> rejected
        with self.assertRaises(Exception):
            with client.websocket_connect(f"/session/{session_id}/stream?token=invalid_token"):
                pass

        # Step 3: Connect with valid token
        with client.websocket_connect(f"/session/{session_id}/stream?token={valid_token}") as ws:
            # 1. Handshake greeting
            greeting = ws.receive_json()
            self.assertEqual(greeting["type"], "connected")
            self.assertEqual(greeting["session_id"], session_id)
            self.assertEqual(greeting["status"], "active")

            # 2. Ping / Pong
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            self.assertEqual(pong["type"], "pong")

            # 3. Text Media Chunk (Base64)
            ws.send_json({
                "type": "media_chunk",
                "chunk_id": 1,
                "data": "aGVsbG8td29ybGQtdmlkZW8tY2h1bms=",
                "mime_type": "video/webm",
            })
            chunk_ack = ws.receive_json()
            self.assertEqual(chunk_ack["type"], "chunk_ack")
            self.assertEqual(chunk_ack["chunk_id"], 1)

            # 4. Binary Media Chunk
            ws.send_bytes(b"\x00\x01\x02\x03\x04\x05")
            bin_ack = ws.receive_json()
            self.assertEqual(bin_ack["type"], "binary_chunk_ack")
            self.assertEqual(bin_ack["size"], 6)

    # =========================================================================
    # 6. USER ISOLATION
    # =========================================================================

    def test_candidate_isolation(self):
        """
        Candidate B cannot access or modify Candidate A's session or calibration.
        """
        # Candidate A creates session
        client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"version": "v1.0", "accepted": True},
        )
        s_resp = client.post(
            "/session",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={},
        )
        sess_id = s_resp.json()["id"]

        # Candidate B attempts access -> 404
        b_get = client.get(
            f"/session/{sess_id}",
            headers={"Authorization": f"Bearer {self.token_b}"},
        )
        self.assertEqual(b_get.status_code, 404)

        b_cal = client.post(
            f"/session/{sess_id}/calibration",
            headers={"Authorization": f"Bearer {self.token_b}"},
            json={"face_baseline": {}},
        )
        self.assertEqual(b_cal.status_code, 404)


if __name__ == "__main__":
    unittest.main()
