"""
Report Router (Phase 6.2 & Guest Practice Mode).
Provides endpoints for report access, improvement plan retrieval, and server-side PDF export.
Endpoints:
- GET /report/{id}
- GET /report/{id}/pdf
- GET /report/{id}/improvement-plan
"""

from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, InterviewSession
from app.auth import get_current_user_or_guest, AuthContext
from app.services.report_generator_service import generate_and_persist_report
from app.services.improvement_plan_service import build_improvement_plan
from app.services.pdf_export_service import build_pdf_report

router = APIRouter(prefix="/report", tags=["report"])


def _resolve_session_for_caller(id: int, auth_ctx: AuthContext, db: Session) -> InterviewSession:
    """
    Ensures callers can only access their authorized sessions:
    - Registered user: session.user_id == current_user.id
    - Guest: session.is_guest == True and session.id == guest_session_id
    """
    if auth_ctx.is_guest:
        if auth_ctx.guest_session_id is not None and auth_ctx.guest_session_id != id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Guest token does not permit access to this interview session.",
            )
        session = (
            db.query(InterviewSession)
            .filter(InterviewSession.id == id, InterviewSession.is_guest == True)
            .first()
        )
    else:
        user = auth_ctx.user
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        session = (
            db.query(InterviewSession)
            .filter(InterviewSession.id == id, InterviewSession.user_id == user.id)
            .first()
        )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview session #{id} not found.",
        )
    return session


@router.get("/{id}")
def get_report(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns the structured grounded report for interview session #{id}.
    Accessible by the session owner (registered user) or authorized guest.
    """
    session = _resolve_session_for_caller(id, auth_ctx, db)
    report_data = generate_and_persist_report(session_id=id, db=db)
    
    # Attach guest metadata flag for frontend banner display
    if isinstance(report_data, dict):
        report_data["is_guest"] = bool(session.is_guest)

    return report_data


@router.get("/{id}/improvement-plan")
def get_improvement_plan(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns 3-5 concrete action items with practice questions and curated learning resources
    for interview session #{id}.
    """
    session = _resolve_session_for_caller(id, auth_ctx, db)

    from app.models import SessionResult
    sess_res = db.query(SessionResult).filter(SessionResult.session_id == id).first()
    if not sess_res:
        from app.services.score_fusion_service import process_and_persist_session_result
        res_dict = process_and_persist_session_result(session_id=id, db=db)
    else:
        res_dict = {
            "overall_score": sess_res.overall_score,
            "content_score": sess_res.content_score,
            "speech_score": sess_res.speech_score,
            "face_score": sess_res.face_score,
            "classification": sess_res.classification,
            "round_type": sess_res.round_type,
            "role": sess_res.role,
            "weak_areas": sess_res.weak_areas,
        }

    plan = build_improvement_plan(res_dict)
    return {"session_id": id, "actions": plan, "is_guest": bool(session.is_guest)}


@router.get("/{id}/pdf")
def export_report_pdf(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Exports a clean, executive-quality multi-page PDF report.
    PDF export is strictly blocked for anonymous guests.
    """
    if auth_ctx.is_guest:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PDF export is reserved for registered users. Please create a free account or log in to download PDF reports.",
        )

    session = _resolve_session_for_caller(id, auth_ctx, db)

    try:
        pdf_bytes = build_pdf_report(session_id=id, db=db)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="intervai_report_{id}.pdf"',
                "Content-Type": "application/pdf",
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF report: {str(e)}",
        )
