from datetime import datetime, timezone
import hashlib
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, InterviewConfig, UserMemory, AskedQuestion, Profile, TargetProfile, EducationProfile, QuestionBankItem
from app.auth import get_current_user
from app.schemas import (
    InterviewConfigCreate,
    InterviewConfigOut,
    UserContextOut,
    AskedQuestionOut,
    InterviewBlueprint,
    InterviewBlueprintRequest,
    QuestionBankItemOut,
    QuestionPoolOut,
    QuestionGenerationRequest,
)
from app.services.interview_context import load_user_context, MODE_PRESETS
from app.services.interview_blueprint import build_interview_blueprint
from app.services.question_generator import generate_question_pool_async

router = APIRouter(prefix="/interview", tags=["Interview Setup & Execution"])


@router.get("/context", response_model=UserContextOut)
def get_user_interview_context(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns user context for interview setup:
    - New user -> default baseline weights (equal weights), medium difficulty start
    - Returning user -> loaded past scores, weak areas, asked question history, and adaptive recommendations
    """
    return load_user_context(current_user.id, db)


@router.post("/config", response_model=InterviewConfigOut, status_code=status.HTTP_201_CREATED)
@router.post("/setup", response_model=InterviewConfigOut, status_code=status.HTTP_201_CREATED)
def create_interview_config(
    body: InterviewConfigCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Save the interview setup configuration:
    - round_type: Technical, HR, Managerial, Mixed
    - difficulty: Easy, Medium, Hard, Adaptive
    - duration_minutes: 15, 30, 45, etc.
    - language: e.g. English
    - mode: normal or pressure (pressure mode sets shorter answer timer & aggressive probing)
    """
    now = datetime.now(timezone.utc)
    new_config = InterviewConfig(
        user_id=current_user.id,
        round_type=body.round_type,
        difficulty=body.difficulty,
        duration_minutes=body.duration_minutes,
        language=body.language,
        mode=body.mode,
        focus_topics=body.focus_topics or [],
        created_at=now,
    )
    db.add(new_config)
    db.commit()
    db.refresh(new_config)

    mode_info = MODE_PRESETS.get(new_config.mode, MODE_PRESETS["normal"])
    timer_seconds = mode_info["answer_timer_seconds"]

    return InterviewConfigOut(
        id=new_config.id,
        user_id=new_config.user_id,
        round_type=new_config.round_type,
        difficulty=new_config.difficulty,
        duration_minutes=new_config.duration_minutes,
        language=new_config.language,
        mode=new_config.mode,
        focus_topics=new_config.focus_topics or [],
        answer_timer_seconds=timer_seconds,
        pressure_rules=mode_info,
        created_at=new_config.created_at,
    )


@router.get("/config/latest", response_model=InterviewConfigOut)
def get_latest_interview_config(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieve the candidate's latest saved interview configuration.
    """
    latest = (
        db.query(InterviewConfig)
        .filter(InterviewConfig.user_id == current_user.id)
        .order_by(InterviewConfig.created_at.desc())
        .first()
    )
    if not latest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No interview configuration found for this user."
        )

    mode_info = MODE_PRESETS.get(latest.mode, MODE_PRESETS["normal"])
    timer_seconds = mode_info["answer_timer_seconds"]

    return InterviewConfigOut(
        id=latest.id,
        user_id=latest.user_id,
        round_type=latest.round_type,
        difficulty=latest.difficulty,
        duration_minutes=latest.duration_minutes,
        language=latest.language,
        mode=latest.mode,
        focus_topics=latest.focus_topics or [],
        answer_timer_seconds=timer_seconds,
        pressure_rules=mode_info,
        created_at=latest.created_at,
    )


@router.post("/seed-history", response_model=UserContextOut)
def seed_user_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Developer helper endpoint to seed simulated history for testing returning-user behavior.
    """
    now = datetime.now(timezone.utc)
    memory = db.query(UserMemory).filter(UserMemory.user_id == current_user.id).first()
    if not memory:
        memory = UserMemory(
            user_id=current_user.id,
            topic_scores={
                "React architecture": 68.0,
                "System design": 74.0,
                "Communication": 86.0,
                "Problem solving": 82.0,
                "Clarity": 62.0,
            },
            weak_topics=["React architecture", "Clarity"],
            session_count=4,
            last_session_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(memory)
    else:
        memory.topic_scores = {
            "React architecture": 68.0,
            "System design": 74.0,
            "Communication": 86.0,
            "Problem solving": 82.0,
            "Clarity": 62.0,
        }
        memory.weak_topics = ["React architecture", "Clarity"]
        memory.session_count = (memory.session_count or 0) + 1
        memory.last_session_at = now
        memory.updated_at = now

    # Add sample asked questions if not already present
    sample_questions = [
        ("Tell me about a time you had to optimize state rendering performance in React.", "React architecture", 65.0),
        ("How would you design a scalable notification feed with real-time updates?", "System design", 75.0),
        ("Describe a challenging conflict you navigated with a cross-functional peer.", "Communication", 88.0),
        ("Walk me through your thought process when solving an ambiguous algorithmic trade-off.", "Problem solving", 84.0),
    ]

    for q_text, topic, score in sample_questions:
        q_hash = hashlib.sha256(q_text.encode("utf-8")).hexdigest()[:16]
        existing_q = (
            db.query(AskedQuestion)
            .filter(AskedQuestion.user_id == current_user.id, AskedQuestion.question_hash == q_hash)
            .first()
        )
        if not existing_q:
            db.add(
                AskedQuestion(
                    user_id=current_user.id,
                    question_hash=q_hash,
                    topic=topic,
                    question_text=q_text,
                    score=score,
                    asked_at=now,
                )
            )

    db.commit()
    return load_user_context(current_user.id, db)


@router.post("/blueprint", response_model=InterviewBlueprint)
def create_interview_blueprint(
    body: Optional[InterviewBlueprintRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Constructs an interview blueprint tailored to candidate profile, target role,
    session configuration, and historical performance memory.
    """
    # 1. Fetch user profile
    canonical_profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .order_by(Profile.version.desc())
        .first()
    )
    parsed_profile = canonical_profile.structured_data if canonical_profile else None

    # 2. Fetch target profile
    target_prof = (
        db.query(TargetProfile)
        .filter(TargetProfile.user_id == current_user.id)
        .first()
    )

    # 3. Resolve InterviewConfig
    saved_config = None
    if body and body.config_id:
        saved_config = (
            db.query(InterviewConfig)
            .filter(InterviewConfig.id == body.config_id, InterviewConfig.user_id == current_user.id)
            .first()
        )
    if not saved_config:
        saved_config = (
            db.query(InterviewConfig)
            .filter(InterviewConfig.user_id == current_user.id)
            .order_by(InterviewConfig.created_at.desc())
            .first()
        )

    # Build active config dict from saved config plus any request overrides
    active_config = {
        "round_type": (body.round_type if body and body.round_type else None) or (saved_config.round_type if saved_config else "Technical"),
        "difficulty": (body.difficulty if body and body.difficulty else None) or (saved_config.difficulty if saved_config else "Medium"),
        "duration_minutes": (body.duration_minutes if body and body.duration_minutes else None) or (saved_config.duration_minutes if saved_config else 30),
        "language": (body.language if body and body.language else None) or (saved_config.language if saved_config else "English"),
        "mode": (body.mode if body and body.mode else None) or (saved_config.mode if saved_config else "normal"),
        "focus_topics": (body.focus_topics if body and body.focus_topics is not None else None) or (saved_config.focus_topics if saved_config else []),
    }

    # 4. Fetch user memory context
    user_context = load_user_context(current_user.id, db)

    # 5. Build blueprint
    blueprint = build_interview_blueprint(
        profile=parsed_profile,
        target_profile=target_prof,
        config=active_config,
        user_context=user_context,
        mixed_ratio=body.mixed_ratio if body else None,
    )
    return blueprint


@router.post("/{id}/questions/generate", response_model=QuestionPoolOut, status_code=status.HTTP_201_CREATED)
async def generate_interview_questions(
    id: int,
    body: Optional[QuestionGenerationRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generates a tailored question pool (2-3x required question count),
    deduplicates near-duplicates and previously asked questions,
    tags, ranks, attaches reserve follow-up templates, and stores in the QuestionBank.
    """
    interview = (
        db.query(InterviewConfig)
        .filter(InterviewConfig.id == id, InterviewConfig.user_id == current_user.id)
        .first()
    )
    if not interview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview configuration #{id} not found."
        )

    force_regenerate = body.force_regenerate if body else False
    existing_items = (
        db.query(QuestionBankItem)
        .filter(QuestionBankItem.interview_id == id)
        .all()
    )
    if existing_items and not force_regenerate:
        active_items = [q for q in existing_items if not q.is_reserve_followup]
        reserve_items = [q for q in existing_items if q.is_reserve_followup]
        return QuestionPoolOut(
            interview_id=id,
            total_generated=len(existing_items),
            deduped_count=len(existing_items),
            questions=[QuestionBankItemOut.model_validate(q) for q in active_items],
            reserve_followups=[QuestionBankItemOut.model_validate(q) for q in reserve_items],
            blueprint_summary={
                "round_type": interview.round_type,
                "difficulty": interview.difficulty,
                "duration_minutes": interview.duration_minutes,
                "active_count": len(active_items),
                "reserve_count": len(reserve_items),
            },
        )

    # Fetch context: profile, target, education, user memory
    canonical_profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .order_by(Profile.version.desc())
        .first()
    )
    parsed_profile = canonical_profile.structured_data if canonical_profile else None
    target_prof = db.query(TargetProfile).filter(TargetProfile.user_id == current_user.id).first()
    edu_prof = db.query(EducationProfile).filter(EducationProfile.user_id == current_user.id).first()
    user_context = load_user_context(current_user.id, db)

    # Build blueprint
    blueprint = build_interview_blueprint(
        profile=parsed_profile,
        target_profile=target_prof,
        config=interview,
        user_context=user_context,
    )

    # Generate question pool
    multiplier = body.multiplier if body and body.multiplier else 2.5
    similarity_threshold = body.similarity_threshold if body and body.similarity_threshold else 0.82

    gen_result = await generate_question_pool_async(
        blueprint=blueprint,
        profile=parsed_profile,
        target_profile=target_prof,
        education=edu_prof,
        user_context=user_context,
        multiplier=multiplier,
        similarity_threshold=similarity_threshold,
    )

    # Clear previous question bank items for this interview if force regenerating
    if existing_items:
        db.query(QuestionBankItem).filter(QuestionBankItem.interview_id == id).delete()
        db.commit()

    now = datetime.now(timezone.utc)
    new_db_items: List[QuestionBankItem] = []

    for q in gen_result["active_questions"]:
        item = QuestionBankItem(
            interview_id=id,
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
            is_reserve_followup=False,
            followup_templates=q.get("followup_templates") or [],
            created_at=now,
        )
        db.add(item)
        new_db_items.append(item)

    for q in gen_result["reserve_questions"]:
        item = QuestionBankItem(
            interview_id=id,
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
            is_reserve_followup=True,
            followup_templates=q.get("followup_templates") or [],
            created_at=now,
        )
        db.add(item)
        new_db_items.append(item)

    db.commit()
    for item in new_db_items:
        db.refresh(item)

    active_out = [QuestionBankItemOut.model_validate(q) for q in new_db_items if not q.is_reserve_followup]
    reserve_out = [QuestionBankItemOut.model_validate(q) for q in new_db_items if q.is_reserve_followup]

    return QuestionPoolOut(
        interview_id=id,
        total_generated=gen_result["total_generated"],
        deduped_count=gen_result["deduped_count"],
        questions=active_out,
        reserve_followups=reserve_out,
        blueprint_summary={
            "round_type": blueprint.round_type,
            "difficulty": blueprint.difficulty,
            "duration_minutes": blueprint.duration_minutes,
            "total_question_count": blueprint.total_question_count,
            "topics": [t.model_dump() for t in blueprint.topics],
            "active_count": len(active_out),
            "reserve_count": len(reserve_out),
        },
    )


@router.get("/{id}/questions", response_model=QuestionPoolOut)
def get_interview_questions(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves the stored question pool for an interview session from the QuestionBank.
    """
    interview = (
        db.query(InterviewConfig)
        .filter(InterviewConfig.id == id, InterviewConfig.user_id == current_user.id)
        .first()
    )
    if not interview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview configuration #{id} not found."
        )

    items = (
        db.query(QuestionBankItem)
        .filter(QuestionBankItem.interview_id == id)
        .order_by(QuestionBankItem.rank_score.desc())
        .all()
    )
    active_items = [q for q in items if not q.is_reserve_followup]
    reserve_items = [q for q in items if q.is_reserve_followup]

    return QuestionPoolOut(
        interview_id=id,
        total_generated=len(items),
        deduped_count=len(items),
        questions=[QuestionBankItemOut.model_validate(q) for q in active_items],
        reserve_followups=[QuestionBankItemOut.model_validate(q) for q in reserve_items],
        blueprint_summary={
            "round_type": interview.round_type,
            "difficulty": interview.difficulty,
            "duration_minutes": interview.duration_minutes,
            "active_count": len(active_items),
            "reserve_count": len(reserve_items),
        },
    )


