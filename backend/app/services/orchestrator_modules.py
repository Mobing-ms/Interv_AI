import time
import logging
from typing import Protocol, Optional, Dict, Any, List, runtime_checkable
from app.services.session_state import SessionStateData
from app.config import settings

logger = logging.getLogger("intervai.orchestrator_modules")


# =============================================================================
# 1. MODULE PROTOCOLS / INTERFACES
# =============================================================================

@runtime_checkable
class QuestionSelectorProtocol(Protocol):
    def get_warmup(self, state: SessionStateData) -> Dict[str, Any]:
        """Returns the initial icebreaker/warm-up question."""
        ...

    def get_next_question(self, state: SessionStateData) -> Optional[Dict[str, Any]]:
        """Selects the next primary question across topics."""
        ...

    def get_follow_up(self, state: SessionStateData, last_eval: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Selects or generates a follow-up probe on the current topic."""
        ...

    def get_closing(self, state: SessionStateData) -> Dict[str, Any]:
        """Returns the closing/wrap-up prompt for the candidate."""
        ...


@runtime_checkable
class TTSModuleProtocol(Protocol):
    def synthesize(self, text: str, voice_style: str = "neutral") -> Dict[str, str]:
        """
        Synthesizes speech audio for avatar text.
        Returns a dict: {"text": text, "audio_url": url_or_data}
        """
        ...


@runtime_checkable
class EvaluatorModuleProtocol(Protocol):
    def evaluate(
        self,
        question: Dict[str, Any],
        answer: str,
        session_context: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Evaluates a candidate's answer and returns scoring, feedback,
        and follow-up indicators.
        """
        ...


@runtime_checkable
class RouterModuleProtocol(Protocol):
    def decide_route(
        self,
        state: SessionStateData,
        last_eval: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Decides the next transition:
        - action: "follow_up" | "next_question" | "close"
        - reason: str
        - topic: Optional[str]
        """
        ...


# =============================================================================
# 2. STUB IMPLEMENTATIONS FOR PHASE 4.1
# =============================================================================

class StubQuestionSelector:
    """
    Stub question selector supplying structured questions per topic,
    with time limits adjusted for normal vs pressure modes.
    """

    DEFAULT_TOPICS = ["DSA", "System Design", "Core CS"]

    def __init__(self, topics: Optional[List[str]] = None, max_questions: int = 3):
        self.topics = topics or list(self.DEFAULT_TOPICS)
        self.max_questions = max_questions
        self._q_counter = 100

    def get_warmup(self, state: SessionStateData) -> Dict[str, Any]:
        time_limit = settings.ORCHESTRATOR_WARMUP_TIME_SECONDS
        if state.mode == "pressure":
            time_limit = max(30, int(time_limit * 0.6))

        return {
            "id": 1,
            "text": "Welcome to your interview. To kick things off, please introduce yourself and highlight a technical project you are proud of.",
            "topic": "Warmup",
            "subtopic": "Introduction",
            "difficulty": "Easy",
            "time_limit": time_limit,
            "is_follow_up": False,
            "expected_keywords": ["project", "role", "technologies", "impact"],
        }

    def get_next_question(self, state: SessionStateData) -> Optional[Dict[str, Any]]:
        # Count main questions asked (excluding warmup)
        asked_main = [c for c in state.session_context if c.get("topic") != "Warmup" and not c.get("is_follow_up", False)]
        if len(asked_main) >= self.max_questions:
            return None

        # Determine topic by round-robin or state
        topic_idx = len(asked_main) % len(self.topics)
        topic = self.topics[topic_idx]

        self._q_counter += 1
        q_id = self._q_counter

        time_limit = (
            settings.ORCHESTRATOR_PRESSURE_QUESTION_TIME_SECONDS
            if state.mode == "pressure"
            else settings.ORCHESTRATOR_QUESTION_TIME_SECONDS
        )

        catalog = {
            "DSA": {
                "text": "How would you design an algorithm to find the longest substring without repeating characters, and what are the time and space complexity trade-offs?",
                "subtopic": "Sliding Window",
                "difficulty": state.difficulty,
                "expected_keywords": ["hash set", "sliding window", "two pointers", "O(N)"],
            },
            "System Design": {
                "text": "Explain how you would architect a horizontally scalable distributed rate limiter supporting 100,000 requests per second.",
                "subtopic": "Distributed Rate Limiting",
                "difficulty": state.difficulty,
                "expected_keywords": ["Redis", "token bucket", "concurrency", "low latency"],
            },
            "Core CS": {
                "text": "Describe the difference between process and thread concurrency, including virtual memory isolation and context switching overhead.",
                "subtopic": "Operating Systems",
                "difficulty": state.difficulty,
                "expected_keywords": ["threads", "virtual memory", "context switch", "CPU cache"],
            },
        }

        q_info = catalog.get(
            topic,
            {
                "text": f"Walk me through your engineering approach for handling high throughput and resiliency in {topic}.",
                "subtopic": "General Engineering",
                "difficulty": state.difficulty,
                "expected_keywords": ["resilience", "throughput", "monitoring"],
            },
        )

        return {
            "id": q_id,
            "text": q_info["text"],
            "topic": topic,
            "subtopic": q_info["subtopic"],
            "difficulty": q_info["difficulty"],
            "time_limit": time_limit,
            "is_follow_up": False,
            "expected_keywords": q_info["expected_keywords"],
        }

    def get_follow_up(self, state: SessionStateData, last_eval: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        curr_q = state.current_question or {}
        topic = curr_q.get("topic", state.topic or "Technical")
        self._q_counter += 1

        time_limit = (
            max(45, int(settings.ORCHESTRATOR_PRESSURE_QUESTION_TIME_SECONDS * 0.8))
            if state.mode == "pressure"
            else 90
        )

        return {
            "id": self._q_counter,
            "text": f"Building on your last point regarding {topic}: What trade-offs or edge cases would occur if traffic spiked 10x suddenly?",
            "topic": topic,
            "subtopic": f"{curr_q.get('subtopic', topic)} Follow-Up",
            "difficulty": "Hard" if state.mode == "pressure" else "Medium",
            "time_limit": time_limit,
            "is_follow_up": True,
            "parent_question_id": curr_q.get("id"),
            "expected_keywords": ["bottleneck", "backpressure", "scaling", "cache invalidation"],
        }

    def get_closing(self, state: SessionStateData) -> Dict[str, Any]:
        return {
            "id": 999,
            "text": "That concludes all our technical sections for today! Thank you for walking through your reasoning and problem-solving.",
            "topic": "Closing",
            "subtopic": "Debrief",
            "difficulty": "Easy",
            "time_limit": 60,
            "is_follow_up": False,
        }


class StubTTS:
    """
    Stub TTS engine generating reproducible simulated avatar audio URLs.
    """

    def synthesize(self, text: str, voice_style: str = "neutral") -> Dict[str, str]:
        short_hash = abs(hash(text)) % 100000
        return {
            "text": text,
            "audio_url": f"/static/tts/avatar_voice_{short_hash}.mp3",
            "voice_style": voice_style,
        }


class StubEvaluator:
    """
    Stub evaluator computing answers based on word count, keyword coverage,
    and returning actionable feedback and score.
    """

    def evaluate(
        self,
        question: Dict[str, Any],
        answer: str,
        session_context: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        words = answer.strip().split()
        word_count = len(words)
        expected_kw = question.get("expected_keywords", [])

        # Count matched keywords
        ans_lower = answer.lower()
        matched = [kw for kw in expected_kw if kw.lower() in ans_lower]
        kw_ratio = len(matched) / max(1, len(expected_kw))

        # Basic score calculation
        if word_count < 5:
            score = 3.5
            feedback = "Answer was very brief. Elaborate on the core mechanism and mention concrete trade-offs."
            follow_up_needed = True
        elif word_count < 20:
            score = 6.5
            feedback = "Good initial outline, but missing detailed implementation caveats and complexity metrics."
            follow_up_needed = True
        else:
            base_score = 7.5 + (kw_ratio * 2.0)
            score = round(min(9.8, max(6.0, base_score)), 1)
            feedback = "Strong technical explanation with clear structural clarity and relevant terminology."
            # Only ask follow-up if score is below 8.5 or follow-up is desired
            follow_up_needed = score < 8.2

        return {
            "score": score,
            "feedback": feedback,
            "key_points_covered": matched if matched else ["general_concept"],
            "word_count": word_count,
            "follow_up_needed": follow_up_needed,
            "evaluated_at": time.time(),
        }


class StubRouter:
    """
    Stub router enforcing max 2 follow-ups per topic, time awareness,
    and smooth topic progression.
    """

    def __init__(self, max_followups_per_topic: int = 2, max_total_questions: int = 3):
        self.max_followups = max_followups_per_topic
        self.max_total_questions = max_total_questions

    def decide_route(
        self,
        state: SessionStateData,
        last_eval: Dict[str, Any],
    ) -> Dict[str, Any]:
        curr_q = state.current_question or {}
        topic = curr_q.get("topic", "General")

        # If warmup just ended -> move to next main question
        if topic == "Warmup":
            return {
                "action": "next_question",
                "reason": "warmup_completed",
                "topic": None,
            }

        # Check follow-up count on current topic
        current_followups = state.follow_up_count_per_topic.get(topic, 0)
        follow_up_needed = last_eval.get("follow_up_needed", False)

        if follow_up_needed and current_followups < self.max_followups:
            return {
                "action": "follow_up",
                "reason": f"topic_probe_{current_followups + 1}",
                "topic": topic,
            }

        # Count total main questions asked
        main_questions_count = len([
            c for c in state.session_context
            if c.get("topic") != "Warmup" and not c.get("is_follow_up", False)
        ])

        if main_questions_count >= self.max_total_questions:
            return {
                "action": "close",
                "reason": "target_questions_reached",
                "topic": None,
            }

        # Check elapsed time
        max_duration_sec = state.duration_minutes * 60
        if state.elapsed_time >= max_duration_sec:
            return {
                "action": "close",
                "reason": "session_duration_exceeded",
                "topic": None,
            }

        # Otherwise continue to next question / topic
        return {
            "action": "next_question",
            "reason": "advance_topic",
            "topic": None,
        }
