"""
Report Router (Phase 6.2).
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
from app.auth import get_current_user
from app.services.report_generator_service import generate_and_persist_report
from app.services.improvement_plan_service import build_improvement_plan
from app.services.pdf_export_service import build_pdf_report

router = APIRouter(prefix="/report", tags=["report"])


@router.get("/{id}")
def get_report(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the structured grounded report for interview session #{id}.
    """
    session = (
        db.query(InterviewSession)
        .filter(InterviewSession.id == id, InterviewSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview session #{id} not found.",
        )

    report_data = generate_and_persist_report(session_id=id, db=db)
    return report_data


@router.get("/{id}/improvement-plan")
def get_improvement_plan(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns 3-5 concrete action items with practice questions and curated learning resources
    for interview session #{id}.
    """
    session = (
        db.query(InterviewSession)
        .filter(InterviewSession.id == id, InterviewSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview session #{id} not found.",
        )

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
    return {"session_id": id, "actions": plan}


@router.get("/{id}/pdf")
def export_report_pdf(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Exports a clean, executive-quality multi-page PDF report matching the on-screen view,
    including embedded high-resolution charts.
    """
    session = (
        db.query(InterviewSession)
        .filter(InterviewSession.id == id, InterviewSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview session #{id} not found.",
        )

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
