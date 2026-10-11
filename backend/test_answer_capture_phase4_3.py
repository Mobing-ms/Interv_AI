import sys
import os
import time
import json
import base64
import unittest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import User, TargetProfile, InterviewConfig, UserConsent, InterviewSession
from app.auth import hash_password, create_access_token
from app.services.answer_capture_service import (
    VADDetector,
    VoiceActivityTracker,
    SilenceNudgeDetector,
    StreamingSTTService,
    MockStreamingSTTProvider,
    AnswerStorageManager,
    default_storage_manager,
)
from app.services.session_state import default_state_store, SessionState

client = TestClient(app)


class TestAnswerCapturePhase4_3(unittest.TestCase):
    """
    Test suite for Phase 4.3 (Answer Capture):
    1. 8-second silence rule: triggers one gentle nudge and logs hesitation event; never nudges twice for the same question.
    2. Voice activity detection (VAD): marks end of answer after 2.5s silence; avoids cutting people off prematurely.
    3. Streaming STT: outputs transcript with word-level timestamps.
    4. Storage manager: persists audio chunks, video frames, and transcript under session_id/question_id.
    5. Full WebSocket session: verifies 1 fps video frames, 16 kHz audio chunks, live transcript updates, and automatic VAD answer completion.
    """

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        db = SessionLocal()
        try:
            self.test_user = User(
                email=f"alex_capture_{int(time.time() * 1000)}@test.com",
                name="Alex Kumar",
                password_hash=hash_password("AlexPass123!"),
                auth_provider="email",
                is_verified=True,
                onboarding_status="completed",
            )
            db.add(self.test_user)
            db.commit()
            db.refresh(self.test_user)

            self.target_profile = TargetProfile(
                user_id=self.test_user.id,
                target_role="Frontend Engineer",
                company_type="Product",
                experience_level="Mid",
            )
            db.add(self.target_profile)
            db.commit()

            self.token = create_access_token(
                data={"sub": str(self.test_user.id), "email": self.test_user.email}
            )
        finally:
            db.close()

        # Record consent
        client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"version": "v1.0", "accepted": True},
        )

    def _create_session(self) -> dict:
        cfg_resp = client.post(
            "/interview/config",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"round_type": "Technical", "difficulty": "Medium", "duration_minutes": 20},
        )
        self.assertEqual(cfg_resp.status_code, 201)
        sess_resp = client.post(
            "/session",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"interview_id": cfg_resp.json()["id"]},
        )
        self.assertEqual(sess_resp.status_code, 201)
        return sess_resp.json()

    # =========================================================================
    # 1. 8-SECOND SILENCE RULE TESTS
    # =========================================================================

    def test_silence_nudge_rule_triggers_once_and_logs_hesitation(self):
        """If candidate remains silent for 8 seconds, triggers nudge & hesitation event; never nudges twice."""
        detector = SilenceNudgeDetector(silence_threshold_seconds=8.0)
        q = {"id": 1, "topic": "DSA", "text": "Design a rate limiter"}
        t0 = 1000.0

        # At 5 seconds: no nudge
        res_5s = detector.check_nudge(answer_start_time=t0, speech_detected=False, has_nudged=False, question=q, current_time=t0 + 5.0)
        self.assertIsNone(res_5s)

        # At 8.1 seconds: triggers nudge and logs hesitation event
        res_8s = detector.check_nudge(answer_start_time=t0, speech_detected=False, has_nudged=False, question=q, current_time=t0 + 8.1)
        self.assertIsNotNone(res_8s)
        self.assertIn("nudge_text", res_8s)
        self.assertEqual(res_8s["question_id"], 1)

        hesitation = res_8s["hesitation_event"]
        self.assertEqual(hesitation["event_type"], "hesitation")
        self.assertEqual(hesitation["details"]["question_id"], 1)
        self.assertGreaterEqual(hesitation["details"]["silence_duration_seconds"], 8.0)

        # At 12 seconds with has_nudged=True: MUST NOT nudge again (strictly only once per question)
        res_12s = detector.check_nudge(answer_start_time=t0, speech_detected=False, has_nudged=True, question=q, current_time=t0 + 12.0)
        self.assertIsNone(res_12s)

        # If speech was detected at 4 seconds: MUST NOT nudge
        res_speech = detector.check_nudge(answer_start_time=t0, speech_detected=True, has_nudged=False, question=q, current_time=t0 + 9.0)
        self.assertIsNone(res_speech)

    # =========================================================================
    # 2. VOICE ACTIVITY DETECTION (VAD) & SILENCE THRESHOLD TESTS
    # =========================================================================

    def test_voice_activity_tracker_detects_speech_and_silence_end(self):
        """
        VoiceActivityTracker:
        - Detects speech start
        - Avoids cutting off prematurely before min_speech_duration
        - After candidate speaks >= 1.0s and pauses for >= 2.5s, ends answer automatically
        """
        tracker = VoiceActivityTracker(silence_timeout_seconds=2.5, min_speech_duration_seconds=1.0)
        t = 100.0

        # 16 kHz 16-bit mono: 480 samples = 960 bytes (30ms), amplitude 8192
        speech_chunk = b"\x00\x20" * 480
        silence_chunk = b"\x00\x00" * 480


        # Feed 1.5 seconds of speech (6 chunks of 0.25s)
        for _ in range(6):
            is_speech, should_end, _ = tracker.feed_audio(speech_chunk, current_time=t, chunk_duration_seconds=0.25)
            self.assertTrue(is_speech)
            self.assertFalse(should_end)
            t += 0.25

        self.assertTrue(tracker.speech_started)
        self.assertGreaterEqual(tracker.total_speech_duration, 1.0)

        # Feed 1.0 second of silence -> should NOT end yet (below 2.5s threshold)
        t += 1.0
        is_speech, should_end, silence_dur = tracker.feed_audio(silence_chunk, current_time=t, chunk_duration_seconds=0.25)
        self.assertFalse(is_speech)
        self.assertFalse(should_end)
        self.assertGreaterEqual(silence_dur, 1.0)

        # Feed additional 1.6 seconds of silence -> total silence = 2.6s >= 2.5s -> SHOULD END ANSWER
        t += 1.6
        is_speech, should_end, silence_dur = tracker.feed_audio(silence_chunk, current_time=t, chunk_duration_seconds=0.25)
        self.assertFalse(is_speech)
        self.assertTrue(should_end)
        self.assertGreaterEqual(silence_dur, 2.5)

    def test_vad_does_not_cut_off_without_sufficient_speech(self):
        """If candidate makes a 0.2s mic noise and goes silent, tracker does not cut them off mid-thought."""
        tracker = VoiceActivityTracker(silence_timeout_seconds=2.5, min_speech_duration_seconds=1.0)
        t = 100.0
        speech_chunk = b"\x00\x20" * 480
        silence_chunk = b"\x00\x00" * 480


        # Only 0.2s of speech
        tracker.feed_audio(speech_chunk, current_time=t, chunk_duration_seconds=0.2)
        t += 3.0  # 3 seconds of silence
        _, should_end, _ = tracker.feed_audio(silence_chunk, current_time=t, chunk_duration_seconds=0.25)
        # Should not end because total speech duration is only 0.2s (< 1.0s min)
        self.assertFalse(should_end)

    # =========================================================================
    # 3. STREAMING STT & WORD-LEVEL TIMESTAMPS
    # =========================================================================

    def test_streaming_stt_generates_word_level_timestamps(self):
        """Streaming STT appends candidate speech and returns word-level timestamps."""
        stt = StreamingSTTService(provider=MockStreamingSTTProvider())
        q_id = 42

        # First chunk
        res1 = stt.append_transcript_text(q_id, "I designed a distributed cache")
        self.assertEqual(res1["text"], "I designed a distributed cache")
        words1 = res1["words"]
        self.assertEqual(len(words1), 5)
        self.assertEqual(words1[0]["word"], "I")
        self.assertIn("start", words1[0])
        self.assertIn("end", words1[0])
        self.assertLess(words1[0]["start"], words1[0]["end"])

        # Second chunk
        res2 = stt.append_transcript_text(q_id, "using Redis cluster")
        self.assertEqual(res2["text"], "I designed a distributed cache using Redis cluster")
        words2 = res2["words"]
        self.assertEqual(len(words2), 8)
        # Timestamps must be strictly progressive
        self.assertGreaterEqual(words2[5]["start"], words1[4]["end"])

    # =========================================================================
    # 4. ARTIFACT STORAGE MANAGER
    # =========================================================================

    def test_answer_storage_persists_chunks_frames_and_transcript(self):
        """Storage manager saves audio chunks, video frames, and transcript under session_id/question_id."""
        storage = default_storage_manager
        sess_id = 9999
        q_id = 1

        # 1. Save audio chunk
        audio_path = storage.save_audio_chunk(sess_id, q_id, chunk_id=1, audio_bytes=b"dummy_pcm_audio_data")
        self.assertTrue(os.path.exists(audio_path))

        # 2. Save 1 fps video frame
        dummy_base64_jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0\x00\x10JFIF").decode()
        frame_path = storage.save_video_frame(sess_id, q_id, frame_id=1, frame_data=dummy_base64_jpeg)
        self.assertTrue(os.path.exists(frame_path))

        # 3. Save transcript with word timings
        transcript_data = {
            "text": "Hello world from test",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.4},
                {"word": "world", "start": 0.45, "end": 0.9},
                {"word": "from", "start": 0.95, "end": 1.2},
                {"word": "test", "start": 1.25, "end": 1.6},
            ],
        }
        transcript_path = storage.save_transcript(sess_id, q_id, transcript_data)
        self.assertTrue(os.path.exists(transcript_path))

        # 4. Verify get_question_artifacts
        artifacts = storage.get_question_artifacts(sess_id, q_id)
        self.assertEqual(artifacts["audio_chunks_count"], 1)
        self.assertEqual(artifacts["video_frames_count"], 1)
        self.assertTrue(artifacts["has_transcript"])
        self.assertEqual(artifacts["transcript"]["text"], "Hello world from test")
        self.assertEqual(len(artifacts["transcript"]["words"]), 4)

    # =========================================================================
    # 5. WEBSOCKET SESSION FLOW (VAD AUTOMATIC FINISH & 8S SILENCE NUDGE)
    # =========================================================================

    def test_websocket_8_second_silence_nudge_flow(self):
        """
        WebSocket session flow:
        - Candidate finishes avatar speech and sends client_ready -> timer starts.
        - Candidate stays silent for >= 8s -> server emits nudge and logs hesitation event.
        - Subsequent events do NOT re-nudge for the same question.
        """
        s_data = self._create_session()
        sess_id = s_data["id"]
        sess_token = s_data["session_token"]

        with client.websocket_connect(f"/session/{sess_id}/live?token={sess_token}") as ws:
            # 1. Connected handshake
            f_conn = ws.receive_json()
            self.assertEqual(f_conn["type"], "connected")

            # 2. Avatar greeting
            f_greet = ws.receive_json()
            self.assertEqual(f_greet["type"], "avatar_speak")

            # 3. Warmup question & avatar speak
            f_q = ws.receive_json()
            self.assertEqual(f_q["type"], "question")
            f_q_speak = ws.receive_json()
            self.assertEqual(f_q_speak["type"], "avatar_speak")

            # 4. Client signals speech finished
            ws.send_json({"type": "client_ready", "timestamp": time.time()})
            f_timer = ws.receive_json()
            self.assertEqual(f_timer["type"], "timer_started")

            # 5. Send heartbeat after 8.5 seconds of simulated silence
            silence_timestamp = time.time() + 8.5
            ws.send_json({"type": "heartbeat", "timestamp": silence_timestamp})

            # Server emits heartbeat_ack
            f_ack = ws.receive_json()
            self.assertEqual(f_ack["type"], "heartbeat_ack")

            # Server triggers 8-second silence rule -> emits nudge & avatar_speak
            f_nudge = ws.receive_json()
            self.assertEqual(f_nudge["type"], "nudge")
            self.assertEqual(f_nudge["reason"], "silence_8s")

            f_nudge_speak = ws.receive_json()
            self.assertEqual(f_nudge_speak["type"], "avatar_speak")

            # Verify hesitation event logged in session state
            state_resp = client.get(f"/session/{sess_id}/state", headers={"Authorization": f"Bearer {self.token}"})
            self.assertEqual(state_resp.status_code, 200)
            st_data = state_resp.json()
            hesitations = [ev for ev in st_data.get("integrity_events", []) if ev.get("event_type") == "hesitation"]
            self.assertGreaterEqual(len(hesitations), 1)

            # Send another heartbeat -> MUST NOT nudge a second time
            ws.send_json({"type": "heartbeat", "timestamp": silence_timestamp + 5.0})
            f_ack2 = ws.receive_json()
            self.assertEqual(f_ack2["type"], "heartbeat_ack")

    def test_websocket_vad_automatic_answer_finish_and_transcript_timings(self):
        """
        WebSocket session flow:
        - Candidate sends 1 fps video frames and 16 kHz audio chunks with streaming text.
        - Server emits transcript_update with word-level timestamps.
        - Candidate finishes speaking and remains silent -> VAD automatically finishes answer (finish_reason='vad_silence').
        - Word timings are saved per question.
        """
        s_data = self._create_session()
        sess_id = s_data["id"]
        sess_token = s_data["session_token"]

        with client.websocket_connect(f"/session/{sess_id}/live?token={sess_token}") as ws:
            ws.receive_json()  # connected
            ws.receive_json()  # greeting
            ws.receive_json()  # question
            ws.receive_json()  # avatar_speak

            # Ready signal
            ws.send_json({"type": "client_ready", "timestamp": time.time()})
            ws.receive_json()  # timer_started

            # 1. Send 1 fps video frame
            dummy_jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0\x00\x10JFIFframe").decode()
            ws.send_json({"type": "video_frame", "frame": dummy_jpeg, "timestamp": time.time()})
            f_vack = ws.receive_json()
            self.assertEqual(f_vack["type"], "video_frame_ack")

            # 2. Send 5 speech chunks (1.25s of speech) with partial streaming transcript
            dummy_pcm_speech = base64.b64encode(b"\x7f\x00" * 480).decode()
            curr_t = time.time()

            for i in range(5):
                ws.send_json({
                    "type": "audio_chunk",
                    "chunk_id": i + 1,
                    "data": dummy_pcm_speech,
                    "is_speech": True,
                    "duration": 0.25,
                    "stream_transcript": True if i == 0 else False,
                    "text": "I have experience with React" if i == 0 else "",
                    "timestamp": curr_t,
                })
                curr_t += 0.25
                f_cack = ws.receive_json()
                self.assertEqual(f_cack["type"], "chunk_ack")
                self.assertTrue(f_cack["is_speech"])
                if i == 0:
                    # Receives live streaming transcript with word timestamps
                    f_trans = ws.receive_json()
                    self.assertEqual(f_trans["type"], "transcript_update")
                    self.assertIn("React", f_trans["text"])
                    self.assertGreater(len(f_trans["words"]), 0)

            # 3. Candidate finishes speaking and remains silent for 2.6s
            # Send silence chunk at curr_t + 2.6s
            curr_t += 2.6
            dummy_pcm_silence = base64.b64encode(b"\x00\x00" * 480).decode()
            ws.send_json({
                "type": "audio_chunk",
                "chunk_id": 6,
                "data": dummy_pcm_silence,
                "is_speech": False,
                "duration": 0.25,
                "timestamp": curr_t,
            })

            # Receives chunk_ack
            f_silence_ack = ws.receive_json()
            self.assertEqual(f_silence_ack["type"], "chunk_ack")
            self.assertFalse(f_silence_ack["is_speech"])

            # VAD silence threshold reached: server automatically finishes answer!
            f_ans_complete = ws.receive_json()
            self.assertEqual(f_ans_complete["type"], "answer_complete")
            self.assertEqual(f_ans_complete["finish_reason"], "vad_silence")
            self.assertIn("React", f_ans_complete["text"])
            self.assertGreater(f_ans_complete["word_count"], 0)

            # Advances to EVALUATING -> ROUTING -> ASKING next question
            f_next_q = ws.receive_json()
            self.assertEqual(f_next_q["type"], "question")
            self.assertNotEqual(f_next_q["topic"], "Warmup")

            # Check that question artifacts and word-level timings are persisted on disk
            art_resp = client.get(
                f"/session/{sess_id}/question/1/artifacts",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            self.assertEqual(art_resp.status_code, 200)
            art_data = art_resp.json()
            self.assertTrue(art_data["has_transcript"])
            self.assertGreater(art_data["audio_chunks_count"], 0)
            self.assertGreater(art_data["video_frames_count"], 0)
            self.assertIn("React", art_data["transcript"]["text"])
            self.assertGreater(len(art_data["transcript"]["words"]), 0)


if __name__ == "__main__":
    unittest.main()
