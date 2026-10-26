import time
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable

from fastapi import WebSocket, WebSocketDisconnect

from app.database import SessionLocal
from app.models import User, InterviewSession, InterviewConfig, QuestionBankItem
from app.config import settings
from app.services.tts_service import default_tts_service
from app.services.question_selector import select_next_question
from app.services.session_state import (
    SessionState,
    SessionStateData,
    RedisStateStore,
    default_state_store,
)
from app.services.orchestrator_modules import (
    QuestionSelectorProtocol,
    TTSModuleProtocol,
    EvaluatorModuleProtocol,
    RouterModuleProtocol,
    StubQuestionSelector,
    StubTTS,
    StubEvaluator,
    StubRouter,
)
from app.services.evaluator_service import LLMAnswerEvaluator
from app.services.router_service import (
    RouterService,
    generate_probing_follow_up,
    handle_closing_inquiry,
)
from app.services.signal_workers import (
    ParallelSignalProcessor,
    default_signal_processor,
)
from app.services.answer_capture_service import (
    VoiceActivityTracker,
    SilenceNudgeDetector,
    StreamingSTTService,
    AnswerStorageManager,
    default_stt_service,
    default_storage_manager,
)
from app.services.integrity_monitor import IntegrityMonitor
from app.models import SessionCalibration

logger = logging.getLogger("intervai.session_orchestrator")


class SessionOrchestrator:
    """
    Core state machine orchestrator for real-time interview sessions.
    Manages session lifecycle (GREETING -> WARMUP -> ASKING -> LISTENING ->
    EVALUATING -> ROUTING -> CLOSING -> ENDED) over WebSockets with Redis persistence.
    """

    def __init__(
        self,
        session_id: int,
        user_id: int,
        state_store: Optional[RedisStateStore] = None,
        question_selector: Optional[QuestionSelectorProtocol] = None,
        tts_module: Optional[TTSModuleProtocol] = None,
        evaluator_module: Optional[EvaluatorModuleProtocol] = None,
        router_module: Optional[RouterModuleProtocol] = None,
        heartbeat_timeout_seconds: Optional[float] = None,
        voice_tracker: Optional[VoiceActivityTracker] = None,
        nudge_detector: Optional[SilenceNudgeDetector] = None,
        stt_service: Optional[StreamingSTTService] = None,
        storage_manager: Optional[AnswerStorageManager] = None,
        signal_processor: Optional[ParallelSignalProcessor] = None,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.state_store = state_store or default_state_store
        self.question_selector = question_selector or StubQuestionSelector()
        self.tts = tts_module or StubTTS()
        self.evaluator = evaluator_module or LLMAnswerEvaluator()
        self.router = router_module or RouterService()
        self.heartbeat_timeout = (
            heartbeat_timeout_seconds
            if heartbeat_timeout_seconds is not None
            else settings.HEARTBEAT_TIMEOUT_SECONDS
        )
        self.voice_tracker = voice_tracker or VoiceActivityTracker(silence_timeout_seconds=2.5, min_speech_duration_seconds=1.0)
        self.nudge_detector = nudge_detector or SilenceNudgeDetector(silence_threshold_seconds=8.0)
        self.stt_service = stt_service or default_stt_service
        self.storage_manager = storage_manager or default_storage_manager
        self.signal_processor = signal_processor or default_signal_processor
        self.integrity_monitor = IntegrityMonitor(
            session_id=self.session_id,
            face_missing_threshold_seconds=3.0,
            flag_threshold_count=3,
            emit_callback=self.emit,
        )

        # Load calibration baseline if available for this session
        self.calibration: Optional[Dict[str, Any]] = None
        db = SessionLocal()
        try:
            cal_rec = db.query(SessionCalibration).filter(SessionCalibration.session_id == self.session_id).first()
            if cal_rec:
                self.calibration = {
                    "face_baseline": cal_rec.face_baseline,
                    "voice_baseline": cal_rec.voice_baseline,
                    "background_noise_level_db": cal_rec.background_noise_level_db,
                }
        except Exception as e:
            logger.debug("Could not query session calibration: %s", e)
        finally:
            db.close()


        self.ws: Optional[WebSocket] = None
        self.state: Optional[SessionStateData] = None
        self._is_running: bool = False
        self._last_tick_time: float = time.time()
        self._last_persist_time: float = 0.0
        self._send_lock = asyncio.Lock()
        self._keepalive_task: Optional[asyncio.Task] = None

    # =========================================================================
    # 1. STATE INITIALIZATION & RESUMPTION
    # =========================================================================

    def _load_or_initialize_state(self) -> SessionStateData:
        """
        Loads session state from Redis. If none exists, creates a fresh initial state
        by inspecting the database InterviewSession and InterviewConfig.
        """
        saved = self.state_store.load_state(self.session_id)
        if saved and saved.state != SessionState.ENDED:
            saved.is_connected = True
            saved.last_heartbeat = time.time()
            self.state_store.save_state(saved)
            return saved

        # Initialize from database
        db = SessionLocal()
        interview_id = None
        mode = "normal"
        round_type = "Technical"
        difficulty = "Medium"
        duration_minutes = 30
        language = "English"
        user_name = "Candidate"
        target_role = "Software Engineer"
        try:
            user_obj = db.query(User).filter(User.id == self.user_id).first()
            if user_obj:
                user_name = user_obj.name or "Candidate"
                if user_obj.target_profile and user_obj.target_profile.target_role:
                    target_role = user_obj.target_profile.target_role

            sess_record = db.query(InterviewSession).filter(InterviewSession.id == self.session_id).first()
            if sess_record and sess_record.interview_id:
                interview_id = sess_record.interview_id
                cfg = db.query(InterviewConfig).filter(InterviewConfig.id == interview_id).first()
                if cfg:
                    mode = cfg.mode or "normal"
                    round_type = cfg.round_type or "Technical"
                    difficulty = cfg.difficulty or "Medium"
                    duration_minutes = cfg.duration_minutes or 30
                    language = cfg.language or "English"
        finally:
            db.close()

        now = time.time()
        new_state = SessionStateData(
            session_id=self.session_id,
            user_id=self.user_id,
            interview_id=interview_id,
            state=SessionState.GREETING,
            previous_state=None,
            elapsed_time=0.0,
            created_at=now,
            updated_at=now,
            last_heartbeat=now,
            mode=mode,
            round_type=round_type,
            difficulty=difficulty,
            duration_minutes=duration_minutes,
            user_name=user_name,
            target_role=target_role,
            language=language,
            is_connected=True,
        )
        self.state_store.save_state(new_state)
        return new_state

    # =========================================================================
    # 2. WEBSOCKET EVENT EMITTERS (Server -> Client)
    # =========================================================================

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Sends a JSON frame to the connected client."""
        if self.ws:
            payload = {"type": event_type, "session_id": self.session_id, **data}
            try:
                # Serialize sends: the keepalive task and the event loop share one socket.
                async with self._send_lock:
                    await self.ws.send_json(payload)
            except Exception as e:
                logger.warning("Error emitting event %s for session #%d: %s", event_type, self.session_id, e)

    async def emit_avatar_speak(self, text: str, voice_style: str = "neutral") -> None:
        """Server -> Client: avatar_speak (text, audio_url, cache_key, language)."""
        lang = self.state.language if self.state else "English"
        # TTS may hit the network or disk: never run it on the event loop thread.
        try:
            synth = await asyncio.to_thread(
                default_tts_service.synthesize_speech, text, language=lang, voice_style=voice_style
            )
        except Exception:
            logger.exception("TTS synthesis failed for session #%d; sending text only", self.session_id)
            synth = {}
        await self.emit("avatar_speak", {
            "text": text,
            "audio_url": synth.get("audio_url", ""),
            "cache_key": synth.get("cache_key", ""),
            "language": synth.get("language", "en"),
            "timestamp": time.time(),
        })

    async def emit_question(self, q: Dict[str, Any]) -> None:
        """Server -> Client: question (id, text, time_limit, topic, is_follow_up)."""
        await self.emit("question", {
            "id": q["id"],
            "text": q["text"],
            "time_limit": q.get("time_limit", 120),
            "topic": q.get("topic", "General"),
            "subtopic": q.get("subtopic"),
            "difficulty": q.get("difficulty", "Medium"),
            "is_follow_up": q.get("is_follow_up", False),
            "timestamp": time.time(),
        })

    async def emit_nudge(self, text: str, reason: str = "silence") -> None:
        """Server -> Client: nudge (text, reason)."""
        await self.emit("nudge", {
            "text": text,
            "reason": reason,
            "timestamp": time.time(),
        })

    async def emit_round_end(self, summary: Dict[str, Any]) -> None:
        """Server -> Client: round_end (summary, next_state)."""
        await self.emit("round_end", {
            "summary": summary,
            "next_state": "ENDED",
            "session_id": self.session_id,
            "next_url": f"/interview/processing/{self.session_id}",
            "timestamp": time.time(),
        })

    async def emit_state_sync(self, resumed: bool = False) -> None:
        """Server -> Client: state_sync for reconnect or progress synchronization."""
        if not self.state:
            return
        await self.emit("state_sync", {
            "resumed": resumed,
            "state": self.state.state.value,
            "current_question": self.state.current_question,
            "topic": self.state.topic,
            "elapsed_time": round(self.state.elapsed_time, 2),
            "follow_up_count_per_topic": self.state.follow_up_count_per_topic,
            "context_count": len(self.state.session_context),
            "timestamp": time.time(),
        })

    def _select_next_question(self) -> Optional[Dict[str, Any]]:
        """
        Uses Question Selector service to select next question based on blueprint,
        topic weights, difficulty level, candidate CV items, and non-repeating rules.
        """
        if not self.state:
            return None

        # 1. Return pending follow-up if one is queued
        if self.state.pending_followup:
            fu = self.state.pending_followup
            self.state.pending_followup = None
            return fu

        # 2. Query QuestionBankItem from DB if exists
        pool: List[Dict[str, Any]] = []
        db = SessionLocal()
        try:
            if self.state.interview_id:
                items = (
                    db.query(QuestionBankItem)
                    .filter(QuestionBankItem.interview_id == self.state.interview_id)
                    .all()
                )
                for it in items:
                    pool.append({
                        "id": it.id,
                        "text": it.question_text,
                        "topic": it.topic,
                        "subtopic": it.subtopic,
                        "difficulty": it.difficulty,
                        "is_cv_based": bool(it.cv_item_reference),
                        "time_limit": it.max_time_seconds,
                        "expected_keywords": it.expected_keywords or [],
                    })
        finally:
            db.close()

        # 3. Fallback to default pool if database has none
        if not pool:
            time_limit = (
                settings.ORCHESTRATOR_PRESSURE_QUESTION_TIME_SECONDS
                if self.state.mode == "pressure"
                else settings.ORCHESTRATOR_QUESTION_TIME_SECONDS
            )
            pool = [
                {
                    "id": 101,
                    "text": "How would you design an algorithm to find the longest substring without repeating characters, and what are the time and space complexity trade-offs?",
                    "topic": "DSA",
                    "subtopic": "Sliding Window",
                    "difficulty": "Medium",
                    "is_cv_based": True,
                    "time_limit": time_limit,
                    "expected_keywords": ["hash set", "sliding window", "two pointers", "O(N)"],
                },
                {
                    "id": 102,
                    "text": "Explain how you would architect a horizontally scalable distributed rate limiter supporting 100,000 requests per second.",
                    "topic": "System Design",
                    "subtopic": "Distributed Rate Limiting",
                    "difficulty": "Medium",
                    "is_cv_based": True,
                    "time_limit": time_limit,
                    "expected_keywords": ["Redis", "token bucket", "concurrency", "low latency"],
                },
                {
                    "id": 103,
                    "text": "Describe the difference between process and thread concurrency, including virtual memory isolation and context switching overhead.",
                    "topic": "Core CS",
                    "subtopic": "Operating Systems",
                    "difficulty": "Medium",
                    "is_cv_based": False,
                    "time_limit": time_limit,
                    "expected_keywords": ["threads", "virtual memory", "context switch", "CPU cache"],
                },
                {
                    "id": 104,
                    "text": "Walk me through how you implement database indexing with B-Trees and handle write-heavy lock contention.",
                    "topic": "DSA",
                    "subtopic": "Indexing",
                    "difficulty": "Hard",
                    "is_cv_based": False,
                    "time_limit": time_limit,
                    "expected_keywords": ["b-tree", "index", "locks", "wal"],
                },
                {
                    "id": 105,
                    "text": "Tell me about a challenging technical trade-off you had to make in a recent production project.",
                    "topic": "Behavioral",
                    "subtopic": "Decision Making",
                    "difficulty": "Medium",
                    "is_cv_based": True,
                    "time_limit": time_limit,
                    "expected_keywords": ["trade-off", "performance", "delivery", "outcome"],
                },
            ]

        # 4. Blueprint topics
        bp = {
            "topics": [
                {"name": "DSA", "weight": 0.4},
                {"name": "System Design", "weight": 0.3},
                {"name": "Core CS", "weight": 0.3},
            ],
            "difficulty_curve": [self.state.difficulty, self.state.difficulty, "Hard"],
        }

        # 5. Call pure testable question selector function
        selected = select_next_question(
            question_pool=pool,
            blueprint=bp,
            session_context=self.state.session_context,
            pending_followup=None,
            current_difficulty=self.state.difficulty,
        )

        # Fallback to selector module if pool completely exhausted
        if not selected:
            selected = self.question_selector.get_next_question(self.state)

        return selected

    # =========================================================================
    # 3. STATE MACHINE TRANSITIONS
    # =========================================================================

    PERSIST_MIN_INTERVAL_SECONDS = 2.0

    def _persist(self) -> None:
        """Saves current in-memory state to the state store (used on transitions)."""
        if self.state:
            now = time.time()
            dt = max(0.0, now - self._last_tick_time)
            self._last_tick_time = now
            self.state.elapsed_time += dt
            self.state.updated_at = now
            self._last_persist_time = now
            self.state_store.save_state(self.state)

    def _persist_throttled(self) -> None:
        """High-frequency paths (audio/video/heartbeat) persist at most every ~2s."""
        if time.time() - self._last_persist_time >= self.PERSIST_MIN_INTERVAL_SECONDS:
            self._persist()

    async def _evaluate_answer(self, question: Dict[str, Any], answer: str) -> Dict[str, Any]:
        """Runs the evaluator without blocking the event loop."""
        ctx = self.state.session_context if self.state else []
        evaluate_async = getattr(self.evaluator, "evaluate_async", None)
        if evaluate_async is not None:
            return await evaluate_async(question, answer, ctx, session_id=self.session_id)
        return await asyncio.to_thread(self.evaluator.evaluate, question, answer, ctx, session_id=self.session_id)

    def transition_to(self, new_state: SessionState) -> None:
        """Transitions state and records history."""
        if not self.state:
            return
        logger.info(
            "Session #%d transitioning from %s to %s",
            self.session_id,
            self.state.state.value,
            new_state.value,
        )
        self.state.previous_state = self.state.state
        self.state.state = new_state
        self._persist()

    async def run_state_action(self) -> None:
        """
        Executes active autonomous server actions for states:
        GREETING, WARMUP, ASKING, EVALUATING, ROUTING, CLOSING, ENDED.
        For LISTENING, waits for candidate client events.
        """
        if not self.state:
            return

        try:
            curr_state = self.state.state

            # -----------------------------------------------------------------
            # STATE: GREETING
            # -----------------------------------------------------------------
            if curr_state == SessionState.GREETING:
                candidate_name = self.state.user_name or "Candidate"
                target_role = self.state.target_role or "Software Engineer"
                greeting_text = (
                    f"Hello {candidate_name}! Welcome to your {target_role} interview with IntervAI. "
                    "I will be your interviewer today. I'm excited to learn more about your technical background and experience."
                )
                self.transition_to(SessionState.WARMUP)
                await self.emit_avatar_speak(greeting_text)
                # Brief pause so the candidate hears the greeting before warmup question kicks in
                await asyncio.sleep(2.5)
                await self.run_state_action()

            # -----------------------------------------------------------------
            # STATE: WARMUP
            # -----------------------------------------------------------------
            elif curr_state == SessionState.WARMUP:
                warmup_limit = (
                    max(30, int(settings.ORCHESTRATOR_WARMUP_TIME_SECONDS * 0.5))
                    if self.state.mode == "pressure"
                    else settings.ORCHESTRATOR_WARMUP_TIME_SECONDS
                )
                # Requirement: The first question is always "Tell me about yourself"
                warmup_q = {
                    "id": 1,
                    "text": "Tell me about yourself, your background, and what drew you to this role.",
                    "topic": "Warmup",
                    "subtopic": "Introduction",
                    "difficulty": "Easy",
                    "time_limit": warmup_limit,
                    "is_follow_up": False,
                    "expected_keywords": ["experience", "projects", "background", "role", "technologies"],
                }
                self.state.current_question = warmup_q
                self.state.topic = "Warmup"
                self.state.current_answer_text = ""
                self.state.current_question_nudged = False
                self.state.current_question_speech_detected = False
                self.voice_tracker.reset()
                self.stt_service.reset_question(warmup_q["id"])
                self._persist()

                await self.emit_question(warmup_q)
                await self.emit_avatar_speak(warmup_q["text"])
                self.transition_to(SessionState.LISTENING)

            # -----------------------------------------------------------------
            # STATE: ASKING
            # -----------------------------------------------------------------
            elif curr_state == SessionState.ASKING:
                q = self.state.current_question
                if not q:
                    q = self._select_next_question()

                if not q:
                    # No more questions -> transition to closing
                    self.transition_to(SessionState.CLOSING)
                    await self.run_state_action()
                    return

                self.state.current_question = q
                self.state.topic = q.get("topic")
                self.state.current_answer_text = ""
                self.state.current_question_nudged = False
                self.state.current_question_speech_detected = False
                self.voice_tracker.reset()
                if "id" in q:
                    self.stt_service.reset_question(q["id"])
                self._persist()

                await self.emit_question(q)
                await self.emit_avatar_speak(q["text"])
                self.transition_to(SessionState.LISTENING)

            # -----------------------------------------------------------------
            # STATE: LISTENING
            # -----------------------------------------------------------------
            elif curr_state == SessionState.LISTENING:
                # Active listening is driven reactively by client events:
                # answer_started, audio_chunk, video_frame, answer_ended.
                pass

            # -----------------------------------------------------------------
            # STATE: EVALUATING
            # -----------------------------------------------------------------
            elif curr_state == SessionState.EVALUATING:
                curr_q = self.state.current_question or {}
                ans_text = self.state.current_answer_text or ""
                eval_res = await self._evaluate_answer(curr_q, ans_text)

                # Append to persistent session context with validated evaluation metrics
                context_item = {
                    "question_id": curr_q.get("id"),
                    "question": curr_q.get("text"),
                    "topic": curr_q.get("topic"),
                    "subtopic": curr_q.get("subtopic"),
                    "is_follow_up": curr_q.get("is_follow_up", False),
                    "answer": ans_text,
                    "relevance": eval_res.get("relevance", 7.0),
                    "correctness": eval_res.get("correctness", 7.0),
                    "depth": eval_res.get("depth", 7.0),
                    "score": eval_res.get("overall_score", eval_res.get("score", 7.0)),
                    "classification": eval_res.get("classification", "OK"),
                    "feedback": eval_res.get("feedback", eval_res.get("justification", "")),
                    "justification": eval_res.get("justification", ""),
                    "keyword_coverage": eval_res.get("keyword_coverage", {}),
                    "star_completeness": eval_res.get("star_completeness", {}),
                    "follow_up_gap": eval_res.get("follow_up_gap", ""),
                    "key_points_covered": eval_res.get("key_points_covered", eval_res.get("keyword_coverage", {}).get("matched", [])),
                    "word_count": eval_res.get("word_count", len(ans_text.split())),
                    "transcript_words": self.state.question_transcripts.get(curr_q.get("id", 1), {}).get("words", []),
                    "follow_up_needed": eval_res.get("follow_up_needed", False),
                    "asked_at": time.time(),
                }
                self.state.session_context.append(context_item)

                # Increment topic follow-up count if applicable
                if curr_q.get("is_follow_up") and self.state.topic:
                    t = self.state.topic
                    self.state.follow_up_count_per_topic[t] = self.state.follow_up_count_per_topic.get(t, 0) + 1

                self._persist()

                # Transition to ROUTING
                self.transition_to(SessionState.ROUTING)
                await self.run_state_action()

            # -----------------------------------------------------------------
            # STATE: ROUTING
            # -----------------------------------------------------------------
            elif curr_state == SessionState.ROUTING:
                last_eval = (
                    self.state.session_context[-1]
                    if self.state.session_context
                    else {"follow_up_needed": False}
                )
                route = self.router.decide_route(self.state, last_eval)
                action = route.get("action", "next_question")

                # Handle difficulty adjustment
                diff_adj = route.get("difficulty_adjustment")
                if diff_adj == "raise":
                    diff_map = {"Easy": "Medium", "Medium": "Hard", "Hard": "Hard", "Adaptive": "Hard"}
                    self.state.difficulty = diff_map.get(self.state.difficulty, "Hard")
                elif diff_adj == "lower":
                    diff_map = {"Hard": "Medium", "Medium": "Easy", "Easy": "Easy", "Adaptive": "Easy"}
                    self.state.difficulty = diff_map.get(self.state.difficulty, "Easy")

                # 1. Redirect for OFF_TOPIC (repeat question once)
                if action == "redirect":
                    curr_q = self.state.current_question or {}
                    q_id_str = str(curr_q.get("id", "current"))
                    self.state.question_repeat_count[q_id_str] = self.state.question_repeat_count.get(q_id_str, 0) + 1
                    self._persist()

                    redirect_msg = route.get("redirect_message") or f"Let's refocus on the original question: {curr_q.get('text', '')}"
                    await self.emit("redirect", {
                        "text": redirect_msg,
                        "message": redirect_msg,
                        "question": curr_q,
                        "reason": route.get("reason", "off_topic"),
                    })
                    await self.emit_avatar_speak(redirect_msg)
                    self.transition_to(SessionState.ASKING)
                    await self.run_state_action()
                    return

                # 2. Follow-up probing for WEAK_VAGUE (strictly max 2 per topic)
                if action == "follow_up":
                    fu_q = None
                    if hasattr(self.question_selector, "get_follow_up"):
                        fu_q = self.question_selector.get_follow_up(self.state, last_eval)
                    if not fu_q:
                        fu_q = generate_probing_follow_up(
                            self.state.current_question or {},
                            last_eval,
                            route.get("topic") or self.state.topic or "General",
                        )

                    if fu_q:
                        self.state.current_question = fu_q
                        self.state.pending_followup = fu_q
                        self._persist()
                        self.transition_to(SessionState.ASKING)
                        await self.run_state_action()
                        return

                # 3. Next question / next topic / deepen topic
                if action in ("next_question", "deepen_topic", "next_topic"):
                    nxt_q = self.question_selector.get_next_question(self.state)
                    if nxt_q:
                        self.state.current_question = nxt_q
                        self.state.pending_followup = None
                        self._persist()
                        self.transition_to(SessionState.ASKING)
                        await self.run_state_action()
                        return
                    else:
                        self.transition_to(SessionState.CLOSING)
                        await self.run_state_action()
                        return

                # Default fallback: close
                self.transition_to(SessionState.CLOSING)
                await self.run_state_action()

            # -----------------------------------------------------------------
            # STATE: CLOSING
            # -----------------------------------------------------------------
            elif curr_state == SessionState.CLOSING:
                closing_q = self.question_selector.get_closing(self.state)
                closing_text = closing_q.get("text", "")
                if "questions for us" not in closing_text.lower():
                    closing_text = (
                        "That concludes all of our interview questions for today! "
                        "Do you have any questions for us about the role, our engineering team, or our tech stack? "
                        "Thank you very much for your time and for sharing your experience with us."
                    )
                await self.emit_avatar_speak(closing_text)

                # Compile final summary
                scores = [c["score"] for c in self.state.session_context if "score" in c]
                avg_score = round(sum(scores) / max(1, len(scores)), 1) if scores else 8.0
                topics_covered = list(set([c.get("topic") for c in self.state.session_context if c.get("topic")]))

                summary = {
                    "total_questions": len(self.state.session_context),
                    "average_score": avg_score,
                    "topics_covered": topics_covered,
                    "elapsed_time_seconds": round(self.state.elapsed_time, 1),
                }

                await self.emit_round_end(summary)
                self.transition_to(SessionState.ENDED)
                await self.run_state_action()

            # -----------------------------------------------------------------
            # STATE: ENDED
            # -----------------------------------------------------------------
            elif curr_state == SessionState.ENDED:
                self._persist()
                # Finalize recordings, update session status to CLOSED, and store file keys
                from app.services.analysis_pipeline import default_analysis_manager
                # Both touch disk/DB; keep them off the event loop.
                await asyncio.to_thread(default_analysis_manager.close_and_finalize_session, self.session_id)
                analysis_job = await asyncio.to_thread(default_analysis_manager.enqueue_analysis_job, self.session_id)
                logger.info("Session #%d ended: analysis job enqueued (%s)", self.session_id, analysis_job.get("job_id"))

                # Clean close
                if self.ws:
                    try:
                        await self.ws.close(code=1000, reason="Interview completed cleanly")
                    except Exception:
                        logger.debug("WebSocket already closed for session #%d", self.session_id)

        except Exception as e:
            logger.exception("Error executing orchestrator action for session #%d", self.session_id)
            if self.state:
                self.state.error_detail = f"{type(e).__name__}"
                self.transition_to(SessionState.ERROR)
                await self.emit("error", {"code": "internal_error", "detail": "Internal server error", "timestamp": time.time()})

    # =========================================================================
    # 3.5 ANSWER CAPTURE, VAD & SILENCE NUDGE HELPERS
    # =========================================================================

    async def _check_silence_nudge(self, current_time: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Enforces 8-second silence rule:
        If no speech detected within 8 seconds of question ending / answer phase start,
        emits gentle nudge/rephrase and logs a hesitation event. Strictly once per question.
        """
        if not self.state or self.state.state != SessionState.LISTENING or not self.state.current_answer_start:
            return None

        now = current_time or time.time()
        nudge_info = self.nudge_detector.check_nudge(
            answer_start_time=self.state.current_answer_start,
            speech_detected=self.state.current_question_speech_detected,
            has_nudged=self.state.current_question_nudged,
            question=self.state.current_question or {},
            current_time=now,
        )
        if nudge_info:
            self.state.current_question_nudged = True
            self.state.integrity_events.append(nudge_info["hesitation_event"])
            self._persist()
            logger.info(
                "8-second silence rule triggered for session #%d question #%s: sending nudge and logging hesitation event",
                self.session_id,
                nudge_info["question_id"],
            )
            await self.emit_nudge(nudge_info["nudge_text"], reason="silence_8s")
            await self.emit_avatar_speak(nudge_info["nudge_text"])
            return nudge_info
        return None

    async def _finish_answer(self, reason: str = "manual", answer_text: Optional[str] = None) -> None:
        """
        Finalizes candidate's answer for the current question:
        - Stores final transcript with word-level timestamps.
        - Persists artifacts in storage under session_id/question_id.
        - Transitions to EVALUATING state.
        """
        if not self.state or self.state.state != SessionState.LISTENING:
            return

        now = time.time()
        q_id = self.state.current_question.get("id", 1) if self.state.current_question else 1
        final_text = (
            answer_text.strip()
            if answer_text and answer_text.strip()
            else (self.state.current_answer_text or "")
        )
        self.state.current_answer_text = final_text

        # Ensure transcript with word timings is saved
        current_trans = self.stt_service.get_transcript(q_id)
        if not current_trans.get("text") or current_trans.get("text") != final_text:
            current_trans = self.stt_service.append_transcript_text(q_id, final_text)

        await asyncio.to_thread(self.storage_manager.save_transcript, self.session_id, q_id, current_trans)
        self.state.question_transcripts[q_id] = current_trans
        self._persist()
        await self.signal_processor.store.flush()

        # Emit answer_complete event to client if ended automatically via VAD silence
        if reason == "vad_silence":
            await self.emit("answer_complete", {
                "question_id": q_id,
                "finish_reason": reason,
                "text": final_text,
                "word_count": len(current_trans.get("words", [])),
                "timestamp": now,
            })

        # Advance to EVALUATING
        self.transition_to(SessionState.EVALUATING)
        await self.run_state_action()


    # =========================================================================
    # 4. INCOMING CLIENT EVENT DISPATCHER (Client -> Server)
    # =========================================================================

    async def handle_client_event(self, data: Dict[str, Any]) -> None:
        """
        Handles incoming client events:
        - heartbeat
        - answer_started
        - audio_chunk
        - video_frame
        - answer_ended
        - integrity_event
        """
        if not self.state:
            return

        msg_type = data.get("type", "unknown")
        now = time.time()
        if "simulated_time" in data:
            now = float(data["simulated_time"])
        elif "timestamp" in data:
            try:
                client_ts = float(data["timestamp"])
                if client_ts > 1e11:
                    client_ts = client_ts / 1000.0
                if client_ts > now:
                    now = client_ts
            except (ValueError, TypeError):
                pass

        self.state.last_heartbeat = now
        self._persist_throttled()

        # Handle candidate questions during CLOSING / wrap-up
        if self.state.state in (SessionState.CLOSING, SessionState.ENDED) and msg_type in ("answer_ended", "client_query", "candidate_question"):
            query_text = data.get("text", "")
            ans = handle_closing_inquiry(query_text)
            await self.emit_avatar_speak(ans["text"])
            return

        # 1. Heartbeat
        if msg_type == "heartbeat":
            await self.emit("heartbeat_ack", {
                "client_timestamp": data.get("timestamp"),
                "server_timestamp": now,
            })

        # 2. Answer started
        elif msg_type == "answer_started":
            self.state.current_answer_start = now
            self.state.current_question_nudged = False
            self.state.current_question_speech_detected = False
            self.voice_tracker.reset()
            self._persist()

        # 3. Audio chunk
        elif msg_type == "audio_chunk":
            self.state.audio_chunks_received += 1
            chunk_id = data.get("chunk_id", self.state.audio_chunks_received)
            q_id = self.state.current_question.get("id", 1) if self.state.current_question else 1
            chunk_duration = float(data.get("duration", 0.25))
            text_fragment = data.get("text", "").strip()

            # Decode raw audio bytes if base64 or raw
            raw_audio = b""
            if "data" in data and data["data"]:
                try:
                    import base64
                    raw_audio = base64.b64decode(data["data"])
                except (ValueError, TypeError):
                    logger.warning("Session #%d: audio_chunk data is not valid base64; dropping payload", self.session_id)
                    raw_audio = b""
            elif "bytes" in data and isinstance(data["bytes"], bytes):
                raw_audio = data["bytes"]

            if raw_audio:
                await asyncio.to_thread(self.storage_manager.save_audio_chunk, self.session_id, q_id, chunk_id, raw_audio)
                # Parallel Audio Signal Worker (asynchronous with backpressure)
                self.signal_processor.push_audio_chunk(
                    session_id=self.session_id,
                    question_id=q_id,
                    timestamp=now,
                    audio_bytes=raw_audio,
                    duration=chunk_duration,
                    stt_text=text_fragment,
                    calibration=self.calibration,
                )

            # Voice Activity Detection (VAD)
            is_speech_flag = data.get("is_speech")
            is_speech, should_end, silence_dur = self.voice_tracker.feed_audio(
                raw_audio or b"",
                current_time=now,
                chunk_duration_seconds=chunk_duration,
                is_speech=is_speech_flag,
            )

            if is_speech:
                self.state.current_question_speech_detected = True

            # Streaming STT & word-level timestamps
            timed_res = None
            if text_fragment:
                timed_res = self.stt_service.append_transcript_text(q_id, text_fragment)
                self.state.current_answer_text = timed_res["text"]
                await asyncio.to_thread(self.storage_manager.save_transcript, self.session_id, q_id, timed_res)

            self._persist_throttled()
            await self.emit("chunk_ack", {
                "chunk_id": chunk_id,
                "is_speech": is_speech,
                "silence_duration": round(silence_dur, 2),
                "received_at": now,
            })

            # Emit streaming transcript update if requested
            if timed_res and (data.get("stream_transcript") or data.get("streaming")):
                await self.emit("transcript_update", {
                    "question_id": q_id,
                    "text": timed_res["text"],
                    "words": timed_res["words"],
                    "is_partial": True,
                })

            # Automatic end of answer if VAD silence threshold reached after sufficient speech
            if should_end and self.state.state == SessionState.LISTENING:
                logger.info("VAD detected end of answer for session #%d question #%d", self.session_id, q_id)
                await self._finish_answer(reason="vad_silence")
                return

        # 4. Video frame (sent at 1 per second from client)
        elif msg_type == "video_frame":
            self.state.video_frames_received += 1
            frame_id = self.state.video_frames_received
            q_id = self.state.current_question.get("id", 1) if self.state.current_question else 1
            frame_data = data.get("frame") or data.get("data")
            if frame_data:
                await asyncio.to_thread(self.storage_manager.save_video_frame, self.session_id, q_id, frame_id, frame_data)
                # Parallel Video Signal Worker (asynchronous with backpressure)
                self.signal_processor.push_video_frame(
                    session_id=self.session_id,
                    question_id=q_id,
                    timestamp=now,
                    frame_data=frame_data,
                    calibration=self.calibration,
                    on_metrics_callback=self.integrity_monitor.on_video_metrics,
                )
            self._persist_throttled()
            await self.emit("video_frame_ack", {
                "frame_id": frame_id,
                "received_at": now,
            })

        # 5. Integrity event (tab switch, window blur, fullscreen exit, clipboard copy/paste, etc.)
        elif msg_type == "integrity_event":
            event_type = data.get("event_type") or data.get("type", "unknown")
            q_id = data.get("question_id") or (self.state.current_question.get("id") if self.state.current_question else None)
            ts = float(data.get("timestamp", now))
            severity = data.get("severity")
            details = data.get("details", {})
            event_entry = {
                "event_type": event_type,
                "type": event_type,
                "details": details,
                "timestamp": ts,
                "question_id": q_id,
            }
            self.state.integrity_events.append(event_entry)
            self._persist()

            event_dict = await self.integrity_monitor.record_event(
                event_type=event_type,
                question_id=q_id,
                start_time=ts,
                end_time=ts,
                severity=severity,
                details=details,
            )
            summary = self.integrity_monitor.get_integrity_summary()
            await self.emit("integrity_event_ack", {
                "event_id": event_dict.get("id"),
                "event_type": event_type,
                "total_events": summary["total_events"],
                "is_flagged": summary["is_flagged"],
                "received_at": now,
            })
            logger.info("Integrity event recorded for session #%d: %s", self.session_id, event_type)

        # 5.5 Handshake when avatar speech ends: client_ready / ready
        elif msg_type in ("client_ready", "ready"):
            self.state.current_answer_start = now
            self.state.current_question_nudged = False
            self.state.current_question_speech_detected = False
            self.voice_tracker.reset()
            self._persist()
            curr_limit = (
                self.state.current_question.get("time_limit", 120)
                if self.state.current_question
                else 120
            )
            await self.emit("timer_started", {
                "time_limit": curr_limit,
                "started_at": now,
                "question_id": self.state.current_question.get("id") if self.state.current_question else None,
            })

        # 6. Answer ended (manual backup button or timer expiration)
        elif msg_type == "answer_ended":
            raw_text = data.get("text", "").strip()
            await self._finish_answer(reason="manual", answer_text=raw_text)
            return

        # 7. Client keepalive
        elif msg_type == "ping":
            await self.emit("pong", {"timestamp": now})

        else:
            # Unknown types are acknowledged but ignored (non-fatal, so older clients keep working).
            await self.emit("ack", {"original_type": msg_type, "ignored": True, "timestamp": now})

        # Check 8-second silence rule whenever candidate is listening
        if self.state.state == SessionState.LISTENING:
            await self._check_silence_nudge(now)

    # =========================================================================
    # 5. MAIN CONNECTION LIFECYCLE & RESUME LOGIC
    # =========================================================================

    async def _keepalive_loop(self) -> None:
        """Server heartbeat: a 'keepalive' frame every WS_SERVER_PING_SECONDS, independent of
        state actions, so proxies and clients see traffic even during long evaluations."""
        interval = max(1.0, float(settings.WS_SERVER_PING_SECONDS))
        try:
            while self._is_running:
                await asyncio.sleep(interval)
                if not self._is_running:
                    break
                await self.emit("keepalive", {"server_time": time.time()})
        except asyncio.CancelledError:
            pass

    async def start(self, websocket: WebSocket, first_message: Optional[Dict[str, Any]] = None) -> None:
        """
        Accepts the WebSocket connection, checks for reconnection, synchronizes state,
        and enters the main event loop.
        """
        self.ws = websocket
        self._is_running = True
        self._last_tick_time = time.time()
        self.integrity_monitor.set_emit_callback(self.emit)
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        # Load existing state or initialize fresh
        is_reconnect = False
        saved = self.state_store.load_state(self.session_id)
        if saved and saved.state != SessionState.ENDED:
            is_reconnect = True
            self.state = saved
            self.state.is_connected = True
            self.state.last_heartbeat = time.time()
            self.state_store.save_state(self.state)
        else:
            self.state = self._load_or_initialize_state()

        # Send initial handshake/connection frame
        await self.emit("connected", {
            "status": "active",
            "resumed": is_reconnect,
            "state": self.state.state.value,
            "message": "IntervAI live stream connection established.",
            "timestamp": time.time(),
        })

        # If reconnecting, send state_sync and resume active progress
        if is_reconnect:
            await self.emit_state_sync(resumed=True)
            # If reconnect occurs during ASKING or LISTENING, re-surface question so candidate can proceed
            if self.state.state in (SessionState.ASKING, SessionState.LISTENING) and self.state.current_question:
                await self.emit_question(self.state.current_question)
                if self.state.state == SessionState.ASKING:
                    self.transition_to(SessionState.LISTENING)
            elif self.state.state in (SessionState.GREETING, SessionState.WARMUP, SessionState.EVALUATING, SessionState.ROUTING, SessionState.CLOSING):
                await self.run_state_action()
        else:
            # First-time launch -> begin GREETING
            await self.run_state_action()

        # Main receiver loop
        try:
            if first_message is not None:
                await self.handle_client_event(first_message)
            while self._is_running and self.state and self.state.state != SessionState.ENDED:
                try:
                    raw = await asyncio.wait_for(self.ws.receive(), timeout=1.0)
                except asyncio.TimeoutError:
                    if self.state and self.state.state == SessionState.LISTENING:
                        await self._check_silence_nudge()
                    continue

                if "text" in raw and raw["text"]:
                    try:
                        data = json.loads(raw["text"])
                        await self.handle_client_event(data)
                    except json.JSONDecodeError:
                        await self.emit("error", {"code": "invalid_json", "detail": "Invalid JSON frame format"})

                elif "bytes" in raw and raw["bytes"]:
                    self.state.audio_chunks_received += 1
                    raw_bytes = raw["bytes"]
                    q_id = self.state.current_question.get("id", 1) if self.state.current_question else 1
                    await asyncio.to_thread(self.storage_manager.save_audio_chunk, self.session_id, q_id, self.state.audio_chunks_received, raw_bytes)
                    now = time.time()
                    is_speech, should_end, silence_dur = self.voice_tracker.feed_audio(raw_bytes, current_time=now)
                    if is_speech:
                        self.state.current_question_speech_detected = True
                    await self.emit("binary_chunk_ack", {
                        "chunk_id": self.state.audio_chunks_received,
                        "size": len(raw_bytes),
                        "is_speech": is_speech,
                        "received_at": now,
                    })
                    self._persist_throttled()
                    if should_end and self.state.state == SessionState.LISTENING:
                        logger.info("Binary VAD detected silence timeout; ending answer.")
                        await self._finish_answer(reason="vad_silence")


        except (WebSocketDisconnect, RuntimeError):
            logger.info("WebSocket disconnected for session #%d", self.session_id)
        except Exception:
            logger.exception("WebSocket exception for session #%d", self.session_id)
        finally:
            self._is_running = False
            if self._keepalive_task:
                self._keepalive_task.cancel()
            if self.state:
                self.state.is_connected = False
                self._persist()
