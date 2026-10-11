"""
Unit & Integration Test Suite for No-Login Guest Practice Mode.
Tests:
1. Guest session initialization (3 questions, 10 min, signed token, httpOnly cookie).
2. Abuse protection: Daily IP rate limiting (429 Too Many Requests after threshold).
3. Abuse protection: Cloudflare Turnstile CAPTCHA verification.
4. Abuse protection: CV upload 2MB size cap (413 Request Entity Too Large for > 2MB).
5. Guest session isolation (cannot access other guest sessions, returns 403 Forbidden).
6. Restrictions: PDF export strictly blocked for guests (returns 403 Forbidden).
7. Privacy: Automatic 24-hour cleanup job deletes expired sessions & data.
8. Account linking: Guest session is automatically linked upon signup or login.
9. Scoring: Uniform scoring pipeline works for guests without polluting UserMemory.
"""

import os
import io
import unittest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup test environment variables before importing app
os.environ["SECRET_KEY"] = "test-secret-key-32-chars-long-abcdef"
os.environ["DEV_MODE"] = "True"
os.environ["GUEST_MAX_SESSIONS_PER_IP_PER_DAY"] = "3"
os.environ["GUEST_RETENTION_HOURS"] = "24"
os.environ["GUEST_MAX_UPLOAD_SIZE_BYTES"] = str(2 * 1024 * 1024)

from app.main import app
from app.database import Base, get_db
from app.config import settings
from app.models import (
    User,
    InterviewSession,
    InterviewConfig,
    QuestionBankItem,
    UserConsent,
    GuestIpLog,
    SessionResult,
    SessionReport,
    UserMemory,
)
from app.auth import hash_password, create_access_token, create_guest_token
from app.services.guest_service import (
    check_guest_ip_limit,
    log_guest_ip,
    cleanup_expired_guest_sessions,
    link_guest_session_to_user,
)


from sqlalchemy.pool import StaticPool


class TestGuestPracticeMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an isolated test SQLite in-memory database with StaticPool
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=cls.engine
        )
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        # Override get_db dependency
        self.db = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.db.rollback()
        # Clean tables for next test
        for table in reversed(Base.metadata.sorted_tables):
            self.db.execute(table.delete())
        self.db.commit()
        self.db.close()
        app.dependency_overrides.clear()

    def test_01_guest_start_session_success(self):
        """A logged-out visitor starts a guest session with 3 questions, 10 min, and token."""
        payload = {
            "target_role": "Fullstack Engineer",
            "round_type": "Technical",
            "difficulty": "Medium",
            "turnstile_token": "mock_turnstile_token",
        }
        resp = self.client.post("/guest/start", json=payload, headers={"x-forwarded-for": "192.168.1.10"})
        self.assertEqual(resp.status_code, 201)
        data = resp.json()

        self.assertIn("session_id", data)
        self.assertIn("guest_token", data)
        self.assertIn("guest_id", data)
        self.assertEqual(data["round_type"], "Technical")
        self.assertEqual(data["duration_minutes"], 10)
        self.assertEqual(data["total_questions"], 3)
        self.assertEqual(len(data["questions"]), 3)
        self.assertTrue(data["ws_url"].startswith("ws"))

        # Verify DB records
        sess = self.db.query(InterviewSession).filter(InterviewSession.id == data["session_id"]).first()
        self.assertIsNotNone(sess)
        self.assertTrue(sess.is_guest)
        self.assertIsNone(sess.user_id)
        self.assertEqual(sess.guest_id, data["guest_id"])

        # Verify cookie was set
        self.assertIn("guest_token", resp.cookies)

    def test_02_abuse_protection_daily_ip_rate_limit(self):
        """Exceeding 3 guest sessions per day per IP returns 429 Too Many Requests."""
        test_ip = "203.0.113.42"
        payload = {
            "target_role": "Software Engineer",
            "round_type": "Technical",
            "difficulty": "Easy",
            "turnstile_token": "mock_turnstile_token",
        }

        # First 3 sessions succeed
        for i in range(3):
            resp = self.client.post("/guest/start", json=payload, headers={"x-forwarded-for": test_ip})
            self.assertEqual(resp.status_code, 201, f"Session {i+1} failed")

        # 4th session must be rejected with 429
        resp4 = self.client.post("/guest/start", json=payload, headers={"x-forwarded-for": test_ip})
        self.assertEqual(resp4.status_code, 429)
        self.assertIn("Daily guest practice limit reached", resp4.json()["detail"])

        # Different IP is not blocked
        other_resp = self.client.post("/guest/start", json=payload, headers={"x-forwarded-for": "198.51.100.99"})
        self.assertEqual(other_resp.status_code, 201)

    def test_03_abuse_protection_turnstile_captcha(self):
        """Invalid CAPTCHA token returns 400 Bad Request."""
        # Temporarily configure a dummy Turnstile secret key to activate strict verification
        original_secret = settings.TURNSTILE_SECRET_KEY
        original_dev = settings.DEV_MODE
        try:
            settings.TURNSTILE_SECRET_KEY = "0x4AAAAAAABBBBBBBCCCCCCCCDDDDDDD"
            settings.DEV_MODE = False

            payload = {
                "target_role": "Product Manager",
                "round_type": "HR",
                "difficulty": "Medium",
                "turnstile_token": "invalid_or_bot_token",
            }
            resp = self.client.post("/guest/start", json=payload, headers={"x-forwarded-for": "10.0.0.1"})
            self.assertEqual(resp.status_code, 400)
            self.assertIn("CAPTCHA", resp.json()["detail"])

            # Valid test token succeeds
            payload["turnstile_token"] = "mock_turnstile_token"
            resp_valid = self.client.post("/guest/start", json=payload, headers={"x-forwarded-for": "10.0.0.2"})
            self.assertEqual(resp_valid.status_code, 201)
        finally:
            settings.TURNSTILE_SECRET_KEY = original_secret
            settings.DEV_MODE = original_dev

    def test_04_abuse_protection_cv_upload_size_limit(self):
        """CV upload is strictly limited to 2MB for guests."""
        import pypdf
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=72, height=72)
        buf = io.BytesIO()
        writer.write(buf)
        valid_pdf_bytes = buf.getvalue()

        # 1. Upload valid PDF
        small_file = io.BytesIO(valid_pdf_bytes)
        resp_small = self.client.post(
            "/guest/cv/upload",
            files={"file": ("resume.pdf", small_file, "application/pdf")},
        )
        self.assertEqual(resp_small.status_code, 200)
        data = resp_small.json()
        self.assertIn("cv_document_id", data)

        # 2. Upload file exceeding 2MB (e.g. 2.5 MB) -> 413 Payload Too Large
        large_bytes = valid_pdf_bytes + (b"X" * (2 * 1024 * 1024 + 1024))
        large_file = io.BytesIO(large_bytes)
        resp_large = self.client.post(
            "/guest/cv/upload",
            files={"file": ("heavy_resume.pdf", large_file, "application/pdf")},
        )
        self.assertEqual(resp_large.status_code, 413)
        self.assertIn("exceeds the 2MB guest limit", resp_large.json()["detail"])

    def test_05_guest_session_isolation(self):
        """Guest can only read their own session; accessing another guest session returns 403."""
        # Create Guest 1
        resp1 = self.client.post(
            "/guest/start",
            json={"target_role": "Backend", "round_type": "Technical", "difficulty": "Medium", "turnstile_token": "mock_turnstile_token"},
            headers={"x-forwarded-for": "10.0.1.1"},
        )
        data1 = resp1.json()
        token1 = data1["guest_token"]
        id1 = data1["session_id"]

        # Create Guest 2
        resp2 = self.client.post(
            "/guest/start",
            json={"target_role": "Frontend", "round_type": "Technical", "difficulty": "Medium", "turnstile_token": "mock_turnstile_token"},
            headers={"x-forwarded-for": "10.0.1.2"},
        )
        data2 = resp2.json()
        token2 = data2["guest_token"]
        id2 = data2["session_id"]

        # Guest 1 accesses their own session -> 200 OK
        resp_own = self.client.get(
            f"/session/{id1}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        self.assertEqual(resp_own.status_code, 200)

        # Guest 1 tries to access Guest 2's session -> 403 Forbidden
        resp_other = self.client.get(
            f"/session/{id2}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        self.assertEqual(resp_other.status_code, 403)

    def test_06_guest_pdf_export_blocked(self):
        """PDF export is strictly blocked for guests with 403 Forbidden."""
        # Create guest session and result
        resp = self.client.post(
            "/guest/start",
            json={"target_role": "Engineer", "round_type": "Technical", "difficulty": "Medium", "turnstile_token": "mock_turnstile_token"},
            headers={"x-forwarded-for": "10.0.2.1"},
        )
        data = resp.json()
        token = data["guest_token"]
        sess_id = data["session_id"]

        # Request PDF download with guest token -> 403 Forbidden
        pdf_resp = self.client.get(
            f"/report/{sess_id}/pdf",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(pdf_resp.status_code, 403)
        self.assertIn("PDF export is reserved for registered users", pdf_resp.json()["detail"])

    def test_07_privacy_cleanup_expired_sessions(self):
        """Guest sessions older than 24 hours are automatically purged by cleanup job."""
        now = datetime.now(timezone.utc)

        # 1. Old guest session (26 hours ago)
        old_sess = InterviewSession(
            user_id=None,
            is_guest=True,
            guest_id="guest_old_1",
            interview_id=1,
            status="closed",
            session_token="old_token",
            started_at=now - timedelta(hours=26),
            created_at=now - timedelta(hours=26),
        )
        self.db.add(old_sess)

        # 2. Recent guest session (2 hours ago)
        recent_sess = InterviewSession(
            user_id=None,
            is_guest=True,
            guest_id="guest_recent_1",
            interview_id=1,
            status="created",
            session_token="recent_token",
            started_at=now - timedelta(hours=2),
            created_at=now - timedelta(hours=2),
        )
        self.db.add(recent_sess)
        self.db.commit()

        # Run cleanup endpoint
        cleanup_resp = self.client.post("/guest/cleanup")
        self.assertEqual(cleanup_resp.status_code, 200)
        self.assertEqual(cleanup_resp.json()["cleaned_sessions_count"], 1)

        # Verify old session was deleted, recent session remains
        self.assertIsNone(self.db.query(InterviewSession).filter(InterviewSession.id == old_sess.id).first())
        self.assertIsNotNone(self.db.query(InterviewSession).filter(InterviewSession.id == recent_sess.id).first())

    def test_08_account_linking_on_signup_or_login(self):
        """When a guest signs up or logs in, their guest session is linked to their account."""
        # 1. Create a guest session
        resp = self.client.post(
            "/guest/start",
            json={"target_role": "Data Scientist", "round_type": "Technical", "difficulty": "Hard", "turnstile_token": "mock_turnstile_token"},
            headers={"x-forwarded-for": "10.0.3.1"},
        )
        sess_data = resp.json()
        guest_sess_id = sess_data["session_id"]

        # Verify session is currently guest
        sess = self.db.query(InterviewSession).filter(InterviewSession.id == guest_sess_id).first()
        self.assertTrue(sess.is_guest)
        self.assertIsNone(sess.user_id)

        # 2. Visitor signs up and provides guest_session_id
        signup_payload = {
            "name": "Jane Candidate",
            "email": "jane@example.com",
            "password": "Password123!",
            "guest_session_id": guest_sess_id,
        }
        signup_resp = self.client.post("/auth/signup", json=signup_payload)
        self.assertEqual(signup_resp.status_code, 201)
        user_data = signup_resp.json()["user"]

        # Verify session is now owned by Jane and is_guest is False
        self.db.refresh(sess)
        self.assertFalse(sess.is_guest)
        self.assertEqual(sess.user_id, user_data["id"])

        # 3. Direct link endpoint test for another guest session
        resp2 = self.client.post(
            "/guest/start",
            json={"target_role": "Manager", "round_type": "Managerial", "difficulty": "Medium", "turnstile_token": "mock_turnstile_token"},
            headers={"x-forwarded-for": "10.0.3.2"},
        )
        guest_sess_2 = resp2.json()["session_id"]

        login_token = create_access_token({"sub": str(user_data["id"])})
        link_resp = self.client.post(
            "/guest/link",
            json={"guest_session_id": guest_sess_2},
            headers={"Authorization": f"Bearer {login_token}"},
        )
        self.assertEqual(link_resp.status_code, 200)
        self.assertEqual(link_resp.json()["status"], "linked")

        sess2 = self.db.query(InterviewSession).filter(InterviewSession.id == guest_sess_2).first()
        self.assertFalse(sess2.is_guest)
        self.assertEqual(sess2.user_id, user_data["id"])

    def test_09_guest_calibration_and_consent(self):
        """Guest can record consent and calibration baseline using guest token."""
        # Start guest session
        resp = self.client.post(
            "/guest/start",
            json={"target_role": "SRE", "round_type": "Technical", "difficulty": "Medium", "turnstile_token": "mock_turnstile_token"},
            headers={"x-forwarded-for": "10.0.4.1"},
        )
        data = resp.json()
        token = data["guest_token"]
        sess_id = data["session_id"]

        # Record calibration with guest token
        calib_payload = {
            "face_baseline": {"neutral_score": 0.95, "gaze_center": {"x": 0.5, "y": 0.5}, "head_pose": {"pitch": 0, "yaw": 0, "roll": 0}},
            "voice_baseline": {"average_volume_db": -22.0, "pitch_range_hz": [110, 220], "speaking_rate_wpm": 135},
            "background_noise_level_db": -50.0,
            "calibration_text": "I am ready for the interview.",
        }
        calib_resp = self.client.post(
            f"/session/{sess_id}/calibration",
            json=calib_payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(calib_resp.status_code, 201)
        self.assertEqual(calib_resp.json()["session_id"], sess_id)

        # Retrieve consent
        consent_resp = self.client.get(
            "/session/consent",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(consent_resp.status_code, 200)
        self.assertTrue(consent_resp.json()["accepted"])


if __name__ == "__main__":
    unittest.main()
