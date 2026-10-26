import os
import io
import time
import json
import math
import struct
import base64
import logging
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("intervai.answer_capture")

# Try importing webrtcvad
try:
    import webrtcvad
    WEBRTC_VAD_AVAILABLE = True
except ImportError:
    WEBRTC_VAD_AVAILABLE = False
    logger.info("webrtcvad not available; falling back to energy-based VAD.")

# Try importing faster_whisper
try:
    import faster_whisper
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    logger.info("faster_whisper not available; using streaming STT provider.")


# =============================================================================
# 1. VOICE ACTIVITY DETECTION (VAD) & SILENCE TRACKER
# =============================================================================

class VADDetector:
    """
    Voice Activity Detector combining WebRTC VAD (for 16 kHz 16-bit mono PCM)
    with an energy-based RMS fallback.
    """

    def __init__(self, aggressiveness: int = 2, sample_rate: int = 16000, energy_threshold: float = 300.0):
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.vad = webrtcvad.Vad(aggressiveness) if WEBRTC_VAD_AVAILABLE else None

    def is_speech_pcm(self, pcm_bytes: bytes) -> bool:
        """
        Determines if speech is present in 16 kHz 16-bit mono PCM chunk.
        Combines noise-floor energy gating with WebRTC VAD classification.
        """
        if not pcm_bytes or len(pcm_bytes) < 320:
            return False

        # 1. Calculate RMS energy
        try:
            sample_count = len(pcm_bytes) // 2
            samples = struct.unpack(f"<{sample_count}h", pcm_bytes[: sample_count * 2])
            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / sample_count)
            if rms < 100.0:
                return False
        except Exception:
            return False

        # 2. WebRTC VAD on 30ms frames (960 bytes)
        if self.vad and len(pcm_bytes) >= 960:
            frame_len = int(self.sample_rate * 0.03 * 2)  # 30ms * 2 bytes/sample = 960 bytes
            num_frames = len(pcm_bytes) // frame_len
            speech_frames = 0
            for i in range(num_frames):
                frame = pcm_bytes[i * frame_len : (i + 1) * frame_len]
                try:
                    if self.vad.is_speech(frame, self.sample_rate):
                        speech_frames += 1
                except Exception:
                    logging.getLogger(__name__).debug("Suppressed exception", exc_info=True)
            if num_frames > 0 and (speech_frames / num_frames) >= 0.3:
                return True

        # 3. Fallback energy threshold
        return rms > self.energy_threshold



class VoiceActivityTracker:
    """
    Tracks real-time voice activity and speech flow per question.
    Implements silence threshold (e.g. 2.5 seconds) with protection logic
    against cutting off candidates mid-thought (requires minimum speech duration).
    """

    def __init__(
        self,
        silence_timeout_seconds: float = 2.5,
        min_speech_duration_seconds: float = 1.0,
        vad_detector: Optional[VADDetector] = None,
    ):
        self.silence_timeout_seconds = silence_timeout_seconds
        self.min_speech_duration_seconds = min_speech_duration_seconds
        self.vad = vad_detector or VADDetector()

        self.speech_started: bool = False
        self.first_speech_time: Optional[float] = None
        self.last_speech_time: Optional[float] = None
        self.total_speech_duration: float = 0.0
        self.total_chunks_processed: int = 0
        self.is_answer_completed: bool = False

    def reset(self) -> None:
        """Resets tracker for a fresh interview question."""
        self.speech_started = False
        self.first_speech_time = None
        self.last_speech_time = None
        self.total_speech_duration = 0.0
        self.total_chunks_processed = 0
        self.is_answer_completed = False

    def feed_audio(
        self,
        pcm_bytes: bytes,
        current_time: Optional[float] = None,
        chunk_duration_seconds: float = 0.25,
        is_speech: Optional[bool] = None,
    ) -> Tuple[bool, bool, float]:
        """
        Feeds an incoming audio chunk.
        Returns:
            (is_speech, should_end_answer, current_silence_duration)
        """
        now = current_time or time.time()
        self.total_chunks_processed += 1
        if is_speech is None:
            is_speech = self.vad.is_speech_pcm(pcm_bytes)


        if is_speech:
            if not self.speech_started:
                self.speech_started = True
                self.first_speech_time = now
            self.last_speech_time = now
            self.total_speech_duration += chunk_duration_seconds
            return True, False, 0.0
        else:
            silence_duration = 0.0
            should_end = False

            if self.speech_started and self.last_speech_time is not None:
                silence_duration = max(0.0, now - self.last_speech_time)
                # Avoid cutting people off mid-thought: only mark end of answer
                # if candidate has delivered substantial speech (> min_speech_duration)
                if (
                    silence_duration >= self.silence_timeout_seconds
                    and self.total_speech_duration >= self.min_speech_duration_seconds
                    and not self.is_answer_completed
                ):
                    should_end = True
                    self.is_answer_completed = True

            return False, should_end, silence_duration


# =============================================================================
# 2. 8-SECOND SILENCE RULE & HESITATION NUDGE
# =============================================================================

class SilenceNudgeDetector:
    """
    Enforces the 8-second silence rule:
    If no speech within 8 seconds of question ending / answer timer start:
    - Sends a gentle nudge or a rephrased version of the question.
    - Logs a hesitation event with timestamp and question ID.
    - Strictly only nudges once per question.
    """

    def __init__(self, silence_threshold_seconds: float = 8.0):
        self.silence_threshold = silence_threshold_seconds

    def check_nudge(
        self,
        answer_start_time: float,
        speech_detected: bool,
        has_nudged: bool,
        question: Dict[str, Any],
        current_time: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates whether an 8-second silence nudge should be triggered.
        Returns:
            Nudge payload dict if rule is triggered, or None.
        """
        now = current_time or time.time()
        elapsed = now - answer_start_time

        # If candidate has started speaking, or already nudged, or within 8s -> no nudge
        if speech_detected or has_nudged or elapsed < self.silence_threshold:
            return None

        q_topic = question.get("topic", "General")
        q_text = question.get("text", "")
        q_id = question.get("id")

        # Generate contextual rephrase / encouragement
        if "scale" in q_text.lower() or "design" in q_text.lower():
            nudge_text = "Take your time! You can start by mentioning key components or high-level architecture before detailing scale."
        elif "dsa" in q_topic.lower() or "algorithm" in q_text.lower():
            nudge_text = "Feel free to talk through a brute-force approach first, then we can optimize time and space complexity."
        elif "yourself" in q_text.lower() or "background" in q_text.lower():
            nudge_text = "Whenever you're ready, feel free to give a brief 1-minute highlight of your journey and current technical focus."
        else:
            nudge_text = f"Take your time! Feel free to think out loud regarding {q_topic} and outline your core thoughts."

        hesitation_event = {
            "event_type": "hesitation",
            "details": {
                "question_id": q_id,
                "silence_duration_seconds": round(elapsed, 2),
                "threshold_seconds": self.silence_threshold,
                "topic": q_topic,
            },
            "timestamp": now,
        }

        return {
            "nudge_text": nudge_text,
            "hesitation_event": hesitation_event,
            "silence_duration": round(elapsed, 2),
            "question_id": q_id,
        }


# =============================================================================
# 3. STREAMING SPEECH-TO-TEXT WITH WORD-LEVEL TIMESTAMPS
# =============================================================================

class BaseSTTProvider:
    """Abstract base provider for Speech-To-Text."""

    def transcribe_chunk(
        self,
        audio_bytes: bytes,
        language: str = "en",
        base_timestamp: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Returns:
            {
                "text": str,
                "words": List[{"word": str, "start": float, "end": float, "probability": float}]
            }
        """
        raise NotImplementedError


class MockStreamingSTTProvider(BaseSTTProvider):
    """
    Fast deterministic streaming STT provider for tests, mock streaming,
    and offline operation. Emits realistic word-level timestamps.
    """

    def transcribe_chunk(
        self,
        audio_bytes: bytes,
        language: str = "en",
        base_timestamp: float = 0.0,
    ) -> Dict[str, Any]:
        return {
            "text": "",
            "words": [],
        }

    def transcribe_text_to_timed_words(
        self,
        text: str,
        start_time: float = 0.0,
        words_per_second: float = 2.5,
    ) -> Dict[str, Any]:
        """Converts text into word items with sequential start/end timestamps."""
        tokens = text.strip().split()
        words = []
        curr_t = start_time
        sec_per_word = 1.0 / max(0.5, words_per_second)

        for w in tokens:
            w_start = round(curr_t, 2)
            w_end = round(curr_t + sec_per_word * 0.85, 2)
            words.append({
                "word": w,
                "start": w_start,
                "end": w_end,
                "probability": 0.98,
            })
            curr_t += sec_per_word

        return {
            "text": text.strip(),
            "words": words,
            "duration": round(curr_t - start_time, 2),
        }


class FasterWhisperSTTProvider(BaseSTTProvider):
    """
    Streaming STT provider leveraging faster-whisper with word timestamps.
    """

    def __init__(self, model_size: str = "tiny"):
        self.model = None
        self.model_size = model_size
        self._init_model()

    def _init_model(self):
        if FASTER_WHISPER_AVAILABLE:
            try:
                # Use CPU with int8 quantization for lightweight streaming
                self.model = faster_whisper.WhisperModel(self.model_size, device="cpu", compute_type="int8")
            except Exception as e:
                logger.info("faster-whisper model load deferred or failed: %s", e)

    def transcribe_chunk(
        self,
        audio_bytes: bytes,
        language: str = "en",
        base_timestamp: float = 0.0,
    ) -> Dict[str, Any]:
        if not self.model or len(audio_bytes) < 3200:
            return {"text": "", "words": []}

        try:
            audio_io = io.BytesIO(audio_bytes)
            segments, info = self.model.transcribe(
                audio_io,
                language=language,
                word_timestamps=True,
                beam_size=1,
            )
            words = []
            full_text_parts = []
            for seg in segments:
                full_text_parts.append(seg.text.strip())
                if seg.words:
                    for w in seg.words:
                        words.append({
                            "word": w.word,
                            "start": round(base_timestamp + w.start, 2),
                            "end": round(base_timestamp + w.end, 2),
                            "probability": round(w.probability, 2),
                        })
            return {
                "text": " ".join(full_text_parts),
                "words": words,
            }
        except Exception as e:
            logger.warning("Error in faster-whisper transcribe: %s", e)
            return {"text": "", "words": []}


class StreamingSTTService:
    """
    Central STT service managing candidate answer transcription,
    word-level timestamps, and live progress per question.
    """

    def __init__(self, provider: Optional[BaseSTTProvider] = None):
        self.provider = provider or (
            FasterWhisperSTTProvider() if FASTER_WHISPER_AVAILABLE else MockStreamingSTTProvider()
        )
        self.mock_fallback = MockStreamingSTTProvider()
        # Per-question transcript buffers: {question_id: {"text": str, "words": list}}
        self._transcripts: Dict[int, Dict[str, Any]] = {}

    def reset_question(self, question_id: int) -> None:
        self._transcripts[question_id] = {
            "text": "",
            "words": [],
            "updated_at": time.time(),
        }

    def append_transcript_text(
        self,
        question_id: int,
        text_chunk: str,
        start_time_offset: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Appends transcribed text chunk and computes word-level timings.
        """
        if question_id not in self._transcripts:
            self.reset_question(question_id)

        rec = self._transcripts[question_id]
        existing_words = rec.get("words", [])
        curr_offset = existing_words[-1]["end"] if existing_words else start_time_offset

        timed = self.mock_fallback.transcribe_text_to_timed_words(text_chunk, start_time=curr_offset)
        new_words = timed.get("words", [])

        if rec["text"]:
            rec["text"] += " " + text_chunk.strip()
        else:
            rec["text"] = text_chunk.strip()

        rec["words"].extend(new_words)
        rec["updated_at"] = time.time()
        return rec

    def get_transcript(self, question_id: int) -> Dict[str, Any]:
        return self._transcripts.get(
            question_id,
            {"text": "", "words": [], "updated_at": time.time()},
        )


# =============================================================================
# 4. CHUNK STORAGE MANAGER (Audio & Video per session_id/question_id)
# =============================================================================

class AnswerStorageManager:
    """
    Stores audio chunks, video frames, and word-timed transcripts under:
    {base_dir}/{session_id}/{question_id}/
    """

    def __init__(self, base_dir: Optional[str] = None):
        if not base_dir:
            from app.config import settings
            base_dir = settings.data_path("storage", "sessions")
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)


    def _get_target_dir(self, session_id: int, question_id: int) -> str:
        d = os.path.join(self.base_dir, str(session_id), str(question_id))
        os.makedirs(d, exist_ok=True)
        return d

    def save_audio_chunk(
        self,
        session_id: int,
        question_id: int,
        chunk_id: int,
        audio_bytes: bytes,
    ) -> str:
        """Saves or appends audio chunk bytes."""
        target_dir = self._get_target_dir(session_id, question_id)
        chunks_dir = os.path.join(target_dir, "audio_chunks")
        os.makedirs(chunks_dir, exist_ok=True)

        chunk_path = os.path.join(chunks_dir, f"chunk_{chunk_id:04d}.bin")
        with open(chunk_path, "wb") as f:
            f.write(audio_bytes)

        # Also append to consolidated audio file
        master_audio_path = os.path.join(target_dir, "audio_stream.bin")
        with open(master_audio_path, "ab") as f:
            f.write(audio_bytes)

        return chunk_path

    def save_video_frame(
        self,
        session_id: int,
        question_id: int,
        frame_id: int,
        frame_data: str | bytes,
    ) -> str:
        """Saves a 1 fps video frame (base64 data URL or raw image bytes)."""
        target_dir = self._get_target_dir(session_id, question_id)
        frames_dir = os.path.join(target_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        frame_path = os.path.join(frames_dir, f"frame_{frame_id:04d}.jpg")
        if isinstance(frame_data, str):
            # Strip data:image/jpeg;base64, prefix if present
            if "," in frame_data:
                frame_data = frame_data.split(",", 1)[1]
            raw_bytes = base64.b64decode(frame_data)
        else:
            raw_bytes = frame_data

        with open(frame_path, "wb") as f:
            f.write(raw_bytes)

        return frame_path

    def save_transcript(
        self,
        session_id: int,
        question_id: int,
        transcript_data: Dict[str, Any],
    ) -> str:
        """Saves transcript with word timings as transcript.json."""
        target_dir = self._get_target_dir(session_id, question_id)
        transcript_path = os.path.join(target_dir, "transcript.json")
        payload = {
            "session_id": session_id,
            "question_id": question_id,
            "text": transcript_data.get("text", ""),
            "words": transcript_data.get("words", []),
            "saved_at": time.time(),
        }
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        return transcript_path

    def get_question_artifacts(self, session_id: int, question_id: int) -> Dict[str, Any]:
        """Retrieves stored artifact metadata for a given question."""
        target_dir = self._get_target_dir(session_id, question_id)
        frames_dir = os.path.join(target_dir, "frames")
        chunks_dir = os.path.join(target_dir, "audio_chunks")
        transcript_path = os.path.join(target_dir, "transcript.json")

        num_frames = len(os.listdir(frames_dir)) if os.path.exists(frames_dir) else 0
        num_chunks = len(os.listdir(chunks_dir)) if os.path.exists(chunks_dir) else 0
        has_transcript = os.path.exists(transcript_path)

        transcript_content = None
        if has_transcript:
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    transcript_content = json.load(f)
            except Exception:
                logging.getLogger(__name__).debug("Suppressed exception", exc_info=True)

        return {
            "session_id": session_id,
            "question_id": question_id,
            "audio_chunks_count": num_chunks,
            "video_frames_count": num_frames,
            "has_transcript": has_transcript,
            "transcript": transcript_content,
        }

    def finalize_session_recordings(self, session_id: int) -> Dict[str, Any]:
        """
        Finalizes recordings across all questions for the session:
        - Merges audio chunks into a consolidated session audio file.
        - Compiles a video manifest / frame registry for object storage.
        - Generates persistent storage file keys.
        """
        sess_dir = os.path.join(self.base_dir, str(session_id))
        os.makedirs(sess_dir, exist_ok=True)

        merged_audio_path = os.path.join(sess_dir, "audio_merged.bin")
        video_manifest_path = os.path.join(sess_dir, "video_manifest.json")

        total_audio_bytes = 0
        all_frames: List[Dict[str, Any]] = []

        # 1. Merge audio across questions
        with open(merged_audio_path, "wb") as master_audio:
            if os.path.exists(sess_dir):
                # Iterate over question subdirectories (named numerically)
                subdirs = sorted([d for d in os.listdir(sess_dir) if d.isdigit()], key=lambda x: int(x))
                for q_str in subdirs:
                    q_dir = os.path.join(sess_dir, q_str)
                    # Check audio_stream.bin or audio_chunks/
                    q_stream = os.path.join(q_dir, "audio_stream.bin")
                    if os.path.exists(q_stream):
                        with open(q_stream, "rb") as qf:
                            chunk_data = qf.read()
                            master_audio.write(chunk_data)
                            total_audio_bytes += len(chunk_data)
                    else:
                        chunks_dir = os.path.join(q_dir, "audio_chunks")
                        if os.path.exists(chunks_dir):
                            chunk_files = sorted(os.listdir(chunks_dir))
                            for cf in chunk_files:
                                cp = os.path.join(chunks_dir, cf)
                                with open(cp, "rb") as f:
                                    cd = f.read()
                                    master_audio.write(cd)
                                    total_audio_bytes += len(cd)

                    # Collect video frames
                    frames_dir = os.path.join(q_dir, "frames")
                    if os.path.exists(frames_dir):
                        for ff in sorted(os.listdir(frames_dir)):
                            fp = os.path.join(frames_dir, ff)
                            all_frames.append({
                                "question_id": int(q_str),
                                "filename": ff,
                                "path": fp,
                                "size_bytes": os.path.getsize(fp) if os.path.exists(fp) else 0,
                            })

        # 2. Write video manifest
        with open(video_manifest_path, "w", encoding="utf-8") as vf:
            json.dump({
                "session_id": session_id,
                "total_frames": len(all_frames),
                "frames": all_frames,
                "finalized_at": time.time(),
            }, vf, indent=2)

        audio_file_key = f"sessions/{session_id}/audio_merged.bin"
        video_file_key = f"sessions/{session_id}/video_manifest.json"

        return {
            "session_id": session_id,
            "audio_file_key": audio_file_key,
            "video_file_key": video_file_key,
            "audio_merged_path": merged_audio_path,
            "video_manifest_path": video_manifest_path,
            "total_audio_bytes": total_audio_bytes,
            "total_video_frames": len(all_frames),
            "finalized_at": time.time(),
        }


# Singletons
default_vad_detector = VADDetector()
default_voice_tracker = VoiceActivityTracker(vad_detector=default_vad_detector)
default_nudge_detector = SilenceNudgeDetector()
default_stt_service = StreamingSTTService()
default_storage_manager = AnswerStorageManager()
