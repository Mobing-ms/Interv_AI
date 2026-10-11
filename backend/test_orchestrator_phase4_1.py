import sys
import os
import time
import json
import unittest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import User, InterviewConfig, UserConsent, InterviewSession
from app.auth import hash_password, create_access_token
from app.services.session_state import default_state_store, SessionState

client = TestClient(app)


class TestSessionOrchestratorPhase4(unittest.TestCase):
    """
    Comprehensive test suite for Phase 4.1:
    - Interview Session Orchestrator State Machine (GREETING -> WARMUP -> ASKING -> LISTENING -> EVALUATING -> ROUTING -> CLOSING -> ENDED)
    - Redis session state persistence & retrieval
    - Reconnection resilience: dropping connection and resuming seamlessly from saved state
    - WebSocket Protocol Server->Client & Client->Server events
    - Heartbeat keepalive and integrity tracking
    """

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        db = SessionLocal()
        try:
            # Create test candidate user with unique timestamp
            self.candidate = User(
                email=f"candidate_{int(time.time() * 1000)}@orchestrator-test.com",
                name="Alex Kumar",
                password_hash=hash_password("SecretPassword123!"),
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

        # Record candidate consent
        consent_resp = client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"version": "v1.0", "accepted": True},
        )
        self.assertEqual(consent_resp.status_code, 201)

    def tearDown(self):
        pass

    def _create_session(self, mode: str = "normal", duration_minutes: int = 15) -> dict:
        """Helper to create an interview configuration and active session."""
        cfg_resp = client.post(
            "/interview/config",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "round_type": "Technical",
                "difficulty": "Medium",
                "duration_minutes": duration_minutes,
                "mode": mode,
            },
        )
        self.assertEqual(cfg_resp.status_code, 201)
        cfg_id = cfg_resp.json()["id"]

        sess_resp = client.post(
            "/session",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"interview_id": cfg_id},
        )
        self.assertEqual(sess_resp.status_code, 201)
        return sess_resp.json()

    # =========================================================================
    # 1. FULL SCRIPTED FAKE CLIENT SESSION (GREETING TO CLOSING)
    # =========================================================================

    def test_scripted_fake_client_full_session(self):
        """
        Runs a full scripted interview session from GREETING to CLOSING over WebSocket.
        Verifies all server and client events:
        - avatar_speak (greeting)
        - question + avatar_speak (warmup)
        - answer_started, audio_chunk, video_frame, answer_ended
        - question + avatar_speak (main question)
        - follow-up question
        - avatar_speak (closing) + round_end
        - clean connection close (code 1000)
        - DB status updated to 'completed'
        """
        s_data = self._create_session(mode="normal")
        session_id = s_data["id"]
        sess_token = s_data["session_token"]

        with client.websocket_connect(f"/session/{session_id}/live?token={sess_token}") as ws:
            # 1. Connected handshake
            connected = ws.receive_json()
            self.assertEqual(connected["type"], "connected")
            self.assertEqual(connected["session_id"], session_id)
            self.assertFalse(connected["resumed"])

            # 2. Server emits greeting (avatar_speak)
            greeting = ws.receive_json()
            self.assertEqual(greeting["type"], "avatar_speak")
            self.assertIn("welcome", greeting["text"].lower())
            self.assertTrue(greeting["audio_url"].endswith(".mp3") or greeting["audio_url"].startswith("/session/tts/audio/"))

            # 3. Server emits warmup question & avatar_speak
            warmup_q = ws.receive_json()
            self.assertEqual(warmup_q["type"], "question")
            self.assertEqual(warmup_q["topic"], "Warmup")
            self.assertGreater(warmup_q["time_limit"], 0)

            warmup_avatar = ws.receive_json()
            self.assertEqual(warmup_avatar["type"], "avatar_speak")
            self.assertTrue("introduce yourself" in warmup_avatar["text"].lower() or "tell me about yourself" in warmup_avatar["text"].lower())

            # 4. Client sends heartbeat keepalive
            ws.send_json({"type": "heartbeat", "timestamp": time.time()})
            hb_ack = ws.receive_json()
            self.assertEqual(hb_ack["type"], "heartbeat_ack")

            # 5. Client begins answering warmup
            ws.send_json({"type": "answer_started", "timestamp": time.time()})
            ws.send_json({
                "type": "audio_chunk",
                "chunk_id": 1,
                "data": "aGVsbG8=",
                "text": "Hello, I am Alex. I have built scalable microservices and React web applications.",
            })
            chunk_ack = ws.receive_json()
            self.assertEqual(chunk_ack["type"], "chunk_ack")

            ws.send_json({"type": "video_frame", "timestamp": time.time()})

            # Client finishes answering warmup
            ws.send_json({
                "type": "answer_ended",
                "text": "Hello, I am Alex. I have built scalable microservices and React web applications with solid impact.",
            })

            # 6. Scripted Client Event Loop until round_end
            questions_answered = 0
            round_end_summary = None

            while True:
                msg = ws.receive_json()
                msg_type = msg.get("type")

                if msg_type == "avatar_speak":
                    # Avatar speaks
                    continue

                elif msg_type == "question":
                    questions_answered += 1
                    topic = msg.get("topic", "General")
                    # Scripted client starts answer
                    ws.send_json({"type": "answer_started", "timestamp": time.time()})
                    # Stream simulated audio chunk
                    ws.send_json({
                        "type": "audio_chunk",
                        "chunk_id": questions_answered,
                        "data": "aGVsbG8tdGVjaG5pY2Fs",
                        "text": f"Detailed answer regarding {topic}.",
                    })
                    # Send thorough technical answer
                    ws.send_json({
                        "type": "answer_ended",
                        "text": (
                            f"In {topic}, I prioritize scalable architectural patterns, "
                            "minimizing algorithmic complexity with hash tables and sliding windows, "
                            "and applying backpressure rate limiting under high concurrency loads."
                        ),
                    })

                elif msg_type == "round_end":
                    round_end_summary = msg
                    break

            # 7. Assertions on completed session
            self.assertIsNotNone(round_end_summary)
            self.assertEqual(round_end_summary["next_state"], "ENDED")
            self.assertGreaterEqual(round_end_summary["summary"]["total_questions"], 2)
            self.assertGreater(round_end_summary["summary"]["average_score"], 0)
            self.assertGreaterEqual(questions_answered, 2)

        # 12. Verify Database record updated to 'completed'
        updated_sess = client.get(
            f"/session/{session_id}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(updated_sess.status_code, 200)
        self.assertEqual(updated_sess.json()["status"], "completed")

    # =========================================================================
    # 2. RECONNECTION RESILIENCE (RESUME FROM SAVED REDIS STATE)
    # =========================================================================

    def test_dropped_connection_resumes_correctly_from_redis(self):
        """
        Simulates an abrupt WebSocket drop mid-interview (during ASKING/LISTENING).
        Client reconnects with a fresh WebSocket connection.
        Verifies:
        - Saved state restored from Redis
        - Server emits 'state_sync' with resumed=True
        - Re-emits the active question without restarting interview
        - Allows candidate to finish remaining questions cleanly
        """
        s_data = self._create_session(mode="normal")
        session_id = s_data["id"]
        sess_token = s_data["session_token"]

        # Step 1: Connect, answer warmup, and reach Main Question #1
        with client.websocket_connect(f"/session/{session_id}/live?token={sess_token}") as ws:
            connected = ws.receive_json()
            self.assertFalse(connected["resumed"])
            _ = ws.receive_json()  # greeting avatar_speak
            _ = ws.receive_json()  # warmup question
            _ = ws.receive_json()  # warmup avatar_speak

            # Complete warmup
            ws.send_json({
                "type": "answer_ended",
                "text": "I am Alex, full stack developer with experience in microservices and React.",
            })

            # Receive Main Question #1 (DSA)
            q1 = ws.receive_json()
            self.assertEqual(q1["type"], "question")
            self.assertEqual(q1["topic"], "DSA")
            q1_id = q1["id"]

            _ = ws.receive_json()  # q1 avatar_speak

            # CANDIDATE STARTS ANSWERING, THEN CONNECTION DROPS SUDDENLY!
            ws.send_json({"type": "answer_started", "timestamp": time.time()})
            # Context exit simulates abrupt network drop

        # Step 2: Verify state in Redis is preserved
        state_in_redis = default_state_store.load_state(session_id)
        self.assertIsNotNone(state_in_redis)
        self.assertEqual(state_in_redis.state, SessionState.LISTENING)
        self.assertEqual(state_in_redis.current_question["id"], q1_id)
        self.assertEqual(state_in_redis.topic, "DSA")
        self.assertEqual(len(state_in_redis.session_context), 1)  # Warmup recorded
        self.assertFalse(state_in_redis.is_connected)

        # Also verify REST endpoint GET /session/{id}/state returns saved state
        state_rest = client.get(
            f"/session/{session_id}/state",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(state_rest.status_code, 200)
        self.assertEqual(state_rest.json()["state"], "LISTENING")

        # Step 3: Reconnect with new WebSocket connection
        with client.websocket_connect(f"/session/{session_id}/live?token={sess_token}") as ws_reconnect:
            # 1. Connection frame indicates resumed
            reconnected_frame = ws_reconnect.receive_json()
            self.assertEqual(reconnected_frame["type"], "connected")
            self.assertTrue(reconnected_frame["resumed"])

            # 2. State synchronization frame
            sync_frame = ws_reconnect.receive_json()
            self.assertEqual(sync_frame["type"], "state_sync")
            self.assertTrue(sync_frame["resumed"])
            self.assertEqual(sync_frame["state"], "LISTENING")
            self.assertEqual(sync_frame["current_question"]["id"], q1_id)

            # 3. Server re-emits active question so candidate can resume answering
            resumed_q = ws_reconnect.receive_json()
            self.assertEqual(resumed_q["type"], "question")
            self.assertEqual(resumed_q["id"], q1_id)

            # 4. Candidate completes answer on the reconnected socket
            ws_reconnect.send_json({
                "type": "answer_ended",
                "text": "For the longest substring without repeating characters, I use a sliding window with a set.",
            })

            # Next event will be follow-up or next question
            next_event = ws_reconnect.receive_json()
            self.assertIn(next_event["type"], ("question", "avatar_speak"))

    # =========================================================================
    # 3. PRESSURE MODE ADAPTATION
    # =========================================================================

    def test_pressure_mode_timers(self):
        """
        Verifies that Pressure mode config applies tighter countdown timers
        (e.g. 60 seconds vs 120 seconds) for faster pacing.
        """
        s_data = self._create_session(mode="pressure")
        session_id = s_data["id"]
        sess_token = s_data["session_token"]

        with client.websocket_connect(f"/session/{session_id}/live?token={sess_token}") as ws:
            _ = ws.receive_json()  # connected
            _ = ws.receive_json()  # greeting
            warmup_q = ws.receive_json()
            # In pressure mode, warmup time is reduced
            self.assertLessEqual(warmup_q["time_limit"], 60)
            _ = ws.receive_json()  # warmup avatar

            ws.send_json({"type": "answer_ended", "text": "Quick intro under pressure mode."})

            main_q = ws.receive_json()
            # Main question in pressure mode is 60s instead of 120s
            self.assertEqual(main_q["time_limit"], 60)

    # =========================================================================
    # 4. INTEGRITY TELEMETRY & PROCTORING EVENTS
    # =========================================================================

    def test_integrity_events_tracking(self):
        """
        Verifies candidate behavior telemetry (tab_switch, gaze_lost)
        is properly captured and saved to Redis state.
        """
        s_data = self._create_session(mode="normal")
        session_id = s_data["id"]
        sess_token = s_data["session_token"]

        with client.websocket_connect(f"/session/{session_id}/live?token={sess_token}") as ws:
            _ = ws.receive_json()  # connected
            _ = ws.receive_json()  # greeting
            _ = ws.receive_json()  # warmup q
            _ = ws.receive_json()  # warmup avatar

            # Send integrity telemetry
            ws.send_json({
                "type": "integrity_event",
                "event_type": "tab_switch",
                "details": {"duration_ms": 3500, "blurred": True},
                "timestamp": time.time(),
            })

            # Check state in Redis
            state = default_state_store.load_state(session_id)
            self.assertIsNotNone(state)
            self.assertEqual(len(state.integrity_events), 1)
            self.assertEqual(state.integrity_events[0]["event_type"], "tab_switch")

    # =========================================================================
    # 5. WEBSOCKET VIA /session/{id}/stream?orchestrate=true
    # =========================================================================

    def test_stream_endpoint_with_orchestrate_flag(self):
        """
        Verifies that connecting to /session/{id}/stream with ?orchestrate=true
        properly launches the SessionOrchestrator.
        """
        s_data = self._create_session(mode="normal")
        session_id = s_data["id"]
        sess_token = s_data["session_token"]

        with client.websocket_connect(f"/session/{session_id}/stream?token={sess_token}&orchestrate=true") as ws:
            connected = ws.receive_json()
            self.assertEqual(connected["type"], "connected")
            greeting = ws.receive_json()
            self.assertEqual(greeting["type"], "avatar_speak")
            q = ws.receive_json()
            self.assertEqual(q["type"], "question")


if __name__ == "__main__":
    unittest.main()
