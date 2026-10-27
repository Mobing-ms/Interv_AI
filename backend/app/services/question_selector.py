import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("intervai.question_selector")


def select_next_question(
    question_pool: List[Dict[str, Any]],
    blueprint: Dict[str, Any],
    session_context: List[Dict[str, Any]],
    pending_followup: Optional[Dict[str, Any]] = None,
    current_difficulty: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Selects the next interview question according to blueprint topic weights,
    difficulty level, and candidate CV items, strictly avoiding repeats.

    Args:
        question_pool: Seed pool of candidate questions.
        blueprint: Interview blueprint with topics, weights, and difficulty curve.
        session_context: Prior asked questions and answers in this session.
        pending_followup: Pending follow-up question probe if one was routed.
        current_difficulty: Target difficulty level (Easy, Medium, Hard, Adaptive).

    Returns:
        Selected question dict or None if pool is exhausted.
    """
    # 1. If a follow-up is pending from evaluator/router, return it immediately
    if pending_followup:
        return pending_followup

    if not question_pool:
        return None

    # 2. Identify all already asked questions to strictly prevent repeats
    asked_ids = set()
    asked_texts = set()
    topic_counts: Dict[str, int] = {}
    main_asked_count = 0
    last_main_was_cv: Optional[bool] = None

    for item in session_context:
        q_id = item.get("question_id")
        if q_id is not None:
            if q_id in asked_ids:
                continue  # a repeated (redirected) question counts once
            asked_ids.add(q_id)

        q_text = item.get("question", "").strip().lower()
        if q_text:
            asked_texts.add(q_text)

        topic = item.get("topic")
        is_followup = item.get("is_follow_up", False)
        # Only count main domain questions toward topic quotas (exclude Warmup & Closing)
        if topic and topic not in ("Warmup", "Closing") and not is_followup:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
            main_asked_count += 1
            last_main_was_cv = bool(item.get("is_cv_based"))

    # 3. Filter question pool to unasked candidates
    available_questions = [
        q for q in question_pool
        if q.get("id") not in asked_ids
        and q.get("text", "").strip().lower() not in asked_texts
    ]

    if not available_questions:
        logger.info("Question pool exhausted for session.")
        return None

    # 4. Parse blueprint topics and weights
    bp_topics = blueprint.get("topics", [])
    topic_weights: Dict[str, float] = {}
    total_weight = 0.0

    for t in bp_topics:
        t_name = t.get("name") or t.get("topic") or "General"
        t_weight = float(t.get("weight", 1.0))
        topic_weights[t_name] = t_weight
        total_weight += t_weight

    # Normalize topic weights
    if total_weight > 0:
        for t_name in topic_weights:
            topic_weights[t_name] /= total_weight
    else:
        topic_weights = {"General": 1.0}

    # 5. Determine target difficulty
    if not current_difficulty:
        diff_curve = blueprint.get("difficulty_curve", [])
        if isinstance(diff_curve, list) and diff_curve:
            turn_idx = min(main_asked_count, len(diff_curve) - 1)
            target_diff = diff_curve[turn_idx]
        elif isinstance(diff_curve, str) and diff_curve:
            target_diff = diff_curve
        else:
            target_diff = "Medium"
    else:
        target_diff = current_difficulty

    # 6. Rank each candidate question
    # Score factors:
    # - Topic deficit score (higher weight topic with fewest questions asked)
    # - CV preference (+25 points if grounded in candidate CV)
    # - Difficulty match (+15 points if matches target difficulty)
    scored_candidates = []

    for q in available_questions:
        q_topic = q.get("topic", "General")
        expected_share = topic_weights.get(q_topic, 0.1)
        actual_share = (topic_counts.get(q_topic, 0) / max(1, main_asked_count))
        topic_deficit = expected_share - actual_share

        score = topic_deficit * 100.0

        # Prefer CV-based questions when topic fits
        # Open with a CV question, then alternate CV and topic questions.
        is_cv = bool(q.get("is_cv_based") or q.get("based_on_cv_item"))
        if is_cv and last_main_was_cv is not True:
            score += 25.0
        elif is_cv and last_main_was_cv:
            score -= 60.0  # strong enough to beat topic weighting, so topic questions get their turn

        # Match difficulty level
        q_diff = q.get("difficulty", "Medium")
        if q_diff.lower() == target_diff.lower():
            score += 15.0
        elif target_diff.lower() == "adaptive":
            score += 10.0

        scored_candidates.append((score, q))

    # Sort descending by score
    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    selected = scored_candidates[0][1]

    return selected


class QuestionSelectorService:
    """
    Service wrapper around question selection logic with default seed pools
    and warm-up/closing prompts.
    """

    def __init__(self, question_pool: Optional[List[Dict[str, Any]]] = None):
        self.question_pool = question_pool or []

    def get_warmup_question(self, user_name: str = "Candidate", target_role: str = "Software Engineer", time_limit: int = 60) -> Dict[str, Any]:
        """
        Rule 1: The first question is always 'Tell me about yourself'.
        """
        return {
            "id": 1,
            "text": "Tell me about yourself, your background, and what drew you to this role.",
            "topic": "Warmup",
            "subtopic": "Introduction",
            "difficulty": "Easy",
            "time_limit": time_limit,
            "is_follow_up": False,
            "expected_keywords": ["experience", "projects", "background", "role", "technologies"],
        }

    def get_closing_question(self) -> Dict[str, Any]:
        return {
            "id": 999,
            "text": "That concludes all our technical questions for today! Do you have any questions for me about the role, team, or technologies?",
            "topic": "Closing",
            "subtopic": "Candidate Questions",
            "difficulty": "Easy",
            "time_limit": 60,
            "is_follow_up": False,
        }

    def select_next(
        self,
        blueprint: Dict[str, Any],
        session_context: List[Dict[str, Any]],
        pending_followup: Optional[Dict[str, Any]] = None,
        current_difficulty: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return select_next_question(
            question_pool=self.question_pool,
            blueprint=blueprint,
            session_context=session_context,
            pending_followup=pending_followup,
            current_difficulty=current_difficulty,
        )
