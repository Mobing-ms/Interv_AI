"""
Guest Practice Mode Router.
Provides endpoints for anonymous, no-account interview practice:
- POST /guest/start: Initiates guest practice session with abuse protections (IP limit & Turnstile CAPTCHA)
- POST /guest/cv/upload: Uploads CV with 2MB limit for guest sessions
- POST /guest/cleanup: Scheduled or on-demand cleanup of sessions older than 24 hours
- POST /guest/link: Links an anonymous guest session to a registered account
"""

import os
import uuid
import secrets
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
    UploadFile,
    File,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models import (
    User,
    InterviewSession,
    InterviewConfig,
    QuestionBankItem,
    UserConsent,
    CVDocument,
)
from app.auth import get_current_user, create_guest_token, require_maintenance_token
from app.services.guest_service import (
    check_guest_ip_limit,
    log_guest_ip,
    verify_turnstile_captcha,
    client_ip_from_request,
    generate_guest_questions,
    cleanup_expired_guest_sessions,
    link_guest_session_to_user,
)
from app.services.cv_extractor import validate_cv_file, extract_cv_text, CVValidationError
from app.routers.session import _build_ws_url

router = APIRouter(prefix="/guest", tags=["guest-practice"])


class GuestStartRequest(BaseModel):
    target_role: str = Field(default="Software Engineer", description="Target role")
    round_type: str = Field(default="Technical", description="Round type (Technical, HR, Managerial)")
    difficulty: str = Field(default="Medium", description="Difficulty (Easy, Medium, Hard)")
    turnstile_token: Optional[str] = Field(default=None, description="Cloudflare Turnstile CAPTCHA response")
    cv_text: Optional[str] = Field(default=None, description="Extracted CV text if provided")
    cv_document_id: Optional[int] = Field(default=None, description="Uploaded CV document ID")


class GuestStartResponse(BaseModel):
    session_id: int
    session_token: str
    guest_token: str
    guest_id: str
    round_type: str
    target_role: str
    difficulty: str
    duration_minutes: int
    total_questions: int
    questions: List[Dict[str, Any]]
    ws_url: str
    retention_hours: int = 24


class GuestLinkRequest(BaseModel):
    guest_session_id: int
    guest_token: Optional[str] = None


@router.post("/start", response_model=GuestStartResponse, status_code=status.HTTP_201_CREATED)
def start_guest_session(
    body: GuestStartRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Starts an anonymous guest practice session without requiring an account.
    Enforces abuse protection:
    1. Daily IP rate limit (configurable, default 3 sessions per IP per day).
    2. Cloudflare Turnstile CAPTCHA verification.
    3. Fixed 3 questions for a focused 8-10 minute interview.
    4. Issues a signed 24-hour guest JWT in an httpOnly cookie.
    """
    client_ip = client_ip_from_request(request)

    # 1. Abuse Protection: Daily IP Rate Limit
    is_allowed, hit_count = check_guest_ip_limit(client_ip, db)
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily guest practice limit reached ({settings.GUEST_MAX_SESSIONS_PER_IP_PER_DAY} per day). Please create a free account to continue practicing.",
        )

    # 2. Abuse Protection: Turnstile CAPTCHA Verification
    is_captcha_valid = verify_turnstile_captcha(body.turnstile_token, remote_ip=client_ip)
    if not is_captcha_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Security verification (CAPTCHA) failed. Please complete the verification check.",
        )

    # 3. Create Anonymous Guest Identity & Config
    guest_id = f"guest_{secrets.token_hex(12)}"
    now = datetime.now(timezone.utc)

    config = InterviewConfig(
        user_id=None,
        is_guest=True,
        round_type=body.round_type.title(),
        difficulty=body.difficulty.title(),
        duration_minutes=settings.GUEST_DURATION_MINUTES,
        language="English",
        mode="normal",
        focus_topics=[],
        created_at=now,
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    # 4. Generate Exactly 3 Guest Questions
    raw_questions = generate_guest_questions(
        role=body.target_role,
        round_type=body.round_type,
        difficulty=body.difficulty,
        cv_text=body.cv_text,
    )

    created_questions = []
    for q in raw_questions:
        q_item = QuestionBankItem(
            interview_id=config.id,
            question_hash=q["question_hash"],
            text=q["text"],
            topic=q["topic"],
            difficulty=q["difficulty"],
            question_type=q["question_type"],
            expected_keywords=q["expected_keywords"],
            ideal_answer_points=q["ideal_answer_points"],
            max_time_seconds=q["max_time_seconds"],
            rank_score=q["rank_score"],
            is_reserve_followup=False,
            created_at=now,
        )
        db.add(q_item)
        db.commit()
        db.refresh(q_item)
        created_questions.append({
            "id": q_item.id,
            "text": q_item.text,
            "topic": q_item.topic,
            "difficulty": q_item.difficulty,
            "question_type": q_item.question_type,
            "max_time_seconds": q_item.max_time_seconds,
        })

    # 5. Create Guest Privacy Consent (Explicit 24h Retention)
    consent = UserConsent(
        user_id=None,
        is_guest=True,
        guest_id=guest_id,
        version="guest-v1.0",
        retention_days=1,  # 24 hours
        accepted=True,
        can_delete=True,
        accepted_at=now,
    )
    db.add(consent)

    # 6. Create Guest Interview Session
    session_token = secrets.token_urlsafe(32)
    session = InterviewSession(
        user_id=None,
        is_guest=True,
        guest_id=guest_id,
        interview_id=config.id,
        status="created",
        session_token=session_token,
        started_at=now,
        created_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    # Log IP hit for abuse tracking
    log_guest_ip(client_ip, session.id, db)

    # 7. Create Signed Guest Access Token
    guest_jwt = create_guest_token(guest_id=guest_id, session_id=session.id)

    # Set httpOnly secure cookie
    response.set_cookie(
        key="guest_token",
        value=guest_jwt,
        max_age=86400,  # 24 hours
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )

    ws_url = _build_ws_url(request, session.id, session.session_token)

    return GuestStartResponse(
        session_id=session.id,
        session_token=session.session_token,
        guest_token=guest_jwt,
        guest_id=guest_id,
        round_type=config.round_type,
        target_role=body.target_role,
        difficulty=config.difficulty,
        duration_minutes=config.duration_minutes,
        total_questions=len(created_questions),
        questions=created_questions,
        ws_url=ws_url,
        retention_hours=24,
    )


@router.post("/cv/upload")
async def upload_guest_cv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Uploads an optional CV file for a guest session.
    Strictly enforces a 2MB maximum size cap for guest uploads.
    """
    filename = file.filename or "cv_document"

    try:
        file_bytes = await file.read()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read uploaded CV file.",
        )

    # Enforce strict 2MB cap for guests
    if len(file_bytes) > settings.GUEST_MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"CV upload size exceeds the 2MB guest limit (file size: {len(file_bytes)} bytes).",
        )

    # Validate file type
    try:
        detected_type = validate_cv_file(file_bytes, filename)
    except CVValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err.message,
        )

    storage_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "storage",
        "cv_uploads",
    )
    os.makedirs(storage_dir, exist_ok=True)
    file_key = f"guest_{uuid.uuid4().hex}_{filename}"
    file_path = os.path.join(storage_dir, file_key)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # Extract text
    try:
        extracted_text = extract_cv_text(file_path, detected_type)
    except Exception as e:
        extracted_text = ""

    # Create CVDocument
    cv_doc = CVDocument(
        user_id=None,
        is_guest=True,
        file_key=file_key,
        filename=filename,
        file_size=len(file_bytes),
        mime_type=file.content_type or "application/pdf",
        status="extracted" if extracted_text else "uploaded",
        raw_text=extracted_text,
        created_at=datetime.now(timezone.utc),
    )
    db.add(cv_doc)
    db.commit()
    db.refresh(cv_doc)

    return {
        "cv_document_id": cv_doc.id,
        "filename": filename,
        "file_size": len(file_bytes),
        "raw_text_snippet": (extracted_text or "")[:300],
        "status": cv_doc.status,
    }


@router.post("/cleanup")
def cleanup_old_guest_data(request: Request, db: Session = Depends(get_db)):
    """
    Requires X-Maintenance-Token.
    Deletes all guest sessions and storage files older than 24 hours.
    Can be run on schedule or invoked by background maintenance jobs.
    """
    require_maintenance_token(request)
    cleaned = cleanup_expired_guest_sessions(db, max_age_hours=settings.GUEST_RETENTION_HOURS)
    return {
        "status": "success",
        "cleaned_sessions_count": cleaned,
        "message": f"Successfully deleted {cleaned} expired guest session(s) older than {settings.GUEST_RETENTION_HOURS}h.",
    }


@router.post("/link")
def link_guest_session(
    request: Request,
    body: GuestLinkRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Links an anonymous guest session and its report to the currently logged in user account.
    The caller must prove ownership of the guest session with its guest token
    (body.guest_token, X-Guest-Token header, or the guest_token cookie).
    """
    from app.auth import guest_session_ids_proven_by_request
    if body.guest_session_id not in guest_session_ids_proven_by_request(request, body.guest_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A valid guest token for this session is required to link it.",
        )
    success = link_guest_session_to_user(
        guest_session_id=body.guest_session_id,
        user_id=current_user.id,
        db=db,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guest session #{body.guest_session_id} not found or already linked.",
        )

    return {
        "status": "linked",
        "session_id": body.guest_session_id,
        "user_id": current_user.id,
        "message": "Guest session successfully linked to your account.",
    }
