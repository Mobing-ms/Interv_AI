import json
import time
import logging
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger("intervai.session_state")


class SessionState(str, Enum):
    GREETING = "GREETING"
    WARMUP = "WARMUP"
    ASKING = "ASKING"
    LISTENING = "LISTENING"
    EVALUATING = "EVALUATING"
    ROUTING = "ROUTING"
    CLOSING = "CLOSING"
    ENDED = "ENDED"
    ERROR = "ERROR"


class SessionStateData(BaseModel):
    session_id: int
    user_id: Optional[int] = None
    interview_id: Optional[int] = None
    state: SessionState = SessionState.GREETING
    previous_state: Optional[SessionState] = None
    current_question: Optional[Dict[str, Any]] = None
    topic: Optional[str] = None
    follow_up_count_per_topic: Dict[str, int] = Field(default_factory=dict)
    elapsed_time: float = 0.0
    session_context: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    last_heartbeat: float = Field(default_factory=time.time)
    error_detail: Optional[str] = None
    mode: str = "normal"  # "normal" or "pressure"
    round_type: str = "Technical"
    difficulty: str = "Medium"
    duration_minutes: int = 30
    total_questions_target: int = 5
    current_answer_start: Optional[float] = None
    current_answer_text: str = ""
    audio_chunks_received: int = 0
    video_frames_received: int = 0
    integrity_events: List[Dict[str, Any]] = Field(default_factory=list)
    user_name: str = "Candidate"
    target_role: str = "Software Engineer"
    language: str = "English"
    pending_followup: Optional[Dict[str, Any]] = None
    is_connected: bool = False
    current_question_nudged: bool = False
    current_question_speech_detected: bool = False
    question_transcripts: Dict[int, Dict[str, Any]] = Field(default_factory=dict)
    question_repeat_count: Dict[str, int] = Field(default_factory=dict)


    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "SessionStateData":
        return cls.model_validate_json(json_str)


class RedisStateStore:
    """
    Manages session state persistence in Redis with automatic fallback to
    in-memory fakeredis when no standalone Redis instance is running.
    """

    def __init__(self, redis_url: Optional[str] = None, client: Optional[Any] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import redis
            r = redis.from_url(self.redis_url, decode_responses=True, socket_connect_timeout=1.0)
            r.ping()
            self._client = r
            logger.info("Connected to Redis at %s", self.redis_url)
        except Exception as e:
            logger.info("Standalone Redis unavailable (%s). Using embedded FakeRedis in-memory store.", e)
            try:
                import fakeredis
                self._client = fakeredis.FakeRedis(decode_responses=True)
            except Exception:
                # Lightweight in-memory dictionary fallback if fakeredis fails
                self._client = _InMemoryDictRedis()
        return self._client

    def _key(self, session_id: int) -> str:
        return f"intervai:session:{session_id}:state"

    def save_state(self, state: SessionStateData, ttl_seconds: int = 7200) -> None:
        """
        Saves or updates full session state in Redis.
        """
        state.updated_at = time.time()
        client = self._get_client()
        key = self._key(state.session_id)
        raw_json = state.to_json()
        client.set(key, raw_json, ex=ttl_seconds)

    def load_state(self, session_id: int) -> Optional[SessionStateData]:
        """
        Retrieves current session state from Redis. Returns None if not found.
        """
        client = self._get_client()
        key = self._key(session_id)
        raw_json = client.get(key)
        if not raw_json:
            return None
        try:
            return SessionStateData.from_json(raw_json)
        except Exception as e:
            logger.error("Failed to deserialize session state for session #%d: %s", session_id, e)
            return None

    def delete_state(self, session_id: int) -> bool:
        """
        Deletes session state key from Redis.
        """
        client = self._get_client()
        key = self._key(session_id)
        return bool(client.delete(key))

    def touch_heartbeat(self, session_id: int) -> float:
        """
        Updates the last heartbeat timestamp for the session state.
        """
        state = self.load_state(session_id)
        now = time.time()
        if state:
            state.last_heartbeat = now
            state.updated_at = now
            self.save_state(state)
        return now

    def get_last_heartbeat(self, session_id: int) -> Optional[float]:
        state = self.load_state(session_id)
        return state.last_heartbeat if state else None


class _InMemoryDictRedis:
    """Lightweight in-memory fallback mimicking basic Redis string key-value operations."""

    def __init__(self):
        self._store: Dict[str, str] = {}
        self._expirations: Dict[str, float] = {}

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        self._store[key] = value
        if ex:
            self._expirations[key] = time.time() + ex
        elif key in self._expirations:
            del self._expirations[key]
        return True

    def get(self, key: str) -> Optional[str]:
        if key in self._expirations and time.time() > self._expirations[key]:
            del self._store[key]
            del self._expirations[key]
            return None
        return self._store.get(key)

    def delete(self, key: str) -> int:
        existed = key in self._store
        self._store.pop(key, None)
        self._expirations.pop(key, None)
        return 1 if existed else 0


default_state_store = RedisStateStore()
