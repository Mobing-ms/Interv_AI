"""
Score Fusion, Comparison & Memory Update Engine (Phase 5.3).
- Score Fusion: Weighted combination of content, speech, and face scores based on round type
  (e.g., Technical: content-heavy; HR/Behavioral: communication/speech/face heavy).
- Comparisons:
  - Candidate's own baseline & chronological trend across past sessions.
  - Cohort percentile rank against peers in same round type and role (with labeled seeded benchmarks when data < 5).
- Weak-Area Ranking:
  - Ranks topics/skills by lowest scores, repeated weakness across sessions, and integrity/confidence issues.
  - Outputs top 3-5 weak areas with question IDs, scores, and exact deduction evidence.
- U Memory Update:
  - Persists SessionResult record.
  - Updates UserMemory (topic averages, weak tags, session count).
  - Logs AskedQuestion history with question hashes and scores.
"""

import math
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    InterviewSession,
    InterviewConfig,
    TargetProfile,
    SessionResult,
    UserMemory,
    AskedQuestion,
    IntegrityEvent,
)
from app.services.scoring_engine import compute_session_scores
from app.services.question_dedupe import compute_question_hash, normalize_question_text

logger = logging.getLogger("intervai.score_fusion")


# =============================================================================
# 1. ROUND-TYPE WEIGHT DEFINITIONS
# =============================================================================

ROUND_TYPE_WEIGHTS: Dict[str, Dict[str, float]] = {
    # Technical interviews: heavy focus on technical accuracy and depth
    "technical": {
        "content": 0.60,
        "speech": 0.25,
        "face": 0.15,
    },
    # HR / Behavioral / Leadership interviews: high focus on communication and composure
    "hr": {
        "content": 0.35,
        "speech": 0.35,
        "face": 0.30,
    },
    "behavioral": {
        "content": 0.35,
        "speech": 0.35,
        "face": 0.30,
    },
    "situational": {
        "content": 0.35,
        "speech": 0.35,
        "face": 0.30,
    },
    # Managerial / Leadership: balanced technical leadership and communication
    "managerial": {
        "content": 0.45,
        "speech": 0.35,
        "face": 0.20,
    },
    "leadership": {
        "content": 0.45,
        "speech": 0.35,
        "face": 0.20,
    },
    # System design: architectural content focus
    "system design": {
        "content": 0.55,
        "speech": 0.30,
        "face": 0.15,
    },
    "system_design": {
        "content": 0.55,
        "speech": 0.30,
        "face": 0.15,
    },
    # Default balanced weights
    "default": {
        "content": 0.50,
        "speech": 0.30,
        "face": 0.20,
    },
}


def get_round_type_weights(round_type: Optional[str]) -> Dict[str, float]:
    """Retrieves normalized weights (content, speech, face) for a given round type."""
    if not round_type:
        return dict(ROUND_TYPE_WEIGHTS["default"])

    key = str(round_type).strip().lower()
    for pattern, w in ROUND_TYPE_WEIGHTS.items():
        if pattern in key:
            return dict(w)

    return dict(ROUND_TYPE_WEIGHTS["default"])


# =============================================================================
# 2. SCORE FUSION (PURE FUNCTION)
# =============================================================================

def fuse_session_scores(
    raw_scoring_report: Dict[str, Any],
    round_type: str,
    custom_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Computes fused per-question and overall session scores using round-type weights.
    Returns structured results including weights_used and updated classifications.
    """
    weights = custom_weights or get_round_type_weights(round_type)
    w_content = weights.get("content", 0.50)
    w_speech = weights.get("speech", 0.30)
    w_face = weights.get("face", 0.20)

    # Normalize weights so they sum exactly to 1.0
    w_sum = w_content + w_speech + w_face
    if w_sum > 0:
        w_content = round(w_content / w_sum, 3)
        w_speech = round(w_speech / w_sum, 3)
        w_face = round(1.0 - w_content - w_speech, 3)

    weights_used = {"content": w_content, "speech": w_speech, "face": w_face}

    questions_fused = []
    content_list = []
    speech_list = []
    face_list = []
    composite_list = []

    for q in raw_scoring_report.get("per_question_breakdown", []):
        c_score = float(q.get("content", {}).get("score", 70.0))
        s_score = float(q.get("speech_confidence", {}).get("score", 70.0))
        f_score = float(q.get("face_posture", {}).get("score", 70.0))

        # Calculate fused question score
        q_fused = round((c_score * w_content) + (s_score * w_speech) + (f_score * w_face), 1)
        q_fused = max(0.0, min(100.0, q_fused))

        content_list.append(c_score)
        speech_list.append(s_score)
        face_list.append(f_score)
        composite_list.append(q_fused)

        q_copy = dict(q)
        q_copy["fused_score"] = q_fused
        q_copy["weights_used"] = weights_used
        questions_fused.append(q_copy)

    if composite_list:
        avg_content = round(sum(content_list) / len(content_list), 1)
        avg_speech = round(sum(speech_list) / len(speech_list), 1)
        avg_face = round(sum(face_list) / len(face_list), 1)
        overall_fused = round((avg_content * w_content) + (avg_speech * w_speech) + (avg_face * w_face), 1)
        overall_fused = max(0.0, min(100.0, overall_fused))
    else:
        avg_content = 0.0
        avg_speech = 0.0
        avg_face = 0.0
        overall_fused = 0.0

    if overall_fused >= 80.0:
        classification = "STRONG"
    elif overall_fused >= 60.0:
        classification = "AVERAGE"
    else:
        classification = "WEAK"

    return {
        "round_type": round_type,
        "weights_used": weights_used,
        "overall_scores": {
            "content_score": avg_content,
            "speech_confidence_score": avg_speech,
            "face_posture_score": avg_face,
            "composite_score": overall_fused,
        },
        "classification": classification,
        "per_question_breakdown": questions_fused,
        "top_deductions": raw_scoring_report.get("top_deductions", []),
        "key_strengths": raw_scoring_report.get("key_strengths", []),
        "total_questions": len(questions_fused),
    }


# =============================================================================
# 3. COMPARISON ENGINE (BASELINE, TREND & COHORT PERCENTILE)
# =============================================================================

# Industry standard seeded cohorts used when database cohort size < 5
SEEDED_BENCHMARKS: Dict[str, Dict[str, float]] = {
    "technical": {"mean": 71.5, "std": 12.5},
    "hr": {"mean": 74.0, "std": 11.0},
    "behavioral": {"mean": 74.0, "std": 11.0},
    "system design": {"mean": 68.0, "std": 13.5},
    "default": {"mean": 72.0, "std": 12.0},
}


def compute_cohort_percentile(score: float, round_type: str, past_cohort_scores: List[float]) -> Dict[str, Any]:
    """
    Computes candidate's cohort percentile rank.
    If fewer than 5 recorded sessions in cohort, uses a calibrated industry standard benchmark.
    """
    if len(past_cohort_scores) >= 5:
        # Empirical percentile from platform candidates
        below_count = sum(1 for s in past_cohort_scores if s <= score)
        percentile = round((below_count / len(past_cohort_scores)) * 100.0, 1)
        percentile = max(1.0, min(99.0, percentile))
        cohort_mean = round(sum(past_cohort_scores) / len(past_cohort_scores), 1)

        return {
            "percentile": percentile,
            "cohort_mean": cohort_mean,
            "cohort_size": len(past_cohort_scores),
            "is_seeded_benchmark": False,
            "benchmark_label": f"Platform Cohort ({len(past_cohort_scores)} candidates in {round_type.title()})",
            "delta_vs_cohort": round(score - cohort_mean, 1),
        }

    # Fallback to seeded industry benchmark
    key = str(round_type).lower()
    bench = SEEDED_BENCHMARKS.get("default")
    for b_key, b_val in SEEDED_BENCHMARKS.items():
        if b_key in key:
            bench = b_val
            break

    mean = bench["mean"]
    std = bench["std"]

    # Compute normal CDF: percentile = 0.5 * (1 + erf((x - mean)/(std * sqrt(2))))
    z = (score - mean) / max(1.0, std * math.sqrt(2.0))
    cdf = 0.5 * (1.0 + math.erf(z))
    percentile = round(max(2.0, min(99.0, cdf * 100.0)), 1)
    delta_vs_cohort = round(score - mean, 1)

    return {
        "percentile": percentile,
        "cohort_mean": mean,
        "cohort_size": len(past_cohort_scores),
        "is_seeded_benchmark": True,
        "benchmark_label": f"Industry Standard Benchmark ({round_type.title()} Cohort)",
        "delta_vs_cohort": delta_vs_cohort,
    }


def compute_session_comparisons(
    user_id: int,
    session_id: int,
    current_score: float,
    round_type: str,
    role: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Computes comparisons against:
    1. User's own baseline (previous sessions)
    2. Trend trajectory across chronological sessions
    3. Cohort percentile rank
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        # 1. User's own past sessions
        past_user_results = (
            db.query(SessionResult)
            .filter(SessionResult.user_id == user_id, SessionResult.session_id != session_id)
            .order_by(SessionResult.created_at.asc())
            .all()
        )

        if past_user_results:
            past_scores = [r.overall_score for r in past_user_results]
            user_baseline = round(sum(past_scores) / len(past_scores), 1)
            delta_baseline = round(current_score - user_baseline, 1)
            sign = "+" if delta_baseline >= 0 else ""
            baseline_text = f"{sign}{delta_baseline} pts vs personal baseline ({user_baseline})"
            is_first_session = False
        else:
            user_baseline = 70.0
            delta_baseline = round(current_score - 70.0, 1)
            sign = "+" if delta_baseline >= 0 else ""
            baseline_text = f"First completed session (reference target: 70.0)"
            is_first_session = True

        # 2. Trend across sessions
        timeline = []
        for r in past_user_results:
            timeline.append({
                "session_id": r.session_id,
                "score": r.overall_score,
                "round_type": r.round_type,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            })
        timeline.append({
            "session_id": session_id,
            "score": current_score,
            "round_type": round_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        if len(timeline) >= 2:
            scores_timeline = [t["score"] for t in timeline]
            trend_delta = round(scores_timeline[-1] - scores_timeline[0], 1)
            if trend_delta > 2.0:
                trend_direction = "improving"
            elif trend_delta < -2.0:
                trend_direction = "declining"
            else:
                trend_direction = "stable"
        else:
            trend_direction = "baseline_established"
            trend_delta = 0.0

        # 3. Cohort Percentile
        cohort_results = (
            db.query(SessionResult)
            .filter(SessionResult.round_type.ilike(f"%{round_type[:4]}%"), SessionResult.session_id != session_id)
            .all()
        )
        cohort_scores = [c.overall_score for c in cohort_results]
        cohort_comparison = compute_cohort_percentile(current_score, round_type, cohort_scores)

        return {
            "baseline": {
                "user_baseline_score": user_baseline,
                "delta": delta_baseline,
                "is_first_session": is_first_session,
                "summary": baseline_text,
                "total_past_sessions": len(past_user_results),
            },
            "trend": {
                "direction": trend_direction,
                "trend_delta": trend_delta,
                "timeline": timeline,
                "summary": f"Performance is {trend_direction} ({'+' if trend_delta >= 0 else ''}{trend_delta} pts across {len(timeline)} sessions).",
            },
            "cohort": cohort_comparison,
        }

    finally:
        if close_db:
            db.close()


# =============================================================================
# 4. WEAK-AREA RANKING WITH EVIDENCE
# =============================================================================

def rank_weak_areas(
    per_question_fused: List[Dict[str, Any]],
    user_past_weak_topics: Optional[List[str]] = None,
    integrity_events: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Ranks topics and skills by lowest scores, repeated weakness across sessions,
    and repeated integrity or confidence issues.
    Outputs top 3-5 weak areas with question IDs, scores, and exact deduction evidence.
    """
    past_weaks = [t.lower() for t in (user_past_weak_topics or [])]
    integrity_count = len(integrity_events or [])

    # Group scores and deductions by topic
    topic_data: Dict[str, Dict[str, Any]] = {}

    for q in per_question_fused:
        topic = str(q.get("topic", "General")).strip()
        q_id = q.get("question_id", 1)
        q_text = q.get("question_text", f"Question #{q_id}")
        f_score = float(q.get("fused_score", 70.0))
        c_score = float(q.get("content", {}).get("score", 70.0))
        s_score = float(q.get("speech_confidence", {}).get("score", 70.0))
        f_face = float(q.get("face_posture", {}).get("score", 70.0))

        if topic not in topic_data:
            topic_data[topic] = {
                "topic": topic,
                "scores": [],
                "questions": [],
                "deductions": [],
            }

        topic_data[topic]["scores"].append(f_score)
        topic_data[topic]["questions"].append({
            "question_id": q_id,
            "question_text": q_text,
            "score": f_score,
            "content_score": c_score,
            "speech_score": s_score,
            "face_score": f_face,
            "deductions": [d.get("reason", "") for d in q.get("all_deductions", [])[:2]],
        })
        topic_data[topic]["deductions"].extend(q.get("all_deductions", []))

    # Also detect global communication / behavioral weak areas
    all_deductions = []
    for q in per_question_fused:
        all_deductions.extend(q.get("all_deductions", []))

    # Check for speech pace issues
    pace_deds = [d for d in all_deductions if d.get("factor") == "speech_pace"]
    if len(pace_deds) >= 1 and sum(d.get("deduction", 0) for d in pace_deds) <= -5.0:
        topic_data["Speech Pacing & Cadence"] = {
            "topic": "Speech Pacing & Cadence",
            "scores": [65.0 - abs(sum(d.get("deduction", 0) for d in pace_deds))],
            "questions": [{
                "question_id": d.get("question_id", 1),
                "question_text": "Interview Speaking Pace",
                "score": round(65.0 - abs(d.get("deduction", 0)), 1),
                "deductions": [d.get("reason", "")],
            } for d in pace_deds[:2]],
            "deductions": pace_deds,
        }

    # Check for filler word usage
    filler_deds = [d for d in all_deductions if d.get("factor") == "filler_rate"]
    if len(filler_deds) >= 1 and sum(d.get("deduction", 0) for d in filler_deds) <= -6.0:
        topic_data["Filler Words & Hesitation"] = {
            "topic": "Filler Words & Hesitation",
            "scores": [60.0 - abs(sum(d.get("deduction", 0) for d in filler_deds))],
            "questions": [{
                "question_id": d.get("question_id", 1),
                "question_text": "Vocal Fluency",
                "score": round(60.0 - abs(d.get("deduction", 0)), 1),
                "deductions": [d.get("reason", "")],
            } for d in filler_deds[:2]],
            "deductions": filler_deds,
        }

    # Check for STAR structure gaps
    star_deds = [d for d in all_deductions if d.get("factor") == "star_structure"]
    if star_deds:
        topic_data["STAR Behavioral Structuring"] = {
            "topic": "STAR Behavioral Structuring",
            "scores": [55.0],
            "questions": [{
                "question_id": d.get("question_id", 1),
                "question_text": "Behavioral Storytelling",
                "score": 55.0,
                "deductions": [d.get("reason", "")],
            } for d in star_deds[:2]],
            "deductions": star_deds,
        }

    # Check for integrity flags
    if integrity_count >= 1:
        topic_data["Interview Presence & Environment"] = {
            "topic": "Interview Presence & Environment",
            "scores": [50.0],
            "questions": [{
                "question_id": 1,
                "question_text": "Test Environment Monitoring",
                "score": 50.0,
                "deductions": [f"Detected {integrity_count} integrity events (tab switches or camera interruptions)."],
            }],
            "deductions": [{"reason": f"{integrity_count} integrity interruptions detected."}],
        }

    ranked_items = []
    for name, item in topic_data.items():
        avg_score = round(sum(item["scores"]) / max(1, len(item["scores"])), 1)
        is_repeated = any(w in name.lower() or name.lower() in w for w in past_weaks)
        rep_count = 2 if is_repeated else 1

        # Priority calculation: higher deficit + repetition + integrity gets higher priority
        deficit = max(0.0, 100.0 - avg_score)
        rep_boost = 25.0 if is_repeated else 0.0
        integrity_boost = 15.0 if "Integrity" in name or "Environment" in name else 0.0
        rank_weight = deficit + rep_boost + integrity_boost

        # Assign severity
        if avg_score < 55.0 or (is_repeated and avg_score < 70.0) or integrity_boost > 0:
            severity = "HIGH"
        elif avg_score < 72.0:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        # Compile evidence from questions
        evidence_list = []
        for q_ev in item["questions"]:
            evidence_list.append({
                "question_id": q_ev["question_id"],
                "question_text": q_ev["question_text"],
                "score": q_ev["score"],
                "key_deductions": q_ev["deductions"],
            })

        # Generate recommendation
        if "STAR" in name:
            rec = "Frame behavioral answers using Situation, Task, Action, and quantifiable Result."
        elif "Pacing" in name:
            rec = "Practice speaking at 130-150 WPM using brief pauses rather than rushing or dragging."
        elif "Filler" in name:
            rec = "Pause silently for 1-2 seconds when organizing thoughts instead of saying 'um' or 'like'."
        elif "Integrity" in name or "Environment" in name:
            rec = "Ensure a quiet, single-person room with no external window switching during interview."
        elif avg_score < 60.0:
            rec = f"Review foundational architecture and implementation trade-offs for {name}."
        else:
            rec = f"Strengthen real-world production metrics and edge-case handling for {name}."

        ranked_items.append({
            "topic": name,
            "average_score": avg_score,
            "severity": severity,
            "is_repeated": is_repeated,
            "repetition_count": rep_count,
            "rank_weight": round(rank_weight, 1),
            "evidence": evidence_list[:3],
            "recommendation": rec,
        })

    # Sort descending by rank weight (worst performance first)
    ranked_items.sort(key=lambda x: x["rank_weight"], reverse=True)

    # Return top 3-5 weak areas
    return ranked_items[:5]


# =============================================================================
# 5. USER MEMORY & QUESTION HISTORY UPDATE ("U MEMORY UPDATE")
# =============================================================================

def execute_u_memory_update(
    user_id: int,
    session_id: int,
    per_question_fused: List[Dict[str, Any]],
    ranked_weak_areas: List[Dict[str, Any]],
    overall_score: float,
    db: Session,
) -> Dict[str, Any]:
    """
    Executes the 'U memory update' workflow:
    1. Updates UserMemory: rolling topic averages, weak tags, session count, and timestamp.
    2. Updates AskedQuestion history: records question hash, topic, score, and timestamp.
    """
    if not user_id:
        return {}

    # 1. Update UserMemory
    mem: Optional[UserMemory] = db.query(UserMemory).filter(UserMemory.user_id == user_id).first()
    if not mem:
        mem = UserMemory(
            user_id=user_id,
            topic_scores={},
            weak_topics=[],
            session_count=0,
            last_session_at=datetime.now(timezone.utc),
        )
        db.add(mem)
        db.flush()

    current_topics = dict(mem.topic_scores or {})
    current_weak_list = list(mem.weak_topics or [])

    # Update rolling topic averages
    for q in per_question_fused:
        topic = str(q.get("topic", "General")).strip()
        q_score = float(q.get("fused_score", 70.0))

        if topic in current_topics:
            old_score = float(current_topics[topic])
            new_avg = round((old_score * 0.6) + (q_score * 0.4), 1)
            current_topics[topic] = new_avg
        else:
            current_topics[topic] = round(q_score, 1)

    # Add top weak tags (severity HIGH or MEDIUM)
    new_weak_tags = [
        wa["topic"] for wa in ranked_weak_areas
        if wa.get("severity") in ("HIGH", "MEDIUM")
    ]
    for tag in new_weak_tags:
        if tag not in current_weak_list:
            current_weak_list.insert(0, tag)

    mem.topic_scores = current_topics
    mem.weak_topics = current_weak_list[:10]  # Keep top 10 historical weak tags
    mem.session_count = (mem.session_count or 0) + 1
    mem.last_session_at = datetime.now(timezone.utc)

    # 2. Update AskedQuestion History
    for q in per_question_fused:
        q_id = q.get("question_id", 1)
        q_text = str(q.get("question_text") or f"Question #{q_id}").strip()
        topic = str(q.get("topic") or "General").strip()
        q_score = float(q.get("fused_score", overall_score))

        norm_text = normalize_question_text(q_text)
        q_hash = hashlib.sha256(norm_text.encode("utf-8")).hexdigest()

        asked_entry = AskedQuestion(
            user_id=user_id,
            question_hash=q_hash,
            topic=topic,
            question_text=q_text,
            score=q_score,
            asked_at=datetime.now(timezone.utc),
        )
        db.add(asked_entry)

    db.commit()
    db.refresh(mem)

    return {
        "user_id": user_id,
        "session_count": mem.session_count,
        "topic_scores": mem.topic_scores,
        "weak_topics": mem.weak_topics,
        "last_session_at": mem.last_session_at.isoformat() if mem.last_session_at else None,
    }


# =============================================================================
# 6. UNIFIED PIPELINE RUNNER & PERSISTENCE
# =============================================================================

def process_and_persist_session_result(
    session_id: int,
    aligned_dataset: Optional[Dict[str, Any]] = None,
    custom_weights: Optional[Dict[str, float]] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Main orchestrator for Phase 5.3:
    1. Loads aligned dataset and raw scores (Phase 5.1 & 5.2).
    2. Runs Score Fusion with round-type weights.
    3. Runs Comparisons (baseline, trend, cohort percentile).
    4. Runs Weak-Area Ranking with evidence.
    5. Persists SessionResult record in DB.
    6. Executes 'U memory update' (UserMemory + AskedQuestion history).
    7. Returns consolidated result object.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        sess: Optional[InterviewSession] = (
            db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
        )
        if not sess:
            raise ValueError(f"Interview session #{session_id} not found.")

        user_id = sess.user_id
        interview_cfg: Optional[InterviewConfig] = (
            db.query(InterviewConfig).filter(InterviewConfig.id == sess.interview_id).first()
        )
        round_type = interview_cfg.round_type if interview_cfg else "Technical"

        target_prof: Optional[TargetProfile] = (
            db.query(TargetProfile).filter(TargetProfile.user_id == user_id).first()
        )
        role = target_prof.target_role if target_prof else "Software Engineer"

        # Load aligned dataset
        if not aligned_dataset:
            from app.services.analysis_pipeline import default_alignment_engine
            aligned_dataset = default_alignment_engine.align_session(session_id)

        # Compute scoring report if not already present
        scoring_rep = aligned_dataset.get("scores")
        if not scoring_rep or "per_question_breakdown" not in scoring_rep:
            scoring_rep = compute_session_scores(aligned_dataset)

        # 1. Score Fusion
        fused_data = fuse_session_scores(scoring_rep, round_type=round_type, custom_weights=custom_weights)
        overall_score = fused_data["overall_scores"]["composite_score"]
        content_score = fused_data["overall_scores"]["content_score"]
        speech_score = fused_data["overall_scores"]["speech_confidence_score"]
        face_score = fused_data["overall_scores"]["face_posture_score"]
        classification = fused_data["classification"]
        weights_used = fused_data["weights_used"]
        per_question_scores = fused_data["per_question_breakdown"]

        # 2. Comparisons
        comparisons = compute_session_comparisons(
            user_id=user_id,
            session_id=session_id,
            current_score=overall_score,
            round_type=round_type,
            role=role,
            db=db,
        )

        # 3. Weak-Area Ranking with Evidence
        # Fetch past weak topics from UserMemory
        user_mem: Optional[UserMemory] = db.query(UserMemory).filter(UserMemory.user_id == user_id).first()
        past_weaks = user_mem.weak_topics if user_mem else []
        integrity_events = (
            db.query(IntegrityEvent).filter(IntegrityEvent.session_id == session_id).all()
        )
        ranked_weaks = rank_weak_areas(
            per_question_fused=per_question_scores,
            user_past_weak_topics=past_weaks,
            integrity_events=[{"id": e.id, "type": e.type} for e in integrity_events],
        )

        strengths = fused_data.get("key_strengths", [])

        # 4. Persist to SessionResult Table
        existing_result = (
            db.query(SessionResult).filter(SessionResult.session_id == session_id).first()
        )
        if existing_result:
            existing_result.overall_score = overall_score
            existing_result.content_score = content_score
            existing_result.speech_score = speech_score
            existing_result.face_score = face_score
            existing_result.classification = classification
            existing_result.round_type = round_type
            existing_result.role = role
            existing_result.weights_used = weights_used
            existing_result.per_question_scores = per_question_scores
            existing_result.comparisons = comparisons
            existing_result.weak_areas = ranked_weaks
            existing_result.strengths = strengths
            db.commit()
            db.refresh(existing_result)
            res_record = existing_result
        else:
            res_record = SessionResult(
                session_id=session_id,
                user_id=user_id,
                is_guest=bool(sess.is_guest),
                round_type=round_type,
                role=role,
                overall_score=overall_score,
                content_score=content_score,
                speech_score=speech_score,
                face_score=face_score,
                classification=classification,
                weights_used=weights_used,
                per_question_scores=per_question_scores,
                comparisons=comparisons,
                weak_areas=ranked_weaks,
                strengths=strengths,
            )
            db.add(res_record)
            db.commit()
            db.refresh(res_record)

        # 5. U Memory Update (only for registered users with account)
        mem_update_info = {}
        if user_id:
            mem_update_info = execute_u_memory_update(
                user_id=user_id,
                session_id=session_id,
                per_question_fused=per_question_scores,
                ranked_weak_areas=ranked_weaks,
                overall_score=overall_score,
                db=db,
            )

        result_payload = {
            "id": res_record.id,
            "session_id": session_id,
            "user_id": user_id,
            "round_type": round_type,
            "role": role,
            "overall_score": overall_score,
            "content_score": content_score,
            "speech_score": speech_score,
            "face_score": face_score,
            "classification": classification,
            "weights_used": weights_used,
            "per_question_scores": per_question_scores,
            "comparisons": comparisons,
            "weak_areas": ranked_weaks,
            "strengths": strengths,
            "user_memory": mem_update_info,
            "created_at": res_record.created_at.isoformat() if res_record.created_at else None,
        }

        logger.info(
            "Session result persisted for session #%d (score=%.1f, classification=%s, weaks=%d)",
            session_id,
            overall_score,
            classification,
            len(ranked_weaks),
        )

        return result_payload

    finally:
        if close_db:
            db.close()
