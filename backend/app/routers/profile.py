from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, EducationProfile, TargetProfile, Profile
from app.auth import get_current_user
from app.schemas import (
    EducationProfileCreate,
    EducationProfileOut,
    TargetProfileCreate,
    TargetProfileOut,
    TargetSuggestionsOut,
    OnboardingStatusOut,
    TARGET_ROLE_SUGGESTIONS,
    VALID_COMPANY_TYPES,
    VALID_EXPERIENCE_LEVELS,
    ProfileConfirmRequest,
    ProfileOut,
    SeverityLevel,
)

router = APIRouter(prefix="/profile", tags=["Profile & Onboarding"])


@router.get("/education", response_model=EducationProfileOut)
def get_education_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(EducationProfile).filter(EducationProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Education profile not found"
        )
    return EducationProfileOut.model_validate(profile)


@router.put("/education", response_model=EducationProfileOut)
def upsert_education_profile(
    body: EducationProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(EducationProfile).filter(EducationProfile.user_id == current_user.id).first()
    now = datetime.now(timezone.utc)

    if profile:
        profile.degree = body.degree.strip()
        profile.branch = body.branch.strip()
        profile.college = body.college.strip()
        profile.graduation_year = body.graduation_year
        profile.cgpa = body.cgpa
        profile.cgpa_scale = body.cgpa_scale or 10.0
        profile.updated_at = now
    else:
        profile = EducationProfile(
            user_id=current_user.id,
            degree=body.degree.strip(),
            branch=body.branch.strip(),
            college=body.college.strip(),
            graduation_year=body.graduation_year,
            cgpa=body.cgpa,
            cgpa_scale=body.cgpa_scale or 10.0,
            created_at=now,
            updated_at=now,
        )
        db.add(profile)

    # Progress onboarding status if at initial step
    if current_user.onboarding_status in ("not_started", ""):
        current_user.onboarding_status = "education_done"

    db.commit()
    db.refresh(profile)
    return EducationProfileOut.model_validate(profile)


@router.get("/target", response_model=TargetProfileOut)
def get_target_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(TargetProfile).filter(TargetProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target profile not found"
        )
    return TargetProfileOut.model_validate(profile)


@router.put("/target", response_model=TargetProfileOut)
def upsert_target_profile(
    body: TargetProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(TargetProfile).filter(TargetProfile.user_id == current_user.id).first()
    now = datetime.now(timezone.utc)

    if profile:
        profile.target_role = body.target_role.strip()
        profile.company_type = body.company_type
        profile.experience_level = body.experience_level
        profile.job_description = body.job_description.strip() if body.job_description else None
        profile.updated_at = now
    else:
        profile = TargetProfile(
            user_id=current_user.id,
            target_role=body.target_role.strip(),
            company_type=body.company_type,
            experience_level=body.experience_level,
            job_description=body.job_description.strip() if body.job_description else None,
            created_at=now,
            updated_at=now,
        )
        db.add(profile)

    # Progress onboarding status
    if current_user.onboarding_status in ("not_started", "education_done"):
        current_user.onboarding_status = "target_done"

    db.commit()
    db.refresh(profile)
    return TargetProfileOut.model_validate(profile)


@router.get("/target/suggestions", response_model=TargetSuggestionsOut)
def get_target_suggestions():
    return TargetSuggestionsOut(
        suggestions=TARGET_ROLE_SUGGESTIONS,
        company_types=VALID_COMPANY_TYPES,
        experience_levels=VALID_EXPERIENCE_LEVELS,
    )


@router.get("/status", response_model=OnboardingStatusOut)
def get_onboarding_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    has_edu = db.query(EducationProfile).filter(EducationProfile.user_id == current_user.id).first() is not None
    has_target = db.query(TargetProfile).filter(TargetProfile.user_id == current_user.id).first() is not None

    status_str = current_user.onboarding_status or "not_started"

    # Step determination:
    # 1: Education
    # 2: Target
    # 3: CV Upload
    # 4: Review
    # 5: Done (Dashboard)
    if status_str == "profile_confirmed":
        step = 5
    elif status_str == "cv_done":
        step = 4
    elif status_str == "target_done":
        step = 3
    elif status_str == "education_done":
        step = 2
    else:
        step = 1

    return OnboardingStatusOut(
        onboarding_status=status_str,
        current_step=step,
        education_done=has_edu or status_str in ("education_done", "target_done", "cv_done", "profile_confirmed"),
        target_done=has_target or status_str in ("target_done", "cv_done", "profile_confirmed"),
        cv_done=status_str in ("cv_done", "profile_confirmed"),
        profile_confirmed=status_str == "profile_confirmed",
    )


@router.put("/confirm", response_model=ProfileOut)
@router.post("/confirm", response_model=ProfileOut)
def confirm_canonical_profile(
    body: ProfileConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate unresolved high-severity flags
    if body.unresolved_flags:
        high_flags = [f for f in body.unresolved_flags if f.severity == SeverityLevel.HIGH]
        if high_flags:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot confirm profile with {len(high_flags)} unresolved high-severity alignment note(s). Please resolve them before confirming."
            )

    # Determine next version for user
    latest_profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .order_by(Profile.version.desc())
        .first()
    )
    next_version = (latest_profile.version + 1) if latest_profile else 1

    now = datetime.now(timezone.utc)
    new_profile = Profile(
        user_id=current_user.id,
        structured_data=body.structured_data.model_dump(),
        version=next_version,
        cv_document_id=body.cv_document_id,
        confirmed_at=now,
        created_at=now,
    )
    db.add(new_profile)

    # Mark user's onboarding complete
    current_user.onboarding_status = "profile_confirmed"
    db.commit()
    db.refresh(new_profile)

    return ProfileOut.model_validate(new_profile)


@router.get("", response_model=ProfileOut)
def get_canonical_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    canonical_profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .order_by(Profile.version.desc())
        .first()
    )
    if not canonical_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No confirmed profile found. Complete onboarding review first."
        )
    return ProfileOut.model_validate(canonical_profile)


@router.get("/versions")
def get_profile_versions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profiles = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .order_by(Profile.version.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "version": p.version,
            "cv_document_id": p.cv_document_id,
            "confirmed_at": p.confirmed_at,
        }
        for p in profiles
    ]


@router.delete("/me/data", status_code=status.HTTP_200_OK)
@router.delete("/data", status_code=status.HTTP_200_OK)
def delete_my_personal_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GDPR & CCPA Compliant 'Delete My Data' endpoint.
    Permanently purges:
    - All uploaded CV documents and files from storage.
    - All recorded audio chunks, video frames, and transcripts.
    - All interview sessions, calibrations, signals, integrity events, scores, and reports.
    - Target profile, education profile, and canonical profile records.
    - User memory and question history.
    - User consent audit records.
    """
    import os
    import shutil
    import logging
    from app.models import (
        CVDocument,
        InterviewSession,
        InterviewConfig,
        SessionCalibration,
        SignalTimeSeries,
        IntegrityEvent,
        SessionAnalysisJob,
        SessionResult,
        SessionReport,
        UserConsent,
        UserMemory,
        AskedQuestion,
    )
    from app.services.answer_capture_service import default_storage_manager
    from app.routers.cv import STORAGE_DIR as CV_STORAGE_DIR

    logger = logging.getLogger("intervai.privacy")
    user_id = current_user.id
    logger.info("Processing complete data deletion request for user_id=%d", user_id)

    # 1. Delete CV files and database rows
    cv_docs = db.query(CVDocument).filter(CVDocument.user_id == user_id).all()
    cv_count = len(cv_docs)
    for doc in cv_docs:
        if doc.file_key:
            fpath = os.path.join(CV_STORAGE_DIR, doc.file_key)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except OSError:
                    pass
        db.delete(doc)

    # 2. Delete Interview Sessions & Media files
    sessions = db.query(InterviewSession).filter(InterviewSession.user_id == user_id).all()
    session_count = len(sessions)
    for sess in sessions:
        sid = sess.id
        # Delete disk media
        sess_dir = os.path.join(default_storage_manager.base_dir, str(sid))
        if os.path.exists(sess_dir):
            shutil.rmtree(sess_dir, ignore_errors=True)

        # Delete dependent session rows
        db.query(SessionReport).filter(SessionReport.session_id == sid).delete()
        db.query(SessionResult).filter(SessionResult.session_id == sid).delete()
        db.query(SessionAnalysisJob).filter(SessionAnalysisJob.session_id == sid).delete()
        db.query(SessionCalibration).filter(SessionCalibration.session_id == sid).delete()
        db.query(SignalTimeSeries).filter(SignalTimeSeries.session_id == sid).delete()
        db.query(IntegrityEvent).filter(IntegrityEvent.session_id == sid).delete()
        db.delete(sess)

    # 3. Delete Profiles, Configs, Memory, History, and Consent
    db.query(Profile).filter(Profile.user_id == user_id).delete()
    db.query(EducationProfile).filter(EducationProfile.user_id == user_id).delete()
    db.query(TargetProfile).filter(TargetProfile.user_id == user_id).delete()
    db.query(InterviewConfig).filter(InterviewConfig.user_id == user_id).delete()
    db.query(UserMemory).filter(UserMemory.user_id == user_id).delete()
    db.query(AskedQuestion).filter(AskedQuestion.user_id == user_id).delete()
    db.query(UserConsent).filter(UserConsent.user_id == user_id).delete()

    # 4. Reset User onboarding & profile status
    current_user.onboarding_status = "not_started"
    current_user.name = "Candidate"
    db.commit()

    logger.info("Data deletion completed cleanly for user_id=%d", user_id)

    return {
        "status": "deleted",
        "message": "All personal data, CVs, session recordings, and interview history have been permanently purged.",
        "purged_records": {
            "cv_documents_deleted": cv_count,
            "interview_sessions_deleted": session_count,
            "profiles_purged": True,
            "memory_and_history_purged": True,
        },
    }


