"""
Builds an interview's question pool and stores it in the QuestionBank.
Shared by POST /interview/{id}/questions/generate and the live session, which
generates the pool on start if the client never asked for it.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import InterviewConfig, Profile, TargetProfile, EducationProfile, QuestionBankItem
from app.schemas import InterviewBlueprint
from app.services.interview_context import load_user_context
from app.services.interview_blueprint import build_interview_blueprint
from app.services.question_generator import generate_question_pool_async

logger = logging.getLogger("intervai.question_pool_store")


def _bank_item(interview_id: int, q: Dict[str, Any], reserve: bool, now: datetime) -> QuestionBankItem:
    return QuestionBankItem(
        interview_id=interview_id,
        question_hash=q["question_hash"],
        text=q["text"],
        topic=q["topic"],
        subtopic=q.get("subtopic"),
        difficulty=q.get("difficulty", "Medium"),
        question_type=q.get("question_type", "conceptual"),
        expected_keywords=q.get("expected_keywords") or [],
        ideal_answer_points=q.get("ideal_answer_points") or [],
        max_time_seconds=q.get("max_time_seconds", 120),
        cv_reference=q.get("cv_reference"),
        is_weak_area=q.get("is_weak_area", False),
        rank_score=q.get("rank_score", 0.0),
        is_reserve_followup=reserve,
        followup_templates=q.get("followup_templates") or [],
        created_at=now,
    )


async def build_question_pool(
    db: Session,
    interview: InterviewConfig,
    user_id: int,
    multiplier: float = 2.5,
    similarity_threshold: float = 0.82,
) -> Tuple[Dict[str, Any], InterviewBlueprint, List[QuestionBankItem]]:
    """Generates the pool for `interview`, replaces any stored items, and returns (result, blueprint, items)."""
    canonical_profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id)
        .order_by(Profile.version.desc())
        .first()
    )
    parsed_profile = canonical_profile.structured_data if canonical_profile else None
    target_prof = db.query(TargetProfile).filter(TargetProfile.user_id == user_id).first()
    edu_prof = db.query(EducationProfile).filter(EducationProfile.user_id == user_id).first()
    user_context = load_user_context(user_id, db)

    blueprint = build_interview_blueprint(
        profile=parsed_profile,
        target_profile=target_prof,
        config=interview,
        user_context=user_context,
    )

    gen_result = await generate_question_pool_async(
        blueprint=blueprint,
        profile=parsed_profile,
        target_profile=target_prof,
        education=edu_prof,
        user_context=user_context,
        multiplier=multiplier,
        similarity_threshold=similarity_threshold,
    )

    db.query(QuestionBankItem).filter(QuestionBankItem.interview_id == interview.id).delete()
    db.commit()

    now = datetime.now(timezone.utc)
    items = [_bank_item(interview.id, q, False, now) for q in gen_result["active_questions"]]
    items += [_bank_item(interview.id, q, True, now) for q in gen_result["reserve_questions"]]
    db.add_all(items)
    db.commit()
    for item in items:
        db.refresh(item)
    return gen_result, blueprint, items


async def ensure_question_pool(interview_id: int, user_id: int) -> int:
    """Generates the pool if the interview has none. Returns how many items it holds."""
    db = SessionLocal()
    try:
        existing = db.query(QuestionBankItem).filter(QuestionBankItem.interview_id == interview_id).count()
        if existing:
            return existing
        interview = db.query(InterviewConfig).filter(InterviewConfig.id == interview_id).first()
        if not interview:
            return 0
        _, _, items = await build_question_pool(db, interview, user_id)
        logger.info("Generated %d pool questions for interview #%d at session start", len(items), interview_id)
        return len(items)
    finally:
        db.close()
