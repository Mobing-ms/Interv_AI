from datetime import datetime, timezone
import hashlib
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, InterviewConfig, UserMemory, AskedQuestion
from app.auth import get_current_user
from app.schemas import (
    InterviewConfigCreate,
    InterviewConfigOut,
    UserContextOut,
    AskedQuestionOut,
)
from app.services.interview_context import load_user_context, MODE_PRESETS

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
