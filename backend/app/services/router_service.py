"""
Router Service (Phase 4.4).
Pure router decision logic directing interview flow based on candidate answer evaluations:
- WEAK_VAGUE -> Probing follow-up on same topic (strictly max 2 per topic).
- STRONG -> Raise difficulty or go deeper in same topic.
- Topic done -> Advance to next topic in blueprint.
- OFF_TOPIC -> Polite redirect and repeat question once.
- Round done -> Check time up, question target, or topic coverage, and transition to closing.
"""

import time
import logging
from typing import Dict, Any, List, Optional
from app.services.session_state import SessionStateData
from app.services.orchestrator_modules import RouterModuleProtocol
from app.prompts.evaluation_rubric import PROBING_FOLLOW_UP_PROMPT_TEMPLATE

logger = logging.getLogger("intervai.router")

MAX_FOLLOWUPS_PER_TOPIC = 2


# =============================================================================
# 1. HELPER CHECKERS (PURE FUNCTIONS)
# =============================================================================

def count_topic_main_questions(session_context: List[Dict[str, Any]], topic: str) -> int:
    """Counts main questions asked for a given topic (excluding follow-ups and warmup)."""
    return len([
        c for c in session_context
        if c.get("topic") == topic
        and not c.get("is_follow_up", False)
        and c.get("topic") != "Warmup"
    ])


def count_all_main_questions(session_context: List[Dict[str, Any]]) -> int:
    """Counts total main domain questions asked across all topics."""
    return len([
        c for c in session_context
        if c.get("topic") not in ("Warmup", "Closing")
        and not c.get("is_follow_up", False)
    ])


def is_topic_done(
    state: SessionStateData,
    topic: str,
    blueprint: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Determines if a topic has fulfilled its blueprint allocation.
    """
    if not topic or topic in ("Warmup", "Closing"):
        return True

    topic_asked = count_topic_main_questions(state.session_context, topic)

    if blueprint and "topics" in blueprint:
        bp_topics = blueprint["topics"]
        total_questions = blueprint.get("total_questions", state.total_questions_target or 5)
        # Find target for this topic based on weight
        matching = [t for t in bp_topics if (t.get("name") or t.get("topic")) == topic]
        if matching:
            weight = float(matching[0].get("weight", 1.0))
            total_weight = sum(float(t.get("weight", 1.0)) for t in bp_topics) or 1.0
            allocated = max(1, round((weight / total_weight) * total_questions))
            return topic_asked >= allocated

    # Default fallback: 1 main question per topic if not explicitly specified
    return topic_asked >= 1


def is_round_done(
    state: SessionStateData,
    blueprint: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Checks if the entire interview round is completed:
    1. Time is up (elapsed_time >= duration_minutes * 60).
    2. Total target questions reached.
    3. All topics in blueprint completed.
    """
    # 1. Time limit check
    max_duration_sec = state.duration_minutes * 60
    if state.elapsed_time >= max_duration_sec:
        logger.info("Round done: elapsed time (%.1fs) reached limit (%.1fs)", state.elapsed_time, max_duration_sec)
        return True

    # 2. Total question count check
    target_questions = (
        blueprint.get("total_questions")
        if blueprint and "total_questions" in blueprint
        else 3
    )
    main_asked = count_all_main_questions(state.session_context)
    if main_asked >= target_questions:
        logger.info("Round done: main questions asked (%d) reached target (%d)", main_asked, target_questions)
        return True

    # 3. Topic coverage check
    if blueprint and "topics" in blueprint:
        bp_topics = [t.get("name") or t.get("topic") for t in blueprint["topics"] if (t.get("name") or t.get("topic"))]
        if bp_topics:
            all_topics_covered = all(is_topic_done(state, t, blueprint) for t in bp_topics)
            if all_topics_covered:
                logger.info("Round done: all blueprint topics completed")
                return True

    return False


# =============================================================================
# 2. PROBING FOLLOW-UP GENERATOR
# =============================================================================

def generate_probing_follow_up(
    question: Dict[str, Any],
    evaluation: Dict[str, Any],
    topic: str,
) -> Dict[str, Any]:
    """
    Generates a targeted probing follow-up based on the specific gap in the answer.
    """
    gap = evaluation.get("follow_up_gap") or "Explain the internal mechanics and edge cases."
    parent_q_text = question.get("text", "")
    subtopic = question.get("subtopic", topic)
    q_id = int(time.time() * 1000) % 1000000

    # Deterministic contextual follow-up templates by topic & gap
    if "metrics" in gap.lower() or "result" in gap.lower():
        text = f"Could you dive deeper into the measurable results and specific metrics that came out of your actions in {subtopic}?"
    elif "edge case" in gap.lower() or "bottleneck" in gap.lower():
        text = f"Building on your thoughts regarding {subtopic}: What specific edge cases or bottlenecks would occur if traffic or load spiked 10x suddenly?"
    elif "trade-off" in gap.lower() or "complexity" in gap.lower():
        text = f"You touched on {subtopic}. What are the primary time/space complexity trade-offs with that approach, and how would you optimize it further?"
    else:
        text = f"Could you elaborate on the underlying mechanism for {subtopic}, specifically regarding {gap}?"

    return {
        "id": q_id,
        "text": text,
        "topic": topic,
        "subtopic": f"{subtopic} Probing",
        "difficulty": question.get("difficulty", "Medium"),
        "time_limit": max(45, int(question.get("time_limit", 90) * 0.75)),
        "is_follow_up": True,
        "parent_question_id": question.get("id"),
        "expected_keywords": evaluation.get("keyword_coverage", {}).get("missing", ["trade-offs", "scaling"]),
    }


# =============================================================================
# 3. PURE ROUTER DECISION FUNCTION
# =============================================================================

def decide_route(
    state: SessionStateData,
    last_eval: Dict[str, Any],
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Pure testable function implementing router decision logic:
    - WEAK_VAGUE -> probing follow-up on same topic (strictly max 2 per topic).
    - STRONG -> raise difficulty or go deeper in same topic.
    - Topic done -> next topic in blueprint.
    - OFF_TOPIC -> redirect politely and repeat question once.
    - After routing -> check "round done?" (time up, question target, topic coverage).

    Returns:
        {
            "action": "redirect" | "follow_up" | "next_question" | "close",
            "reason": str,
            "topic": Optional[str],
            "difficulty_adjustment": Optional[str], # "raise" | "maintain" | "lower"
            "repeat_question": bool,
            "redirect_message": Optional[str],
            "follow_up_gap": Optional[str],
            "round_done": bool,
        }
    """
    curr_q = state.current_question or {}
    topic = curr_q.get("topic") or state.topic or "General"
    q_id_str = str(curr_q.get("id", "current"))

    # 1. Warmup transition
    if topic == "Warmup" or curr_q.get("subtopic") == "Introduction":
        return {
            "action": "next_question",
            "reason": "warmup_completed",
            "topic": None,
            "difficulty_adjustment": "maintain",
            "repeat_question": False,
            "redirect_message": None,
            "follow_up_gap": None,
            "round_done": False,
        }

    # 2. Check if round is already complete
    if is_round_done(state, blueprint):
        return {
            "action": "close",
            "reason": "round_target_or_time_completed",
            "topic": None,
            "difficulty_adjustment": "maintain",
            "repeat_question": False,
            "redirect_message": None,
            "follow_up_gap": None,
            "round_done": True,
        }

    classification = str(last_eval.get("classification", "OK")).upper()

    # 3. OFF_TOPIC -> Redirect politely and repeat question once
    if classification == "OFF_TOPIC":
        repeat_count = state.question_repeat_count.get(q_id_str, 0)
        if repeat_count == 0:
            return {
                "action": "redirect",
                "reason": "off_topic_redirect",
                "topic": topic,
                "difficulty_adjustment": "maintain",
                "repeat_question": True,
                "redirect_message": (
                    f"Let's refocus on the question asked: {curr_q.get('text', 'Please address the prompt directly.')}"
                ),
                "follow_up_gap": last_eval.get("follow_up_gap"),
                "round_done": False,
            }
        else:
            # Already redirected once for this question; move forward to avoid stalling
            logger.info("Question %s already repeated once for OFF_TOPIC; advancing.", q_id_str)
            classification = "WEAK_VAGUE"  # Treat as weak and proceed to standard flow

    # 4. WEAK_VAGUE -> Probing follow-up on the same topic (strictly max 2 per topic)
    if classification == "WEAK_VAGUE":
        current_fu = state.follow_up_count_per_topic.get(topic, 0)
        if current_fu < MAX_FOLLOWUPS_PER_TOPIC:
            return {
                "action": "follow_up",
                "reason": f"probing_follow_up_{current_fu + 1}",
                "topic": topic,
                "difficulty_adjustment": "maintain",
                "repeat_question": False,
                "redirect_message": None,
                "follow_up_gap": last_eval.get("follow_up_gap", "elaborate on mechanisms"),
                "round_done": False,
            }
        else:
            logger.info("Topic %s reached max follow-ups (%d); advancing topic.", topic, MAX_FOLLOWUPS_PER_TOPIC)
            # Advance to next topic or check if topic is done

    # 5. STRONG -> Raise difficulty or go deeper in the same topic
    if classification == "STRONG":
        topic_finished = is_topic_done(state, topic, blueprint)
        if not topic_finished:
            return {
                "action": "next_question",
                "reason": "strong_deepen_topic",
                "topic": topic,
                "difficulty_adjustment": "raise",
                "repeat_question": False,
                "redirect_message": None,
                "follow_up_gap": None,
                "round_done": False,
            }
        else:
            return {
                "action": "next_question",
                "reason": "topic_completed_strong",
                "topic": None,
                "difficulty_adjustment": "raise",
                "repeat_question": False,
                "redirect_message": None,
                "follow_up_gap": None,
                "round_done": False,
            }

    # 6. OK (Satisfactory) or WEAK with follow-up limit exceeded
    topic_finished = is_topic_done(state, topic, blueprint)
    if topic_finished:
        return {
            "action": "next_question",
            "reason": "topic_completed",
            "topic": None,
            "difficulty_adjustment": "maintain",
            "repeat_question": False,
            "redirect_message": None,
            "follow_up_gap": None,
            "round_done": False,
        }
    else:
        return {
            "action": "next_question",
            "reason": "topic_continue",
            "topic": topic,
            "difficulty_adjustment": "maintain",
            "repeat_question": False,
            "redirect_message": None,
            "follow_up_gap": None,
            "round_done": False,
        }


# =============================================================================
# 4. CLOSING INTERACTIVE HANDLER
# =============================================================================

def handle_closing_inquiry(candidate_query: str) -> Dict[str, str]:
    """
    Handles candidate questions during the closing wrap-up ("Any questions for us?").
    Returns an informative answer plus thank-you.
    """
    query_norm = candidate_query.strip().lower()

    if not query_norm or any(p in query_norm for p in ["no", "none", "all good", "nothing", "i'm good", "nope"]):
        response = (
            "Thank you so much for your time and thoughtful responses today! "
            "We enjoyed walking through your experience. Our team will review your session and be in touch soon with next steps."
        )
    elif "culture" in query_norm or "team" in query_norm:
        response = (
            "Great question! Our engineering culture is highly collaborative, emphasizing ownership, continuous learning, "
            "and transparent architectural discussions. We value curiosity and practical impact. "
            "Thank you again for interviewing with us today, and best of luck!"
        )
    elif "stack" in query_norm or "tech" in query_norm:
        response = (
            "We build modern distributed microservices utilizing FastAPI, TypeScript, React, and Redis, focusing heavily "
            "on low latency and resilient real-time streaming architectures. "
            "Thank you for asking, and thank you again for your time today!"
        )
    else:
        response = (
            f"Thank you for asking about that! We prioritize open communication and impactful engineering excellence. "
            "Thank you again for walking through your experience today. We will be in touch with next steps soon!"
        )

    return {
        "text": response,
        "is_closing_complete": True,
    }


# =============================================================================
# 5. ROUTER SERVICE CLASS
# =============================================================================

class RouterService(RouterModuleProtocol):
    """
    RouterModuleProtocol implementation wrapping decide_route.
    """

    def __init__(self, blueprint: Optional[Dict[str, Any]] = None):
        self.blueprint = blueprint

    def decide_route(
        self,
        state: SessionStateData,
        last_eval: Dict[str, Any],
    ) -> Dict[str, Any]:
        return decide_route(state, last_eval, self.blueprint)
