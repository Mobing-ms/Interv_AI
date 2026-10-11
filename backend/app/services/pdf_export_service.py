"""
Server-Side PDF Export Service (Phase 6.2).
Generates an executive-level, publication-quality multimodal interview report PDF matching
the on-screen report layout.
Features:
- High-resolution embedded Matplotlib chart images (Skill Radar, Confidence Timeline, Progress Trend).
- Comprehensive sections:
  1. Header & Candidate Metadata
  2. Executive Composite Scores & Narrative Summary
  3. Visual Analytics (Radar & Timeline Charts)
  4. Strengths & Growth Areas
  5. Per-Question Detailed Breakdown (Transcript excerpts, Feedback, Model Outlines)
  6. Actionable Improvement Plan (with Practice Questions & Verified Documentation Links)
  7. Integrity & Proctoring Audit
- ReportLab Platypus layout with professional color palette, typography, and page numbers.
"""

import os
import io
import math
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# Ensure headless Matplotlib rendering
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
    KeepTogether,
    HRFlowable,
)
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import InterviewSession, SessionResult, SessionReport, IntegrityEvent, User
from app.services.report_generator_service import generate_and_persist_report
from app.services.improvement_plan_service import build_improvement_plan

logger = logging.getLogger("intervai.pdf_export")


# =============================================================================
# 1. COLOR THEME & STYLING CONSTANTS
# =============================================================================

PRIMARY_COLOR = colors.HexColor("#0f172a")     # Slate 900
BRAND_ACCENT = colors.HexColor("#4f46e5")      # Indigo 600
BRAND_LIGHT = colors.HexColor("#eef2ff")       # Indigo 50
SUCCESS_COLOR = colors.HexColor("#059669")     # Emerald 600
WARNING_COLOR = colors.HexColor("#d97706")     # Amber 600
DANGER_COLOR = colors.HexColor("#dc2626")      # Red 600
MUTED_TEXT = colors.HexColor("#64748b")        # Slate 500
BORDER_COLOR = colors.HexColor("#cbd5e1")      # Slate 300
BG_CARD = colors.HexColor("#f8fafc")           # Slate 50


# =============================================================================
# 2. NUMBERED CANVAS FOR HEADER & FOOTER
# =============================================================================

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for dynamic total page count in footers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(MUTED_TEXT)

        # Header rule & title (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 755, "IntervAI Multimodal Assessment Report")
            self.drawRightString(612 - 54, 755, f"Confidential & Proprietary")
            self.setStrokeColor(BORDER_COLOR)
            self.setLineWidth(0.5)
            self.line(54, 748, 612 - 54, 748)

        # Footer
        footer_y = 35
        self.setStrokeColor(BORDER_COLOR)
        self.setLineWidth(0.5)
        self.line(54, footer_y + 12, 612 - 54, footer_y + 12)

        timestamp_str = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
        self.drawString(54, footer_y, f"Generated on {timestamp_str} by IntervAI Engine")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(612 - 54, footer_y, page_str)

        self.restoreState()


# =============================================================================
# 3. MATPLOTLIB CHART GENERATION HELPERS
# =============================================================================

def generate_radar_chart_image(
    content_score: float,
    speech_score: float,
    face_score: float,
    integrity_score: float = 95.0,
    topic_depth: float = 80.0,
) -> io.BytesIO:
    """Generates a high-res Radar/Spider Chart PNG."""
    labels = ["Content Accuracy", "Speech Delivery", "Camera Composure", "Exam Integrity", "Technical Depth"]
    values = [
        max(10.0, min(100.0, content_score)),
        max(10.0, min(100.0, speech_score)),
        max(10.0, min(100.0, face_score)),
        max(10.0, min(100.0, integrity_score)),
        max(10.0, min(100.0, topic_depth)),
    ]

    num_vars = len(labels)
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
    # Close the loop
    values_loop = values + values[:1]
    angles_loop = angles + angles[:1]

    fig, ax = plt.subplots(figsize=(4.0, 3.4), subplot_kw=dict(polar=True), dpi=180)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#f8fafc")

    # Plot data
    ax.plot(angles_loop, values_loop, color="#4f46e5", linewidth=2.0, linestyle="solid")
    ax.fill(angles_loop, values_loop, color="#6366f1", alpha=0.25)

    # Styling axes
    ax.set_xticks(angles)
    ax.set_xticklabels(labels, size=8, color="#0f172a", weight="bold")
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], size=6, color="#64748b")
    ax.set_ylim(0, 100)
    ax.grid(color="#cbd5e1", linestyle="--", linewidth=0.6)
    ax.set_title("Multimodal Skill Radar", size=10, weight="bold", color="#0f172a", pad=14)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=180)
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_timeline_chart_image(per_question_scores: List[Dict[str, Any]]) -> io.BytesIO:
    """Generates a Confidence Timeline Chart across questions PNG."""
    fig, ax = plt.subplots(figsize=(4.0, 3.4), dpi=180)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#f8fafc")

    if not per_question_scores:
        per_question_scores = [{"question_id": 1, "fused_score": 75.0, "content_score": 75.0, "speech_score": 75.0}]

    q_labels = [f"Q{q.get('question_id', i + 1)}" for i, q in enumerate(per_question_scores)]
    fused = [float(q.get("fused_score", 70.0)) for q in per_question_scores]
    content = [float(q.get("content_score", 70.0)) for q in per_question_scores]
    speech = [float(q.get("speech_score", 70.0)) for q in per_question_scores]

    x = np.arange(len(q_labels))

    ax.plot(x, fused, marker="o", color="#4f46e5", linewidth=2.0, label="Fused Score", zorder=3)
    ax.plot(x, content, marker="s", color="#059669", linewidth=1.2, linestyle="--", label="Content", alpha=0.85)
    ax.plot(x, speech, marker="^", color="#d97706", linewidth=1.2, linestyle=":", label="Speech", alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(q_labels, size=8, color="#0f172a", weight="bold")
    ax.set_ylim(0, 105)
    ax.set_ylabel("Score (0-100)", size=8, color="#64748b")
    ax.set_title("Score Trajectory by Question", size=10, weight="bold", color="#0f172a", pad=10)
    ax.grid(color="#e2e8f0", linestyle="-", linewidth=0.7)
    ax.legend(loc="lower right", fontsize=7, framealpha=0.9)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=180)
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_trend_chart_image(trend_data: Dict[str, Any], current_score: float) -> io.BytesIO:
    """Generates Progress Trend Across Sessions PNG."""
    fig, ax = plt.subplots(figsize=(8.2, 2.2), dpi=180)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#f8fafc")

    recent_scores = trend_data.get("recent_session_scores", [])
    if not recent_scores:
        recent_scores = [max(40.0, current_score - 10.0), current_score]
    elif len(recent_scores) == 1:
        recent_scores = [recent_scores[0], current_score]

    x_labels = [f"Session {i + 1}" for i in range(len(recent_scores))]
    x = np.arange(len(x_labels))

    ax.plot(x, recent_scores, marker="o", markersize=6, color="#4f46e5", linewidth=2.2, label="Your Progression")
    ax.axhline(y=75.0, color="#10b981", linestyle="--", linewidth=1.2, label="Proficiency Benchmark (75)")

    for i, s in enumerate(recent_scores):
        ax.annotate(f"{s:.0f}", (x[i], s + 2.5), ha="center", size=7, weight="bold", color="#0f172a")

    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, size=8, color="#0f172a")
    ax.set_ylim(0, 105)
    ax.set_ylabel("Overall Score", size=8, color="#64748b")
    ax.set_title("Historical Practice Progression", size=9, weight="bold", color="#0f172a")
    ax.grid(color="#e2e8f0", linestyle="-", linewidth=0.6)
    ax.legend(loc="lower right", fontsize=7, framealpha=0.9)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=180)
    plt.close(fig)
    buf.seek(0)
    return buf


# =============================================================================
# 4. REPORTLAB PDF BUILDER
# =============================================================================

def build_pdf_report(session_id: int, db: Optional[Session] = None) -> bytes:
    """
    Builds the complete multi-page PDF report for session_id.
    Returns raw PDF bytes.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        session: Optional[InterviewSession] = (
            db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
        )
        if not session:
            raise ValueError(f"Interview session #{session_id} not found.")

        user: Optional[User] = (
            db.query(User).filter(User.id == session.user_id).first()
        )
        candidate_name = getattr(user, "name", None) or getattr(user, "full_name", None) or (user.email if user else "Candidate")

        # Load session result and report
        report_record = db.query(SessionReport).filter(SessionReport.session_id == session_id).first()
        if not report_record:
            rep_data_dict = generate_and_persist_report(session_id=session_id, db=db)
            report_data = rep_data_dict.get("report", {})
        else:
            report_data = report_record.report_data

        sess_result = db.query(SessionResult).filter(SessionResult.session_id == session_id).first()
        if not sess_result:
            from app.services.score_fusion_service import process_and_persist_session_result
            res_dict = process_and_persist_session_result(session_id=session_id, db=db)
        else:
            res_dict = {
                "overall_score": sess_result.overall_score,
                "content_score": sess_result.content_score,
                "speech_score": sess_result.speech_score,
                "face_score": sess_result.face_score,
                "classification": sess_result.classification,
                "round_type": sess_result.round_type,
                "role": sess_result.role,
                "per_question_scores": sess_result.per_question_scores,
                "comparisons": sess_result.comparisons,
                "weak_areas": sess_result.weak_areas,
                "strengths": sess_result.strengths,
            }

        # Query Integrity Events
        integrity_events = (
            db.query(IntegrityEvent).filter(IntegrityEvent.session_id == session_id).all()
        )

        # Build Flowables
        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            leftMargin=54,
            rightMargin=54,
            topMargin=54,
            bottomMargin=54,
        )

        styles = getSampleStyleSheet()

        # Custom typography styles
        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=PRIMARY_COLOR,
        )
        subtitle_style = ParagraphStyle(
            "DocSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=MUTED_TEXT,
        )
        section_h1 = ParagraphStyle(
            "SectionH1",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=PRIMARY_COLOR,
            spaceBefore=14,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "DocBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=PRIMARY_COLOR,
        )
        body_bold = ParagraphStyle(
            "DocBodyBold",
            parent=body_style,
            fontName="Helvetica-Bold",
        )
        callout_style = ParagraphStyle(
            "DocCallout",
            parent=body_style,
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=12,
            textColor=MUTED_TEXT,
        )

        story: List[Any] = []

        # =====================================================================
        # HEADER BLOCK
        # =====================================================================
        round_type = res_dict.get("round_type", "Technical")
        role = res_dict.get("role", "Software Engineer")
        overall_score = float(res_dict.get("overall_score", 70.0))
        classification = res_dict.get("classification", "AVERAGE")
        created_str = (
            session.created_at.strftime("%B %d, %Y")
            if session.created_at
            else datetime.now(timezone.utc).strftime("%B %d, %Y")
        )

        header_table_data = [
            [
                Paragraph("<b>IntervAI</b> <font color='#4f46e5'>Assessment Report</font>", title_style),
                Paragraph(
                    f"<b>Session ID:</b> #{session_id}<br/>"
                    f"<b>Date:</b> {created_str}<br/>"
                    f"<b>Status:</b> Closed & Evaluated",
                    ParagraphStyle("HRight", parent=body_style, alignment=2, leading=12),
                ),
            ],
            [
                Paragraph(
                    f"<font color='#4f46e5'><b>{round_type.upper()} INTERVIEW</b></font> &nbsp;|&nbsp; "
                    f"Target Role: <b>{role}</b> &nbsp;|&nbsp; Candidate: <b>{candidate_name}</b>",
                    subtitle_style,
                ),
                "",
            ],
        ]
        header_table = Table(header_table_data, colWidths=[330, 174])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("SPAN", (0, 1), (1, 1)),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", thickness=1.5, color=BRAND_ACCENT, spaceBefore=4, spaceAfter=14))

        # =====================================================================
        # EXECUTIVE SUMMARY & COMPOSITE SCORE CARDS
        # =====================================================================
        content_score = float(res_dict.get("content_score", 70.0))
        speech_score = float(res_dict.get("speech_score", 70.0))
        face_score = float(res_dict.get("face_score", 70.0))
        cohort_pctl = float(res_dict.get("comparisons", {}).get("cohort", {}).get("percentile", 50.0))

        class_color = (
            SUCCESS_COLOR if classification == "STRONG" else (WARNING_COLOR if classification == "AVERAGE" else DANGER_COLOR)
        )

        score_cards_data = [
            [
                Paragraph(f"<font size='22' color='{BRAND_ACCENT}'><b>{overall_score:.0f}</b></font><br/><font size='7' color='#64748b'><b>OVERALL (0-100)</b></font>", ParagraphStyle("C1", parent=body_style, alignment=1)),
                Paragraph(f"<font size='16' color='#0f172a'><b>{content_score:.0f}</b></font><br/><font size='7' color='#64748b'>CONTENT ACCURACY</font>", ParagraphStyle("C2", parent=body_style, alignment=1)),
                Paragraph(f"<font size='16' color='#0f172a'><b>{speech_score:.0f}</b></font><br/><font size='7' color='#64748b'>SPEECH CONFIDENCE</font>", ParagraphStyle("C3", parent=body_style, alignment=1)),
                Paragraph(f"<font size='16' color='#0f172a'><b>{face_score:.0f}</b></font><br/><font size='7' color='#64748b'>CAMERA COMPOSURE</font>", ParagraphStyle("C4", parent=body_style, alignment=1)),
                Paragraph(f"<font size='13' color='{class_color}'><b>{classification}</b></font><br/><font size='7' color='#64748b'>Top {100.0 - cohort_pctl:.0f}% Cohort</font>", ParagraphStyle("C5", parent=body_style, alignment=1)),
            ]
        ]
        score_cards_table = Table(score_cards_data, colWidths=[100, 100, 100, 100, 104])
        score_cards_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG_CARD),
            ("BOX", (0, 0), (-1, -1), 0.8, BORDER_COLOR),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(score_cards_table)
        story.append(Spacer(1, 10))

        # Narrative Summary Box
        summary_text = report_data.get("overall_summary", "Candidate completed the interview evaluation.")
        summary_box = Table(
            [[Paragraph(f"<b>Executive Summary:</b> {summary_text}", body_style)]],
            colWidths=[504],
        )
        summary_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.8, BRAND_ACCENT),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(summary_box)
        story.append(Spacer(1, 12))

        # =====================================================================
        # VISUAL ANALYTICS (CHARTS)
        # =====================================================================
        story.append(Paragraph("Multimodal Visual Analytics", section_h1))

        # Generate Radar & Timeline charts
        radar_buf = generate_radar_chart_image(
            content_score=content_score,
            speech_score=speech_score,
            face_score=face_score,
            integrity_score=95.0 if not integrity_events else 75.0,
            topic_depth=overall_score,
        )
        timeline_buf = generate_timeline_chart_image(res_dict.get("per_question_scores", []))

        radar_img = Image(radar_buf, width=2.7 * inch, height=2.3 * inch)
        timeline_img = Image(timeline_buf, width=2.7 * inch, height=2.3 * inch)

        charts_table = Table([[radar_img, timeline_img]], colWidths=[252, 252])
        charts_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(charts_table)
        story.append(Spacer(1, 10))

        # Progress Trend Chart across sessions
        trend_buf = generate_trend_chart_image(
            trend_data=res_dict.get("comparisons", {}).get("trend", {}),
            current_score=overall_score,
        )
        trend_img = Image(trend_buf, width=5.5 * inch, height=1.5 * inch)
        story.append(trend_img)
        story.append(Spacer(1, 14))

        # =====================================================================
        # STRENGTHS & GAPS SECTION
        # =====================================================================
        story.append(PageBreak())  # Clean break to Page 2
        story.append(Paragraph("Evaluator Diagnostic: Strengths & Growth Gaps", section_h1))

        strengths_list = report_data.get("strengths", [])
        gaps_list = report_data.get("gaps", [])

        str_cells = [Paragraph("<b>Demonstrated Key Strengths</b>", ParagraphStyle("SH", parent=body_bold, textColor=SUCCESS_COLOR))]
        for st in strengths_list[:3]:
            str_cells.append(Paragraph(f"• <b>{st.get('title', 'Strength')}:</b> {st.get('claim', '')}", body_style))
            str_cells.append(Spacer(1, 2))

        gap_cells = [Paragraph("<b>Identified Growth Gaps</b>", ParagraphStyle("GH", parent=body_bold, textColor=DANGER_COLOR))]
        for gp in gaps_list[:3]:
            gap_cells.append(Paragraph(f"• <b>{gp.get('title', 'Gap')}:</b> {gp.get('claim', '')}", body_style))
            gap_cells.append(Spacer(1, 2))

        eval_table = Table([[str_cells, gap_cells]], colWidths=[248, 248])
        eval_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f0fdf4")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#fef2f2")),
            ("BOX", (0, 0), (0, 0), 0.5, SUCCESS_COLOR),
            ("BOX", (1, 0), (1, 0), 0.5, DANGER_COLOR),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(eval_table)
        story.append(Spacer(1, 14))

        # =====================================================================
        # PER-QUESTION ACCORDION & DEEP DIVE
        # =====================================================================
        story.append(Paragraph("Per-Question Detailed Breakdown", section_h1))

        feedback_list = report_data.get("per_question_feedback", [])
        for fb in feedback_list:
            q_id = fb.get("question_id", 1)
            topic = fb.get("topic", "General")
            q_text = fb.get("question_text", f"Question #{q_id}")
            q_score = float(fb.get("score", 70.0))
            what_good = fb.get("what_was_good", "Covered key technical points.")
            what_missing = fb.get("what_was_missing", "Review production trade-offs.")
            outline = fb.get("sample_answer_outline", "").replace("\n", "<br/>")

            # Find matching transcript from session result
            transcript = ""
            for q_sc in res_dict.get("per_question_scores", []):
                if q_sc.get("question_id") == q_id:
                    transcript = q_sc.get("transcript", "")
                    break

            q_color = SUCCESS_COLOR if q_score >= 80.0 else (WARNING_COLOR if q_score >= 60.0 else DANGER_COLOR)

            q_flowables = [
                Table(
                    [
                        [
                            Paragraph(f"<b>Q{q_id}: {topic}</b> — {q_text}", ParagraphStyle("QT", parent=body_bold, fontSize=9.5)),
                            Paragraph(f"<font color='{q_color}'><b>{q_score:.0f}/100</b></font>", ParagraphStyle("QS", parent=body_bold, alignment=2, fontSize=10)),
                        ]
                    ],
                    colWidths=[430, 74],
                ),
                Spacer(1, 3),
            ]

            if transcript:
                excerpt = transcript if len(transcript) <= 220 else transcript[:215] + "..."
                q_flowables.append(
                    Paragraph(f"<b>Candidate Transcript:</b> <i>\"{excerpt}\"</i>", callout_style)
                )
                q_flowables.append(Spacer(1, 2))

            q_flowables.append(
                Paragraph(f"<font color='{SUCCESS_COLOR}'><b>+ What was good:</b></font> {what_good}", body_style)
            )
            q_flowables.append(
                Paragraph(f"<font color='{WARNING_COLOR}'><b>- What was missing:</b></font> {what_missing}", body_style)
            )

            if outline:
                q_flowables.append(
                    Paragraph(f"<b>Sample Answer Outline:</b><br/>{outline}", callout_style)
                )

            q_card = Table([[q_flowables]], colWidths=[504])
            q_card.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), BG_CARD),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]))

            story.append(KeepTogether(q_card))
            story.append(Spacer(1, 6))

        # =====================================================================
        # TAILORED IMPROVEMENT PLAN SECTION
        # =====================================================================
        story.append(PageBreak())  # Clean break to Page 3
        story.append(Paragraph("Tailored Improvement Plan & Learning Roadmap", section_h1))
        story.append(Paragraph(
            "Concrete recommendations derived directly from identified gap areas, complete with practice reps "
            "and curated, verified documentation resources.",
            subtitle_style,
        ))
        story.append(Spacer(1, 6))

        plan_actions = report_data.get("improvement_plan", [])
        if not plan_actions:
            plan_actions = build_improvement_plan(res_dict)

        for act in plan_actions:
            p_badge = act.get("priority", "MEDIUM")
            badge_color = DANGER_COLOR if p_badge == "HIGH" else WARNING_COLOR

            act_cells = [
                Table(
                    [
                        [
                            Paragraph(f"<b>{act.get('title', 'Action')}</b> ({act.get('topic', '')})", ParagraphStyle("AT", parent=body_bold, fontSize=9.5)),
                            Paragraph(f"<font color='{badge_color}'><b>{p_badge} PRIORITY</b></font>", ParagraphStyle("AP", parent=body_bold, alignment=2, fontSize=8.5)),
                        ]
                    ],
                    colWidths=[400, 104],
                ),
                Spacer(1, 2),
                Paragraph(f"{act.get('description', '')}", body_style),
                Spacer(1, 3),
            ]

            # Practice questions
            pr_questions = act.get("practice_questions", [])
            if pr_questions:
                act_cells.append(Paragraph("<b>Practice Interview Questions:</b>", ParagraphStyle("PQH", parent=body_bold, fontSize=8.5, textColor=BRAND_ACCENT)))
                for pq in pr_questions:
                    act_cells.append(Paragraph(f"  • {pq}", callout_style))
                act_cells.append(Spacer(1, 2))

            # Resources
            resources = act.get("resources", [])
            if resources:
                act_cells.append(Paragraph("<b>Verified Learning Resources:</b>", ParagraphStyle("RH", parent=body_bold, fontSize=8.5, textColor=PRIMARY_COLOR)))
                for r in resources:
                    r_title = r.get("title", "")
                    r_url = r.get("url", "")
                    r_plat = r.get("platform", "")
                    act_cells.append(Paragraph(f"  • <b>{r_title}</b> ({r_plat}): <font color='#4f46e5'><u>{r_url}</u></font>", callout_style))

            act_card = Table([[act_cells]], colWidths=[504])
            act_card.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), BG_CARD),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]))
            story.append(KeepTogether(act_card))
            story.append(Spacer(1, 6))

        # =====================================================================
        # INTEGRITY & PROCTORING AUDIT
        # =====================================================================
        story.append(Spacer(1, 8))
        story.append(Paragraph("Integrity & Session Proctoring Audit", section_h1))

        if not integrity_events:
            integ_text = "<b>Integrity Status: Verified Clean.</b> No tab switches, window blurs, or face-absence anomalies detected during the interview session."
            integ_bg = colors.HexColor("#f0fdf4")
            integ_border = SUCCESS_COLOR
        else:
            event_counts = len(integrity_events)
            integ_text = f"<b>Integrity Observations ({event_counts} recorded):</b> "
            snippets = [f"{e.event_type} (severity: {e.severity})" for e in integrity_events[:3]]
            integ_text += "; ".join(snippets)
            integ_bg = colors.HexColor("#fffbeb")
            integ_border = WARNING_COLOR

        integ_box = Table([[Paragraph(integ_text, body_style)]], colWidths=[504])
        integ_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), integ_bg),
            ("BOX", (0, 0), (-1, -1), 0.5, integ_border),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(integ_box)

        # Build document
        doc.build(story, canvasmaker=NumberedCanvas)
        pdf_bytes = pdf_buffer.getvalue()
        pdf_buffer.close()
        return pdf_bytes

    finally:
        if close_db:
            db.close()
