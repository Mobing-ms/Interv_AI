from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.models import User, UserMemory, AskedQuestion, TargetProfile, Profile
from app.schemas import UserContextOut, AskedQuestionOut


DEFAULT_BASELINE_WEIGHTS = {
    "Problem solving": 0.25,
    "Architecture & design": 0.25,
    "Communication": 0.25,
    "Execution & clarity": 0.25,
}

MODE_PRESETS = {
    "normal": {
        "answer_timer_seconds": 120,
        "probing_intensity": "standard",
        "max_followups_per_topic": 2,
        "time_pressure_warning_seconds": 30,
        "description": "Standard pacing with 120s answer limit and supportive follow-up probing.",
    },
    "pressure": {
        "answer_timer_seconds": 60,
        "probing_intensity": "high",
        "max_followups_per_topic": 3,
        "time_pressure_warning_seconds": 15,
        "interruption_bias": True,
        "description": "High-intensity pressure mode with rapid 60s timer and aggressive follow-up challenges.",
    },
}


def ensure_user_memory_updated(user_id: int, db: Session) -> None:
    """
    Ensures that any completed/closed interview sessions for this user have had their
    score fusion and memory persistence executed before loading user context or building blueprints.
    """
    from app.models import InterviewSession, SessionResult
    from app.services.score_fusion_service import process_and_persist_session_result

    # Find closed sessions that lack a SessionResult record
    unprocessed_sessions = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.user_id == user_id,
            InterviewSession.status.in_(["closed", "CLOSED", "completed"]),
        )
        .order_by(InterviewSession.created_at.desc())
        .all()
    )

    for sess in unprocessed_sessions:
        has_result = db.query(SessionResult).filter(SessionResult.session_id == sess.id).first() is not None
        if not has_result:
            try:
                process_and_persist_session_result(session_id=sess.id, db=db)
            except Exception:
                pass


def load_user_context(user_id: int, db: Session) -> UserContextOut:
    """
    Returns the user's interview context:
    - is_returning: bool
    - past_scores: per-topic average score
    - weak_areas: list of weak-topic tags
    - history_asked_questions: previously asked questions
    - baseline_weights: equal weights for new users, weak-area boosted for returning users
    - recommended settings and mode presets
    """
    ensure_user_memory_updated(user_id, db)

    memory: Optional[UserMemory] = db.query(UserMemory).filter(UserMemory.user_id == user_id).first()
    asked_questions_rows: List[AskedQuestion] = (
        db.query(AskedQuestion)
        .filter(AskedQuestion.user_id == user_id)
        .order_by(AskedQuestion.asked_at.desc())
        .all()
    )

    is_returning = memory is not None and memory.session_count > 0

    if not is_returning:
        # New user: return default baseline weights and medium difficulty start
        return UserContextOut(
            is_returning=False,
            session_count=0,
            last_session_at=None,
            past_scores={},
            weak_areas=[],
            history_asked_questions=[],
            baseline_weights=DEFAULT_BASELINE_WEIGHTS,
            recommended_difficulty="Medium",
            recommended_round="Technical",
            recommended_duration=30,
            mode_presets=MODE_PRESETS,
        )

    # Returning candidate: load scores, weak areas, and question history
    past_scores = dict(memory.topic_scores) if memory.topic_scores else {}
    weak_areas = list(memory.weak_topics) if memory.weak_topics else []

    history_questions = [
        AskedQuestionOut(
            id=q.id,
            question_hash=q.question_hash,
            topic=q.topic,
            question_text=q.question_text,
            asked_at=q.asked_at,
            score=q.score,
        )
        for q in asked_questions_rows
    ]

    # Calculate tailored weights prioritizing weak areas
    computed_weights = {}
    if weak_areas:
        # Boost weight on weak areas (e.g. 50% split evenly among weak areas, 50% across general)
        weak_portion = 0.55 / len(weak_areas)
        for w in weak_areas:
            computed_weights[w] = round(weak_portion, 3)

        general_keys = [k for k in DEFAULT_BASELINE_WEIGHTS if k not in weak_areas]
        if general_keys:
            gen_portion = (1.0 - 0.55) / len(general_keys)
            for g in general_keys:
                computed_weights[g] = round(gen_portion, 3)
    else:
        computed_weights = dict(DEFAULT_BASELINE_WEIGHTS)

    # Normalize weights to sum exactly to 1.0
    total_w = sum(computed_weights.values())
    if total_w > 0:
        computed_weights = {k: round(v / total_w, 3) for k, v in computed_weights.items()}

    # Recommend difficulty based on average past score
    if past_scores:
        avg_score = sum(past_scores.values()) / len(past_scores)
        if avg_score >= 82:
            rec_difficulty = "Hard"
        elif avg_score >= 70:
            rec_difficulty = "Adaptive"
        elif avg_score < 55:
            rec_difficulty = "Easy"
        else:
            rec_difficulty = "Medium"
    else:
        rec_difficulty = "Adaptive"

    return UserContextOut(
        is_returning=True,
        session_count=memory.session_count,
        last_session_at=memory.last_session_at,
        past_scores=past_scores,
        weak_areas=weak_areas,
        history_asked_questions=history_questions,
        baseline_weights=computed_weights,
        recommended_difficulty=rec_difficulty,
        recommended_round="Technical",
        recommended_duration=30,
        mode_presets=MODE_PRESETS,
    )
