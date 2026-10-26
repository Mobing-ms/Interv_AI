"""
Router Service (Phase 4.4).
Pure router decision logic directing interview flow based on candidate answer evaluations:
- WEAK_VAGUE -> Probing follow-up on same topic (strictly max 2 per topic).
- STRONG -> Raise difficulty or go deeper in same topic.
- Topic done -> Advance to next topic in blueprint.
- OFF_TOPIC -> Polite redirect and repeat question once.
- Round done -> Check time up, question target, or topic coverage, and transition to closing.
"""

import re
import time
import random
import logging
from typing import Dict, Any, List, Optional
from app.services.session_state import SessionStateData
from app.services.orchestrator_modules import RouterModuleProtocol
from pydantic import BaseModel, Field
from app.prompts.evaluation_rubric import PROBING_FOLLOW_UP_PROMPT_TEMPLATE
from app.services.llm import llm_service

logger = logging.getLogger("intervai.router")

MAX_FOLLOWUPS_PER_TOPIC = 2
# Not every answer gets a follow-up: vague answers always do (up to the cap); otherwise
# a partial answer is probed half the time and a strong one is pushed deeper about a third of the time.
OK_FOLLOW_UP_RATE = 0.5
SHORT_ANSWER_WORDS = 20
# {subject} is the question's subtopic or topic, so the probe stays tied to what was asked.
SHORT_ANSWER_PROBES = [
    "No problem, let's simplify it. Thinking about {subject}, what is the very first thing you would look at, and why?",
    "That's fine. If you had to start somewhere with {subject}, which part would you tackle first?",
    "Let's make it concrete. Have you come across {subject} anywhere, even in a small project or a course? Walk me through what you did.",
]
STRONG_FOLLOW_UP_RATE = 0.35


# =============================================================================
# 1. HELPER CHECKERS (PURE FUNCTIONS)
# =============================================================================

def _distinct_main(session_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Main questions (no warm-up, closing or follow-ups), once each: a repeated question counts once."""
    seen, out = set(), []
    for c in session_context:
        if c.get("topic") in ("Warmup", "Closing") or c.get("is_follow_up", False):
            continue
        key = c.get("question_id") if c.get("question_id") is not None else c.get("question")
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def count_topic_main_questions(session_context: List[Dict[str, Any]], topic: str) -> int:
    """Counts main questions asked for a given topic (excluding follow-ups and warmup)."""
    return len([c for c in _distinct_main(session_context) if c.get("topic") == topic])


def count_all_main_questions(session_context: List[Dict[str, Any]]) -> int:
    """Counts total main domain questions asked across all topics."""
    return len(_distinct_main(session_context))


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
    subtopic = question.get("subtopic") or topic
    q_id = int(time.time() * 1000) % 1000000

    # Deterministic fallback, used when the LLM is unavailable: neutral and tied to the gap.
    gap_l = gap.lower()
    if "metric" in gap_l or "result" in gap_l or "impact" in gap_l:
        text = "What was the measurable outcome of that, and how did you know it worked?"
    elif "trade-off" in gap_l or "tradeoff" in gap_l or "complexity" in gap_l:
        text = "What alternatives did you consider there, and why did you choose this approach over them?"
    elif "example" in gap_l or "specific" in gap_l or "vague" in gap_l:
        text = "Can you walk me through a specific example of that, step by step?"
    else:
        # Never echo `gap`: it is the evaluator's note to the interviewer, not candidate-facing text.
        text = "Can you make that more concrete? Walk me through a specific example from your own work."

    return {
        "id": q_id,
        "text": text,
        "topic": topic,
        "subtopic": subtopic,
        "difficulty": question.get("difficulty", "Medium"),
        "time_limit": max(45, int(question.get("time_limit", 90) * 0.75)),
        "is_follow_up": True,
        "parent_question_id": question.get("id"),
        "expected_keywords": evaluation.get("keyword_coverage", {}).get("missing", ["trade-offs", "scaling"]),
    }


class FollowUpPayload(BaseModel):
    text: str
    expected_keywords: List[str] = Field(default_factory=list)


async def generate_follow_up_async(
    question: Dict[str, Any],
    evaluation: Dict[str, Any],
    topic: str,
    reason: str = "probe_gap",
    session_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Writes a follow-up that builds on what the candidate actually said.
    reason: "probe_gap" (answer was vague or partial) or "go_deeper" (answer was strong).
    Falls back to generate_probing_follow_up when the LLM is unavailable or returns nothing usable.
    """
    fallback = generate_probing_follow_up(question, evaluation, topic)
    answer = (evaluation.get("answer") or "").strip()
    if len(answer.split()) < SHORT_ANSWER_WORDS:
        # Nothing substantial to build on; an LLM here tends to invent things the candidate
        # "mentioned". Ask for a first concrete step instead.
        subject = question.get("subtopic") or topic or "this"
        if subject in ("Warmup", "General", "Introduction"):
            subject = "this"
        fallback["text"] = SHORT_ANSWER_PROBES[len(answer) % len(SHORT_ANSWER_PROBES)].format(subject=subject)
        return fallback
    if not llm_service.is_active():
        return fallback

    gap = evaluation.get("follow_up_gap") or "the reasoning behind the approach"
    aim = (
        f"The answer was incomplete. Probe this gap: {gap}."
        if reason == "probe_gap"
        else "The answer was solid. Push one level deeper on the most interesting thing they said: "
             "a failure mode, a scaling limit, a trade-off or what they would do differently."
    )
    prompt = f"""You are a senior interviewer in a live {topic} interview.

Your previous question: {question.get('text', '')}
Candidate's answer: {answer[:1500]}

{aim}

Write ONE follow-up question that refers to something specific the candidate said (quote or name it).
One or two sentences, professional and neutral, as you would say it out loud. No praise, no preamble
("Great answer", "Thanks for sharing"), no new unrelated topic. Do not list the points a good answer
should cover; that gives the answer away. If the candidate said little, ask them to start from one
concrete step or example.

Return JSON {{"text": "...", "expected_keywords": ["...", "..."]}}"""
    try:
        res = await llm_service.generate_structured_async(prompt=prompt, response_schema=FollowUpPayload)
    except Exception as e:
        logger.warning("Follow-up generation failed (%s); using fallback", type(e).__name__)
        return fallback
    text = (res.text if res else "").strip()
    if len(text) < 15 or len(text) > 400:
        return fallback
    fallback["text"] = text
    if res.expected_keywords:
        fallback["expected_keywords"] = res.expected_keywords[:8]
    fallback["subtopic"] = f"{question.get('subtopic') or topic} Follow-Up"
    return fallback


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

    # A short non-answer ("I'm not sure", "someone else did it") is weak, not off-topic:
    # probe it instead of asking the candidate to "refocus".
    if classification == "OFF_TOPIC":
        words = last_eval.get("word_count")
        if words is None and last_eval.get("answer"):
            words = len(str(last_eval["answer"]).split())
        if words is not None and words < SHORT_ANSWER_WORDS:
            classification = "WEAK_VAGUE"

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
                # Spoken just before the question is asked again, so it must not contain the question itself
                "redirect_message": "I don't think that quite answers it. Let me ask again.",
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
        # A follow-up that still got a vague answer: move on rather than press again.
        if curr_q.get("is_follow_up"):
            current_fu = MAX_FOLLOWUPS_PER_TOPIC
        if current_fu < MAX_FOLLOWUPS_PER_TOPIC:
            return {
                "action": "follow_up",
                "reason": f"probing_follow_up_{current_fu + 1}",
                "topic": topic,
                "follow_up_reason": "probe_gap",
                "difficulty_adjustment": "maintain",
                "repeat_question": False,
                "redirect_message": None,
                "follow_up_gap": last_eval.get("follow_up_gap", "elaborate on mechanisms"),
                "round_done": False,
            }
        else:
            logger.info("Topic %s reached max follow-ups (%d); advancing topic.", topic, MAX_FOLLOWUPS_PER_TOPIC)
            # Advance to next topic or check if topic is done

    # 5. Optional follow-up on a satisfactory or strong main answer (never chained off a follow-up)
    if (
        classification in ("OK", "STRONG")
        and not curr_q.get("is_follow_up")
        and state.follow_up_count_per_topic.get(topic, 0) == 0
    ):
        rate = STRONG_FOLLOW_UP_RATE if classification == "STRONG" else OK_FOLLOW_UP_RATE
        if random.random() < rate:
            return {
                "action": "follow_up",
                "reason": "strong_go_deeper" if classification == "STRONG" else "partial_probe",
                "follow_up_reason": "go_deeper" if classification == "STRONG" else "probe_gap",
                "topic": topic,
                "difficulty_adjustment": "maintain",
                "repeat_question": False,
                "redirect_message": None,
                "follow_up_gap": last_eval.get("follow_up_gap"),
                "round_done": False,
            }

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
    no_questions = not query_norm or (
        "?" not in query_norm
        and any(re.search(rf"\b{p}\b", query_norm) for p in ["no", "none", "nothing", "all good", "i'm good", "nope", "that's all"])
    )
    if no_questions:
        response = "Thank you for your time today. That's the end of the interview, and your report will be ready shortly."
    else:
        response = (
            "That's a good question to ask, and in a real interview it shows genuine interest in the role. "
            "The interviewer's answer will depend on the company, so note it down for the real thing. "
            "Thank you for your time today. Your report will be ready shortly."
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
