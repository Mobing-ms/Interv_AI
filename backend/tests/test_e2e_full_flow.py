"""
End-to-End Test Suite: Complete Candidate Lifecycle & Hardened Workflow.
Simulates and validates the entire interview flow:
1. Sign up & authentication (JWT tokens)
2. Onboarding: Target Profile & Education Profile
3. CV Upload, extraction, structuring & Profile confirmation
4. Interview Setup & Blueprint creation
5. Pre-check: Consent, Latency Ping, Network Speed Test, Baseline Calibration
6. Scripted Interview: 3 questions with realistic sample answers, audio streaming & evaluation
7. Session close & Analysis pipeline execution (alignment & scoring)
8. Score fusion, comparison metrics & ranked weak areas
9. Grounded Report generation, grounding evidence references & Improvement Plan
10. Server-side PDF export
11. Security & Privacy verification:
    - Expiring signed recording URLs (HMAC-SHA256)
    - IDOR access control checks
    - Security headers
12. Retake Loop: Question deduplication & weak-area focus in second interview round
13. GDPR 'Delete My Data' endpoint compliance
"""

import sys
import os
import io
import time
import uuid
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import (
    User,
    InterviewSession,
    UserMemory,
    AskedQuestion,
    SessionReport,
    SessionResult,
)
from app.services.answer_capture_service import default_storage_manager
from app.services.signed_url_service import generate_signed_recording_url, verify_signed_recording_url


class TestEndToEndFullFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_complete_interview_lifecycle_end_to_end(self):
        client = self.client
        unique_suffix = uuid.uuid4().hex[:8]
        user_email = f"e2e_candidate_{unique_suffix}@example.com"
        password = "SecurePassword123!"

        # =====================================================================
        # STEP 1: SIGN UP & AUTHENTICATION
        # =====================================================================
        reg_res = client.post(
            "/auth/register",
            json={"email": user_email, "name": "Elena Rostova", "password": password},
        )
        self.assertEqual(reg_res.status_code, 201, f"Registration failed: {reg_res.text}")
        auth_data = reg_res.json()
        token = auth_data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Verify user profile endpoint
        me_res = client.get("/auth/me", headers=headers)
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.json()["email"], user_email)

        # =====================================================================
        # STEP 2: ONBOARDING (EDUCATION & TARGET PROFILES)
        # =====================================================================
        edu_payload = {
            "degree": "Bachelor of Science",
            "branch": "Computer Science & Engineering",
            "college": "University of Washington",
            "graduation_year": 2024,
            "cgpa": 3.85,
            "cgpa_scale": 4.0,
        }
        edu_res = client.put("/profile/education", json=edu_payload, headers=headers)
        self.assertEqual(edu_res.status_code, 200, f"Education setup failed: {edu_res.text}")

        target_payload = {
            "target_role": "Backend Engineer",
            "company_type": "Product",
            "experience_level": "2-5",
        }
        target_res = client.put("/profile/target", json=target_payload, headers=headers)
        self.assertEqual(target_res.status_code, 200, f"Target profile failed: {target_res.text}")

        # =====================================================================
        # STEP 3: CV UPLOAD, EXTRACTION, STRUCTURING & PROFILE CONFIRMATION
        # =====================================================================
        pdf_content = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
            b"4 0 obj\n<< /Length 260 >>\nstream\n"
            b"BT\n"
            b"/F1 14 Tf\n"
            b"50 700 Td\n"
            b"(ELENA ROSTOVA - BACKEND DISTRIBUTED SYSTEMS ENGINEER) Tj\n"
            b"0 -30 Td\n"
            b"(EXPERIENCE: Software Engineer at CloudCorp building rate limiters and event data pipelines.) Tj\n"
            b"0 -30 Td\n"
            b"(EDUCATION: Bachelor of Science in Computer Science, University of Washington, 2024.) Tj\n"
            b"0 -30 Td\n"
            b"(SKILLS: Python, Go, Redis, Kafka, PostgreSQL, Distributed Systems, Microservices, AWS.) Tj\n"
            b"ET\n"
            b"endstream\nendobj\n"
            b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
            b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000244 00000 n \n0000000557 00000 n \n"
            b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n635\n%%EOF"
        )
        files = {"file": ("elena_cv.pdf", io.BytesIO(pdf_content), "application/pdf")}
        upload_res = client.post("/cv/upload", files=files, headers=headers)
        self.assertEqual(upload_res.status_code, 201, f"CV Upload failed: {upload_res.text}")
        cv_id = upload_res.json()["id"]

        # Ensure extraction status
        cv_status = client.get(f"/cv/{cv_id}/status", headers=headers).json()
        self.assertIn(cv_status["status"], ("uploaded", "extracting", "extracted"))

        # Parse and structure CV
        parse_res = client.post(f"/cv/{cv_id}/parse", headers=headers)
        self.assertEqual(parse_res.status_code, 200, f"CV Parsing failed: {parse_res.text}")
        parsed_data = parse_res.json()
        structured_data = parsed_data["structured_data"]

        # Confirm Canonical Profile
        confirm_res = client.post(
            "/profile/confirm",
            json={"cv_document_id": cv_id, "structured_data": structured_data},
            headers=headers,
        )
        self.assertEqual(confirm_res.status_code, 200, f"Profile confirm failed: {confirm_res.text}")
        self.assertEqual(confirm_res.json()["version"], 1)

        # =====================================================================
        # STEP 4: INTERVIEW SETUP (CONFIG & BLUEPRINT)
        # =====================================================================
        setup_payload = {
            "round_type": "Technical",
            "difficulty": "Medium",
            "duration_minutes": 25,
            "language": "English",
            "mode": "normal",
            "focus_topics": ["System Design", "Distributed Caching", "Behavioral Leadership"],
        }
        setup_res = client.post("/interview/setup", json=setup_payload, headers=headers)
        self.assertEqual(setup_res.status_code, 201, f"Interview setup failed: {setup_res.text}")
        interview_cfg_id = setup_res.json()["id"]

        # =====================================================================
        # STEP 5: PRE-CHECK (CONSENT, DIAGNOSTICS & BASELINE CALIBRATION)
        # =====================================================================
        consent_res = client.post(
            "/session/consent",
            json={"version": "1.0", "accepted": True},
            headers=headers,
        )
        self.assertEqual(consent_res.status_code, 201)

        # Latency Ping & Network Speed Test
        ping_res = client.get("/session/ping", headers=headers)
        self.assertEqual(ping_res.status_code, 200)
        self.assertEqual(ping_res.json()["status"], "ok")

        speed_res = client.post("/session/speed-test", data=b"x" * 1024 * 50, headers=headers)
        self.assertEqual(speed_res.status_code, 200)

        # Create Interview Session
        session_res = client.post(
            "/session",
            json={"interview_id": interview_cfg_id},
            headers=headers,
        )
        self.assertEqual(session_res.status_code, 201, f"Session create failed: {session_res.text}")
        session_id = session_res.json()["id"]

        # Baseline Calibration
        cal_payload = {
            "face_baseline": {
                "neutral_score": 0.95,
                "gaze_center": {"x": 0.5, "y": 0.5},
                "head_pose": {"pitch": 1.2, "yaw": -0.8, "roll": 0.1},
            },
            "voice_baseline": {
                "average_volume_db": -22.5,
                "pitch_range_hz": [115.0, 210.0],
                "speaking_rate_wpm": 138.0,
            },
            "background_noise_level_db": -52.0,
            "calibration_text": "I am ready for the technical distributed systems interview.",
        }
        cal_res = client.post(f"/session/{session_id}/calibration", json=cal_payload, headers=headers)
        self.assertEqual(cal_res.status_code, 201)

        # =====================================================================
        # STEP 6: SCRIPTED INTERVIEW (3 QUESTIONS & SAMPLE ANSWERS)
        # =====================================================================
        # Question 1: System Design (Rate Limiting)
        q1_text = "How would you design a distributed rate limiter for a high-traffic microservices gateway?"
        a1_text = (
            "To design a resilient distributed rate limiter at gateway scale, I would utilize a Redis cluster "
            "running the sliding window log or token bucket algorithm. Each incoming request checks user or API key "
            "allowances in Redis using an atomic Lua script to prevent concurrency race conditions. We can deploy "
            "local in-memory token buckets for high throughput and fall back gracefully with HTTP 429 Too Many Requests."
        )

        # Question 2: Data Structures & Caching (LRU Cache)
        q2_text = "Explain how you implement an LRU cache with O(1) read and write operations."
        a2_text = (
            "An LRU cache with constant time O(1) lookup, insertion, and eviction combines a hash table with "
            "a doubly linked list. The hash table maps cache keys to doubly linked list nodes for O(1) lookup. "
            "When a key is read or modified, its node moves to the head of the list. On cache capacity overflow, "
            "the node at the tail is evicted in O(1) time."
        )

        # Question 3: Behavioral / Leadership (Production Incident)
        q3_text = "Tell me about a time you resolved a critical production incident under pressure."
        a3_text = (
            "During a Black Friday spike, our downstream checkout service began dropping database connections. "
            "As the on-call engineer, my task was to mitigate latency and restore orders immediately. "
            "I activated the incident bridge, isolated query contention, enabled circuit breaking with degraded fallback, "
            "and provisioned read-replica connection pools. Within 12 minutes latency returned to p99 < 80ms, "
            "preventing customer order loss, and I led the post-mortem to automate connection shedding."
        )

        # Save artifacts to AnswerStorageManager for each question
        q_data = [
            (1, q1_text, a1_text, "System Design"),
            (2, q2_text, a2_text, "Data Structures"),
            (3, q3_text, a3_text, "Behavioral Leadership"),
        ]

        dummy_audio = b"\x00\x01\x02\x03" * 256
        for q_id, q_str, a_str, topic in q_data:
            default_storage_manager.save_audio_chunk(session_id, q_id, chunk_id=1, audio_bytes=dummy_audio)
            default_storage_manager.save_transcript(
                session_id=session_id,
                question_id=q_id,
                transcript_data={
                    "text": a_str,
                    "words": [{"word": w, "start": i * 0.4, "end": (i + 1) * 0.4} for i, w in enumerate(a_str.split()[:10])],
                },
            )

        # Populate state store session context
        from app.services.session_state import default_state_store, SessionStateData, SessionState
        state = SessionStateData(
            session_id=session_id,
            user_id=me_res.json()["id"],
            state=SessionState.CLOSING,
            current_question_index=3,
            session_context=[
                {"question_id": q[0], "question": q[1], "answer": q[2], "topic": q[3], "score": 88.0}
                for q in q_data
            ],
        )
        default_state_store.save_state(state)

        # =====================================================================
        # STEP 7: SESSION FINALIZE & ANALYSIS PIPELINE EXECUTION
        # =====================================================================
        finalize_res = client.post(f"/session/{session_id}/finalize?sync=true", headers=headers)
        self.assertEqual(finalize_res.status_code, 200, f"Finalize failed: {finalize_res.text}")

        # Verify analysis status
        status_res = client.get(f"/session/{session_id}/analysis-status", headers=headers)
        self.assertEqual(status_res.status_code, 200)
        status_json = status_res.json()
        self.assertIn(status_json["status"], ("completed", "partial"))
        self.assertEqual(status_json["progress"], 100)

        # =====================================================================
        # STEP 8: SCORE FUSION & CONSOLIDATED RESULTS
        # =====================================================================
        result_res = client.get(f"/session/{session_id}/result", headers=headers)
        self.assertEqual(result_res.status_code, 200, f"Result failed: {result_res.text}")
        result_json = result_res.json()
        self.assertIn("overall_score", result_json)
        self.assertIn("content_score", result_json)
        self.assertIn("speech_score", result_json)
        self.assertIn("face_score", result_json)
        self.assertIn("weak_areas", result_json)
        self.assertGreaterEqual(result_json["overall_score"], 60.0)

        # Verify UserMemory and AskedQuestionHistory were persisted
        mem = self.db.query(UserMemory).filter(UserMemory.user_id == me_res.json()["id"]).first()
        self.assertIsNotNone(mem, "UserMemory was not updated upon session completion")

        asked_qs = self.db.query(AskedQuestion).filter(AskedQuestion.user_id == me_res.json()["id"]).all()
        self.assertGreaterEqual(len(asked_qs), 1, "AskedQuestion did not record session questions")

        # =====================================================================
        # STEP 9: REPORT GENERATION & GROUNDING CHECKS
        # =====================================================================
        report_res = client.get(f"/report/{session_id}", headers=headers)
        self.assertEqual(report_res.status_code, 200, f"Report failed: {report_res.text}")
        report_json = report_res.json()
        report_content = report_json.get("report") or report_json
        self.assertIn("overall_summary", report_content)
        self.assertIn("strengths", report_content)
        self.assertIn("gaps", report_content)
        self.assertIn("per_question_feedback", report_content)
        self.assertIn("grounding_audit", report_json)

        # Verify grounding audit has verified claims and 0 dropped claims
        audit = report_json["grounding_audit"]
        self.assertGreater(audit["total_claims_verified"], 0)
        self.assertTrue(audit["is_fully_grounded"])

        # Verify Improvement Plan
        plan_res = client.get(f"/report/{session_id}/improvement-plan", headers=headers)
        self.assertEqual(plan_res.status_code, 200)
        plan_json = plan_res.json()
        self.assertIn("actions", plan_json)
        self.assertGreaterEqual(len(plan_json["actions"]), 2)

        # =====================================================================
        # STEP 10: SERVER-SIDE PDF EXPORT
        # =====================================================================
        pdf_res = client.get(f"/report/{session_id}/pdf", headers=headers)
        self.assertEqual(pdf_res.status_code, 200)
        self.assertEqual(pdf_res.headers["Content-Type"], "application/pdf")
        self.assertTrue(pdf_res.content.startswith(b"%PDF"), "PDF export did not return valid PDF bytes")

        # =====================================================================
        # STEP 11: PRIVACY & SECURITY HARDENING VERIFICATION
        # =====================================================================
        # A. Expiring Signed Recording URLs
        rec_urls_res = client.get(f"/session/{session_id}/recording-urls", headers=headers)
        self.assertEqual(rec_urls_res.status_code, 200)
        urls_json = rec_urls_res.json()
        self.assertIn("audio_url", urls_json)
        self.assertIn("video_manifest_url", urls_json)

        # Download audio via signed URL
        audio_url = urls_json["audio_url"]
        audio_stream_res = client.get(audio_url)
        self.assertEqual(audio_stream_res.status_code, 200)
        self.assertGreater(len(audio_stream_res.content), 0)

        # Tampered or Expired signature must be rejected with 403 Forbidden
        tampered_url = audio_url.replace("sig=", "sig=tampered_signature_")
        tampered_res = client.get(tampered_url)
        self.assertEqual(tampered_res.status_code, 403)

        # B. IDOR Access Control: Second User Cannot Access Elena's Data
        user2_res = client.post(
            "/auth/register",
            json={"email": f"hacker_{unique_suffix}@example.com", "name": "Adversary", "password": password},
        )
        token2 = user2_res.json()["access_token"]
        headers2 = {"Authorization": f"Bearer {token2}"}

        # Second user tries to access Elena's CV
        idor_cv = client.get(f"/cv/{cv_id}/status", headers=headers2)
        self.assertEqual(idor_cv.status_code, 404, "IDOR check failed: other user accessed CV document")

        # Second user tries to access Elena's session
        idor_sess = client.get(f"/session/{session_id}", headers=headers2)
        self.assertEqual(idor_sess.status_code, 404, "IDOR check failed: other user accessed session")

        # Second user tries to access Elena's report
        idor_rep = client.get(f"/report/{session_id}", headers=headers2)
        self.assertEqual(idor_rep.status_code, 404, "IDOR check failed: other user accessed report")

        # C. Security Headers
        self.assertEqual(report_res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(report_res.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("Strict-Transport-Security", report_res.headers)

        # =====================================================================
        # STEP 12: RETAKE LOOP & QUESTION DEDUPLICATION
        # =====================================================================
        # Next interview setup reuses confirmed profile without repeating questions
        retake_cfg_res = client.post(
            "/interview/setup",
            json={
                "round_type": "Technical",
                "difficulty": "Hard",
                "duration_minutes": 30,
                "focus_topics": ["System Design", "Distributed Caching"],
            },
            headers=headers,
        )
        self.assertEqual(retake_cfg_res.status_code, 201)
        new_cfg_id = retake_cfg_res.json()["id"]

        # Generate blueprint for retake session via API
        bp_res = client.post("/interview/blueprint", json={"config_id": new_cfg_id}, headers=headers)
        self.assertEqual(bp_res.status_code, 200, f"Blueprint generation failed: {bp_res.text}")
        blueprint = bp_res.json()
        self.assertIsNotNone(blueprint)

        # Ensure questions in new blueprint do not duplicate asked question texts
        new_q_texts = [q.get("text", "") for q in blueprint.get("questions", [])]
        for past_q in [q1_text, q2_text, q3_text]:
            self.assertNotIn(past_q, new_q_texts, "Retake loop asked a previously asked question")

        # =====================================================================
        # STEP 13: GDPR / CCPA "DELETE MY DATA" ENDPOINT
        # =====================================================================
        delete_data_res = client.delete("/profile/me/data", headers=headers)
        self.assertEqual(delete_data_res.status_code, 200)
        del_json = delete_data_res.json()
        self.assertEqual(del_json["status"], "deleted")
        self.assertGreaterEqual(del_json["purged_records"]["interview_sessions_deleted"], 1)

        # Verify session is gone from database
        check_sess = self.db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
        self.assertIsNone(check_sess, "Interview session was not purged after delete my data request")


if __name__ == "__main__":
    unittest.main()
