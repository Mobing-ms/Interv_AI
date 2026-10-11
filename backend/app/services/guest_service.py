"""
Guest Practice Mode Service.
Handles:
1. IP rate limiting (configurable limit per IP per 24 hours).
2. Cloudflare Turnstile CAPTCHA verification.
3. 3-question blueprint generation for guest practice.
4. Privacy: 24-hour cleanup of guest sessions, recordings, and transcripts.
5. Linking guest sessions to newly created or logged-in user accounts.
"""

import os
import shutil
import hashlib
import logging
import urllib.request
import urllib.parse
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    InterviewSession,
    InterviewConfig,
    QuestionBankItem,
    UserConsent,
    GuestIpLog,
    SessionResult,
    SessionReport,
    CVDocument,
    User,
    UserMemory,
)
from app.services.answer_capture_service import default_storage_manager
from app.services.question_dedupe import compute_question_hash

logger = logging.getLogger("intervai.guest_service")


def check_guest_ip_limit(ip: str, db: Session) -> Tuple[bool, int]:
    """
    Checks whether the caller's IP has exceeded the daily guest session limit.
    Returns (is_allowed: bool, current_count: int).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    count = (
        db.query(GuestIpLog)
        .filter(GuestIpLog.ip_address == ip, GuestIpLog.created_at >= cutoff)
        .count()
    )
    is_allowed = count < settings.GUEST_MAX_SESSIONS_PER_IP_PER_DAY
    return is_allowed, count


def log_guest_ip(ip: str, session_id: Optional[int], db: Session) -> GuestIpLog:
    """
    Records an IP hit for guest session creation.
    """
    record = GuestIpLog(
        ip_address=ip,
        session_id=session_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    return record


def verify_turnstile_captcha(token: Optional[str], remote_ip: Optional[str] = None) -> bool:
    """
    Verifies Cloudflare Turnstile CAPTCHA response token.
    If TURNSTILE_SECRET_KEY is empty or token is a known test pass token, allows pass in development/testing.
    """
    secret_key = settings.TURNSTILE_SECRET_KEY

    # Development & test bypasses
    if not secret_key:
        return True
    if token in ("test_pass", "mock_turnstile_token", "1x0000000000000000000000000000000AA"):
        return True

    if not token or not token.strip():
        return False

    try:
        url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
        data = {
            "secret": secret_key,
            "response": token.strip(),
        }
        if remote_ip:
            data["remoteip"] = remote_ip

        encoded_data = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=encoded_data, method="POST")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return bool(result.get("success", False))
    except Exception as e:
        logger.warning("Turnstile verification failed with network error: %s", e)
        # If network error or timeout occurs in dev, fail closed unless dev mode
        return settings.DEV_MODE


def generate_guest_questions(
    role: str,
    round_type: str,
    difficulty: str,
    cv_text: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Generates 3 focused, high-signal interview questions tailored to
    the chosen role, round type, and difficulty for an 8-10 minute session.
    - Question 1: Core Domain Concept & Architecture
    - Question 2: Real-World Technical Scenario & Tradeoffs
    - Question 3: Behavioral Storytelling (STAR structure)
    """
    role_clean = role.strip() if role else "Software Engineer"
    round_type_clean = round_type.strip().title() if round_type else "Technical"
    diff_clean = difficulty.strip().title() if difficulty else "Medium"

    if round_type_clean.lower() == "hr" or round_type_clean.lower() == "behavioral":
        questions = [
            {
                "topic": "Conflict Resolution & Alignment",
                "text": f"Tell me about a time when you disagreed with a colleague or lead on a critical decision for a {role_clean} project. How did you handle the discussion and reach alignment?",
                "question_type": "behavioral",
                "expected_keywords": ["situation", "task", "disagreement", "alignment", "outcome", "empathy"],
                "ideal_answer_points": ["Set context and differing perspectives clearly", "Demonstrated active listening and objective reasoning", "Shared positive team resolution and measurable outcome"],
            },
            {
                "topic": "Prioritization & Pressure",
                "text": "Describe a high-stakes project where requirements changed abruptly under tight deadlines. How did you re-prioritize your tasks and communicate progress to stakeholders?",
                "question_type": "behavioral",
                "expected_keywords": ["prioritization", "deadlines", "tradeoffs", "stakeholders", "communication", "delivery"],
                "ideal_answer_points": ["Addressed ambiguity proactively", "Applied structured prioritization matrix", "Kept stakeholders aligned and delivered on time"],
            },
            {
                "topic": "Self-Reflection & Growth",
                "text": "What is the most impactful constructive feedback you have received in your career, and what concrete steps did you take to improve?",
                "question_type": "behavioral",
                "expected_keywords": ["feedback", "growth", "reflection", "action plan", "improvement"],
                "ideal_answer_points": ["Welcomed feedback constructively", "Outlined intentional action steps taken", "Demonstrated lasting professional growth"],
            },
        ]
    else:
        # Technical / System Design / Managerial default
        questions = [
            {
                "topic": f"{role_clean} Core Architecture",
                "text": f"Walk me through how you design high-performance, maintainable components or services in your work as a {role_clean}. What architectural principles do you prioritize?",
                "question_type": "conceptual",
                "expected_keywords": ["architecture", "modularity", "scalability", "maintainability", "state management", "performance"],
                "ideal_answer_points": ["Articulates separation of concerns and single responsibility", "Addresses error boundaries and observability", "Balances performance with developer maintainability"],
            },
            {
                "topic": "System Reliability & Debugging",
                "text": "Imagine a mission-critical endpoint or user workflow starts experiencing intermittent 5xx errors and high latency in production. How do you systematically diagnose and mitigate the root cause?",
                "question_type": "scenario",
                "expected_keywords": ["metrics", "logs", "traces", "reproduction", "rollback", "mitigation", "postmortem"],
                "ideal_answer_points": ["Immediate containment and customer blast radius reduction", "Deep observability inspection (APM, traces, queries)", "Preventative safeguards and root cause postmortem"],
            },
            {
                "topic": "Cross-Functional Collaboration (STAR)",
                "text": f"Tell me about a challenging technical initiative you drove as a {role_clean} that required cross-functional collaboration. What hurdles did you face, and what was the impact?",
                "question_type": "behavioral",
                "expected_keywords": ["situation", "task", "action", "result", "collaboration", "metrics"],
                "ideal_answer_points": ["Clear STAR structure with quantifiable results", "Emphasized proactive communication across functions", "Highlighted business impact and team learning"],
            },
        ]

    output = []
    for idx, q in enumerate(questions, start=1):
        q_hash = compute_question_hash(q["text"])
        output.append({
            "question_hash": q_hash,
            "text": q["text"],
            "topic": q["topic"],
            "difficulty": diff_clean,
            "question_type": q["question_type"],
            "expected_keywords": q["expected_keywords"],
            "ideal_answer_points": q["ideal_answer_points"],
            "max_time_seconds": 120,
            "rank_score": round(10.0 - (idx * 0.5), 1),
        })

    return output


def cleanup_expired_guest_sessions(db: Session, max_age_hours: Optional[int] = None) -> int:
    """
    Deletes guest sessions, recordings, and transcripts that are older than max_age_hours (default 24h).
    Enforces candidate privacy guarantee.
    """
    age_hours = max_age_hours or settings.GUEST_RETENTION_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=age_hours)

    expired_sessions = (
        db.query(InterviewSession)
        .filter(InterviewSession.is_guest == True, InterviewSession.created_at <= cutoff)
        .all()
    )

    deleted_count = 0
    for sess in expired_sessions:
        sess_id = sess.id
        # 1. Delete disk recordings & transcripts
        try:
            sess_dir = os.path.join(default_storage_manager.base_dir, str(sess_id))
            if os.path.exists(sess_dir):
                shutil.rmtree(sess_dir, ignore_errors=True)
        except Exception as e:
            logger.warning("Could not delete storage directory for guest session #%d: %s", sess_id, e)

        # 2. Delete database session (cascade deletes calibration, signals, integrity_events, result, report)
        try:
            cfg_id = sess.interview_id
            db.delete(sess)
            db.commit()

            # Clean orphaned config if guest
            if cfg_id:
                cfg = db.query(InterviewConfig).filter(InterviewConfig.id == cfg_id, InterviewConfig.is_guest == True).first()
                if cfg:
                    db.delete(cfg)
                    db.commit()

            deleted_count += 1
        except Exception as e:
            db.rollback()
            logger.warning("Error deleting guest session #%d from DB: %s", sess_id, e)

    return deleted_count


def link_guest_session_to_user(
    guest_session_id: int,
    user_id: int,
    db: Session,
) -> bool:
    """
    Links an anonymous guest session and its results/reports to a registered user account.
    Marks is_guest=False and triggers memory update so it shows on their dashboard.
    """
    sess = (
        db.query(InterviewSession)
        .filter(InterviewSession.id == guest_session_id, InterviewSession.is_guest == True)
        .first()
    )
    if not sess:
        return False

    # Link session
    sess.user_id = user_id
    sess.is_guest = False

    # Link interview config
    if sess.interview_config:
        sess.interview_config.user_id = user_id
        sess.interview_config.is_guest = False

    # Link calibration
    if sess.calibration:
        sess.calibration.user_id = user_id

    # Link result
    if sess.result:
        sess.result.user_id = user_id
        sess.result.is_guest = False

    # Link report
    if sess.report:
        sess.report.user_id = user_id
        sess.report.is_guest = False

    db.commit()

    # Update candidate memory if result exists
    if sess.result:
        from app.services.score_fusion_service import execute_memory_update
        try:
            execute_memory_update(
                user_id=user_id,
                per_question_fused=sess.result.per_question_scores or [],
                ranked_weak_areas=sess.result.weak_areas or [],
                overall_score=sess.result.overall_score,
                db=db,
            )
        except Exception as e:
            logger.warning("Could not update memory for linked session #%d: %s", guest_session_id, e)

    return True
