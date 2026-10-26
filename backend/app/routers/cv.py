import os
import uuid
import re
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import User, CVDocument
from app.auth import get_current_user
from app.schemas import (
    CVUploadResponse,
    CVStatusResponse,
    CVParsedResponse,
    StructuredCV,
    CrossCheckFlag,
)
from app.services.cv_extractor import validate_cv_file, extract_cv_text, CVValidationError
from app.services.cv_structuring import parse_and_cross_check_cv

router = APIRouter(prefix="/cv", tags=["CV Upload, Extraction & Structuring"])

STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "storage",
    "cv_uploads"
)
os.makedirs(STORAGE_DIR, exist_ok=True)


def sanitize_filename(filename: str) -> str:
    clean = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    return clean or "document"


import logging

logger = logging.getLogger("intervai.cv")

def process_cv_extraction(cv_id: int, file_path: str, file_type: str):
    db: Session = SessionLocal()
    try:
        cv_doc = db.query(CVDocument).filter(CVDocument.id == cv_id).first()
        if not cv_doc:
            logger.warning("[CV][cv_id=%d] Document not found for background extraction", cv_id)
            return

        user_id = cv_doc.user_id
        logger.info("[CV][cv_id=%d][user_id=%d] Starting background CV extraction (type=%s)", cv_id, user_id, file_type)
        cv_doc.status = "extracting"
        db.commit()

        try:
            extracted_text = extract_cv_text(file_path, file_type)
            cv_doc.raw_text = extracted_text
            cv_doc.status = "extracted"
            cv_doc.extracted_at = datetime.now(timezone.utc)
            cv_doc.error_code = None
            cv_doc.error_message = None

            # Advance user onboarding status
            user = db.query(User).filter(User.id == cv_doc.user_id).first()
            if user and user.onboarding_status in ("not_started", "education_done", "target_done"):
                user.onboarding_status = "cv_done"

            db.commit()
            logger.info("[CV][cv_id=%d][user_id=%d] CV text extracted successfully (%d chars)", cv_id, user_id, len(extracted_text))
        except CVValidationError as ve:
            cv_doc.status = "failed"
            cv_doc.error_code = ve.error_code
            cv_doc.error_message = ve.message
            db.commit()
            logger.warning("[CV][cv_id=%d][user_id=%d] CV validation error: code=%s message=%s", cv_id, user_id, ve.error_code, ve.message)
        except Exception as e:
            cv_doc.status = "failed"
            cv_doc.error_code = "UNREADABLE"
            cv_doc.error_message = "Extraction failed: the file could not be read."
            db.commit()
            logger.error("[CV][cv_id=%d][user_id=%d] Unexpected extraction failure: %s", cv_id, user_id, e)
    finally:
        db.close()


@router.post("/upload", response_model=CVUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_cv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    filename = file.filename or "uploaded_file"

    try:
        file_bytes = await file.read()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error_code": "UNREADABLE",
                "detail": "Failed to read uploaded file contents.",
                "message": "Failed to read uploaded file contents."
            }
        )

    # Validate file
    try:
        detected_type = validate_cv_file(file_bytes, filename)
    except CVValidationError as err:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error_code": err.error_code,
                "detail": err.message,
                "message": err.message
            }
        )

    # Generate unique key & save file
    safe_name = sanitize_filename(filename)
    file_key = f"{uuid.uuid4().hex}_{safe_name}"
    file_path = os.path.join(STORAGE_DIR, file_key)

    try:
        with open(file_path, "wb") as f:
            f.write(file_bytes)
    except OSError:
        logger.exception("Could not persist CV upload to storage")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not persist file to storage."
        )

    # Create CVDocument row in DB
    cv_doc = CVDocument(
        user_id=current_user.id,
        file_key=file_key,
        filename=filename,
        file_size=len(file_bytes),
        mime_type=file.content_type or ("application/pdf" if detected_type == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        status="uploaded",
        created_at=datetime.now(timezone.utc),
    )
    db.add(cv_doc)
    db.commit()
    db.refresh(cv_doc)

    # Queue background extraction
    background_tasks.add_task(process_cv_extraction, cv_doc.id, file_path, detected_type)

    return CVUploadResponse(
        id=cv_doc.id,
        file_key=cv_doc.file_key,
        filename=cv_doc.filename,
        status=cv_doc.status,
        created_at=cv_doc.created_at,
    )


@router.get("/{cv_id}/status", response_model=CVStatusResponse)
def get_cv_status(
    cv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    cv_doc = (
        db.query(CVDocument)
        .filter(CVDocument.id == cv_id, CVDocument.user_id == current_user.id)
        .first()
    )
    if not cv_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV document not found"
        )

    text_length = len(cv_doc.raw_text) if cv_doc.raw_text else None

    return CVStatusResponse(
        id=cv_doc.id,
        status=cv_doc.status,
        filename=cv_doc.filename,
        file_size=cv_doc.file_size,
        text_length=text_length,
        raw_text=cv_doc.raw_text,
        error_code=cv_doc.error_code,
        error_message=cv_doc.error_message,
        created_at=cv_doc.created_at,
        extracted_at=cv_doc.extracted_at,
    )


@router.get("/latest", response_model=CVStatusResponse)
def get_latest_cv(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    cv_doc = (
        db.query(CVDocument)
        .filter(CVDocument.user_id == current_user.id)
        .order_by(CVDocument.created_at.desc())
        .first()
    )
    if not cv_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No CV document found for user"
        )

    text_length = len(cv_doc.raw_text) if cv_doc.raw_text else None

    return CVStatusResponse(
        id=cv_doc.id,
        status=cv_doc.status,
        filename=cv_doc.filename,
        file_size=cv_doc.file_size,
        text_length=text_length,
        raw_text=cv_doc.raw_text,
        error_code=cv_doc.error_code,
        error_message=cv_doc.error_message,
        created_at=cv_doc.created_at,
        extracted_at=cv_doc.extracted_at,
    )


@router.post("/{cv_id}/parse", response_model=CVParsedResponse)
async def parse_cv_document(
    cv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    cv_doc = (
        db.query(CVDocument)
        .filter(CVDocument.id == cv_id, CVDocument.user_id == current_user.id)
        .first()
    )
    if not cv_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV document not found"
        )

    if not cv_doc.raw_text or not cv_doc.raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CV text has not been extracted yet or is empty. Please wait for extraction or re-upload."
        )

    try:
        structured_cv, flags = await parse_and_cross_check_cv(cv_doc, db)
    except Exception:
        logger.exception("CV structuring failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CV structuring failed."
        )

    return CVParsedResponse(
        id=cv_doc.id,
        status=cv_doc.status,
        structured_data=structured_cv,
        cross_check_flags=flags,
        parsed_at=cv_doc.parsed_at,
    )


@router.get("/latest/parsed", response_model=CVParsedResponse)
def get_latest_parsed_cv_document(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    cv_doc = (
        db.query(CVDocument)
        .filter(CVDocument.user_id == current_user.id, CVDocument.structured_data.isnot(None))
        .order_by(CVDocument.created_at.desc())
        .first()
    )
    if not cv_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No structured CV found for user. Call POST /cv/{id}/parse first."
        )

    structured = StructuredCV.model_validate(cv_doc.structured_data)
    flags = [
        CrossCheckFlag.model_validate(f) for f in (cv_doc.cross_check_flags or [])
    ]

    return CVParsedResponse(
        id=cv_doc.id,
        status=cv_doc.status,
        structured_data=structured,
        cross_check_flags=flags,
        parsed_at=cv_doc.parsed_at,
    )


@router.get("/{cv_id}/parsed", response_model=CVParsedResponse)
def get_parsed_cv_document(
    cv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    cv_doc = (
        db.query(CVDocument)
        .filter(CVDocument.id == cv_id, CVDocument.user_id == current_user.id)
        .first()
    )
    if not cv_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV document not found"
        )

    if not cv_doc.structured_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV has not been structured yet. Call POST /cv/{id}/parse first."
        )

    structured = StructuredCV.model_validate(cv_doc.structured_data)
    flags = [
        CrossCheckFlag.model_validate(f) for f in (cv_doc.cross_check_flags or [])
    ]

    return CVParsedResponse(
        id=cv_doc.id,
        status=cv_doc.status,
        structured_data=structured,
        cross_check_flags=flags,
        parsed_at=cv_doc.parsed_at,
    )


