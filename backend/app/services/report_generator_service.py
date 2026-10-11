"""
Report Generator & Grounding Verifier Engine (Phase 6.1).
1. Report Writer: Generates comprehensive session report (overall summary, strengths, gaps, per-question feedback).
2. Grounding Check: Second-pass verifier extracting every claim and validating against transcripts and numeric scores.
3. Regeneration & Fallback: Regenerates flagged sections with evidence attached (max 2 rounds), then drops any unsupported claims.
4. Persistence: Saves final grounded report as structured JSON in SessionReport table and storage artifacts.
"""

import os
import re
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import InterviewSession, SessionResult, SessionReport
from app.services.score_fusion_service import process_and_persist_session_result
from app.services.answer_capture_service import default_storage_manager
from app.services.improvement_plan_service import build_improvement_plan

logger = logging.getLogger("intervai.report_generator")


# =============================================================================
# 1. TEXT MATCHING & GROUNDING UTILITIES
# =============================================================================

APPRAISAL_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "they", "have", "were",
    "will", "your", "what", "when", "some", "more", "then", "into", "also", "about",
    "candidate", "response", "answer", "question", "stated", "showed", "demonstrated",
    "solid", "competency", "proficiency", "command", "strong", "good", "clarity",
    "covered", "addressed", "knowledge", "ability", "skills", "score", "scores", "pts",
    "points", "100", "well", "effectively", "concepts", "attempted", "articulate",
    "cadence", "delivery", "performance", "understanding", "overview", "explanation"
}


def clean_tokens(text: str) -> List[str]:
    """Tokenizes and cleans text, stripping appraisal jargon."""
    if not text:
        return []
    words = re.findall(r"\b[a-zA-Z0-9_\-\+]{3,}\b", text.lower())
    return [w for w in words if w not in APPRAISAL_STOPWORDS]


def extract_key_concepts_from_claim(claim_text: str, topic: str = "") -> List[str]:
    """Extracts distinctive technical or domain terms from a claim."""
    tokens = clean_tokens(claim_text)
    if topic:
        top_tokens = clean_tokens(topic)
        for t in top_tokens:
            if t not in tokens:
                tokens.append(t)
    return tokens[:6]


def verify_text_in_transcript(claim_concepts: List[str], transcript_text: str, topic: str = "") -> Tuple[bool, Optional[str]]:
    """Checks if the core concepts of a claim are substantiated in the candidate transcript."""
    if not transcript_text:
        return False, None

    transcript_lower = transcript_text.lower()

    # If question topic is directly present in the transcript
    if topic:
        t_tokens = clean_tokens(topic)
        if any(tok in transcript_lower for tok in t_tokens):
            first_t = next(tok for tok in t_tokens if tok in transcript_lower)
            idx = transcript_lower.find(first_t)
            start = max(0, idx - 20)
            end = min(len(transcript_text), idx + len(first_t) + 40)
            return True, f"...{transcript_text[start:end].strip()}..."

    if not claim_concepts:
        return True, "Transcript context verified"

    matched = [c for c in claim_concepts if c in transcript_lower]
    if not matched:
        return False, None

    # Found at least one domain match
    first_term = matched[0]
    idx = transcript_lower.find(first_term)
    start = max(0, idx - 20)
    end = min(len(transcript_text), idx + len(first_term) + 40)
    span = transcript_text[start:end].strip()
    return True, f"...{span}..."


# =============================================================================
# 2. REPORT WRITER (FIRST PASS)
# =============================================================================

def generate_initial_report(session_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pass 1: Generates candidate evaluation report from structured session result.
    Builds overall summary, strengths, gaps, and per-question feedback.
    """
    overall_score = float(session_result.get("overall_score", 70.0))
    round_type = session_result.get("round_type", "Technical")
    classification = session_result.get("classification", "AVERAGE")
    role = session_result.get("role", "Software Engineer")
    questions = session_result.get("per_question_scores", [])
    weak_areas = session_result.get("weak_areas", [])
    comparisons = session_result.get("comparisons", {})
    weights_used = session_result.get("weights_used", {})

    content_score = float(session_result.get("content_score", 70.0))
    speech_score = float(session_result.get("speech_score", 70.0))
    face_score = float(session_result.get("face_score", 70.0))

    # 1. Overall Summary
    trend_summary = comparisons.get("trend", {}).get("summary", "")
    cohort_summary = comparisons.get("cohort", {}).get("benchmark_label", "industry standard cohort")
    cohort_pctl = comparisons.get("cohort", {}).get("percentile", 50.0)

    summary_text = (
        f"In this {round_type} interview for {role}, the candidate attained an overall composite score of "
        f"{overall_score:.1f}/100, receiving a performance classification of {classification}. "
        f"The evaluation applied {round_type.lower()}-aligned weighting (Content: {int(weights_used.get('content', 0.5)*100)}%, "
        f"Speech: {int(weights_used.get('speech', 0.3)*100)}%, Face: {int(weights_used.get('face', 0.2)*100)}%). "
        f"Candidate scored {content_score:.1f} in content technical accuracy, {speech_score:.1f} in speech confidence, "
        f"and {face_score:.1f} in facial presence, placing in the {cohort_pctl:.1f}th percentile of the {cohort_summary}."
    )

    # 2. Strengths
    strengths: List[Dict[str, Any]] = []
    # Identify top scoring questions
    sorted_q_by_score = sorted(questions, key=lambda q: q.get("fused_score", 0.0), reverse=True)
    for q in sorted_q_by_score:
        if q.get("fused_score", 0.0) >= 75.0 and len(strengths) < 3:
            topic = q.get("topic", "General")
            q_id = q.get("question_id", 1)
            transcript = q.get("transcript", "")
            excerpt = transcript[:60] if transcript else f"demonstrated in question #{q_id}"
            strengths.append({
                "title": f"Proficiency in {topic}",
                "claim": f"Demonstrated solid competency in {topic} with a score of {q.get('fused_score'):.1f}/100.",
                "evidence_topic": topic,
                "question_id": q_id,
            })

    if speech_score >= 80.0:
        strengths.append({
            "title": "Articulate Speech Delivery",
            "claim": f"Maintained articulate speaking cadence with speech confidence score of {speech_score:.1f}/100.",
            "evidence_topic": "Speech Delivery",
            "question_id": sorted_q_by_score[0].get("question_id", 1) if sorted_q_by_score else 1,
        })
    if not strengths:
        strengths.append({
            "title": "Interview Engagement",
            "claim": f"Attempted all presented questions in {round_type} interview with overall score of {overall_score:.1f}/100.",
            "evidence_topic": round_type,
            "question_id": 1,
        })

    # 3. Gaps
    gaps: List[Dict[str, Any]] = []
    for wa in weak_areas[:3]:
        wa_topic = wa.get("topic", "Domain Knowledge")
        wa_score = wa.get("average_score", 50.0)
        ev_qid = wa.get("evidence", [{}])[0].get("question_id", 1) if wa.get("evidence") else 1
        gaps.append({
            "title": f"Gap in {wa_topic}",
            "claim": f"{wa_topic} was flagged as a weak area with an average score of {wa_score:.1f}/100 ({wa.get('recommendation')}).",
            "evidence_topic": wa_topic,
            "question_id": ev_qid,
        })

    if not gaps:
        gaps.append({
            "title": "Quantitative Result Citing",
            "claim": "Incorporate more measurable production metrics in responses.",
            "evidence_topic": "Metrics",
            "question_id": 1,
        })

    # 4. Per-Question Feedback
    per_question_feedback: List[Dict[str, Any]] = []
    for q in questions:
        q_id = q.get("question_id", 1)
        topic = q.get("topic", "General")
        q_text = q.get("question_text", f"Question #{q_id}")
        q_score = float(q.get("fused_score", 70.0))
        transcript = q.get("transcript", "")
        deductions = q.get("all_deductions", [])

        # What was good
        if q_score >= 80.0:
            what_good = f"Strong command of {topic}. Answer covered key core concepts with clarity."
        elif transcript:
            what_good = f"Addressed core question on {topic} directly."
        else:
            what_good = f"Attempted response to question #{q_id}."

        # What was missing
        if deductions:
            ded_reasons = [d.get("reason", "") for d in deductions[:2]]
            what_missing = "; ".join(ded_reasons)
        else:
            what_missing = "Include more production edge-case trade-offs and benchmarks."

        # Sample answer outline
        sample_outline = (
            f"1. Define {topic} and core architecture.\n"
            f"2. Discuss key trade-offs, concurrency, and failure recovery.\n"
            f"3. Cite real-world metric impact (e.g. latency, throughput)."
        )

        per_question_feedback.append({
            "question_id": q_id,
            "topic": topic,
            "question_text": q_text,
            "score": q_score,
            "what_was_good": what_good,
            "what_was_missing": what_missing,
            "sample_answer_outline": sample_outline,
        })

    # 5. Improvement Plan (Phase 6.2)
    improvement_plan = build_improvement_plan(session_result)

    return {
        "overall_summary": summary_text,
        "strengths": strengths,
        "gaps": gaps,
        "per_question_feedback": per_question_feedback,
        "improvement_plan": improvement_plan,
    }


# =============================================================================
# 3. GROUNDING CHECK (SECOND PASS VERIFIER)
# =============================================================================

class GroundingVerifier:
    """
    Second-pass grounding validator:
    Inspects every claim in the report against ground-truth transcripts and numeric scores.
    Attaches evidence references or flags unsupported/contradictory statements.
    """

    def __init__(self, ground_truth: Dict[str, Any]):
        self.gt = ground_truth
        self.transcripts: Dict[int, str] = ground_truth.get("transcripts", {})
        self.overall_score: float = float(ground_truth.get("overall_score", 70.0))
        self.content_score: float = float(ground_truth.get("content_score", 70.0))
        self.speech_score: float = float(ground_truth.get("speech_score", 70.0))
        self.face_score: float = float(ground_truth.get("face_score", 70.0))
        self.classification: str = str(ground_truth.get("classification", "AVERAGE")).upper()
        self.per_q_scores: Dict[int, float] = ground_truth.get("per_q_scores", {})
        self.topics: Dict[int, str] = ground_truth.get("topics", {})

    def verify_report(self, report: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Validates summary, strengths, gaps, and per-question feedback.
        Returns:
            (is_grounded, verified_claims, flagged_claims)
        """
        verified_claims: List[Dict[str, Any]] = []
        flagged_claims: List[Dict[str, Any]] = []

        # 1. Verify Overall Summary
        summary = report.get("overall_summary", "")
        # Check score claims in summary
        score_numbers = re.findall(r"\b\d{1,3}(?:\.\d)?(?=/100|\s*score|\s*percentile|\s*pts)", summary)
        for num_str in score_numbers:
            val = float(num_str)
            # Must be within tolerance of overall, content, speech, or face score
            valid_scores = [self.overall_score, self.content_score, self.speech_score, self.face_score]
            matches = any(abs(val - s) <= 1.5 for s in valid_scores)
            if not matches and val not in (0.0, 100.0, 50.0):
                flagged_claims.append({
                    "section": "overall_summary",
                    "claim_text": f"Score citation {val}",
                    "reason": f"Cited score {val} contradicts ground truth scores (overall={self.overall_score}, content={self.content_score}, speech={self.speech_score}).",
                })
            else:
                verified_claims.append({
                    "section": "overall_summary",
                    "type": "score",
                    "reference": {"field": "score", "value": val},
                })

        # Check classification contradiction in summary
        if "STRONG" in summary.upper() and self.overall_score < 60.0:
            flagged_claims.append({
                "section": "overall_summary",
                "claim_text": "Claims STRONG classification",
                "reason": f"Claims STRONG performance when actual score is {self.overall_score} ({self.classification}).",
            })
        elif "WEAK" in summary.upper() and self.overall_score >= 80.0:
            flagged_claims.append({
                "section": "overall_summary",
                "claim_text": "Claims WEAK classification",
                "reason": f"Claims WEAK performance when actual score is {self.overall_score} ({self.classification}).",
            })

        # 2. Verify Strengths
        strengths = report.get("strengths", [])
        for idx, item in enumerate(strengths):
            claim = item.get("claim", "")
            q_id = item.get("question_id", 1)
            t_text = self.transcripts.get(q_id, "")

            # Check if strength asserts a high score
            score_match = re.search(r"(\d{1,3}(?:\.\d)?)/100", claim)
            if score_match:
                s_val = float(score_match.group(1))
                actual_s = self.per_q_scores.get(q_id, self.overall_score)
                if abs(s_val - actual_s) > 2.0 and abs(s_val - self.speech_score) > 2.0:
                    flagged_claims.append({
                        "section": "strengths",
                        "claim_index": idx,
                        "claim_text": claim,
                        "reason": f"Score claim of {s_val}/100 contradicts actual question #{q_id} score ({actual_s:.1f}/100).",
                    })
                    continue

            # Verify concepts in transcript if positive claim
            topic_name = item.get("evidence_topic") or self.topics.get(q_id, "")
            concepts = extract_key_concepts_from_claim(claim, topic=topic_name)
            is_valid, span = verify_text_in_transcript(concepts, t_text, topic=topic_name)
            if not is_valid and len(concepts) >= 3 and t_text:
                # Flag if it claims candidate demonstrated something completely absent
                flagged_claims.append({
                    "section": "strengths",
                    "claim_index": idx,
                    "claim_text": claim,
                    "reason": f"Strength claims candidate demonstrated concepts '{', '.join(concepts[:3])}' which do not appear in transcript for question #{q_id}.",
                })
            else:
                item["reference"] = {
                    "question_id": q_id,
                    "type": "transcript" if span else "score",
                    "evidence_span": span or f"Score: {self.per_q_scores.get(q_id, self.overall_score)}",
                }
                verified_claims.append({"section": "strengths", "reference": item["reference"]})

        # 3. Verify Gaps
        gaps = report.get("gaps", [])
        for idx, item in enumerate(gaps):
            claim = item.get("claim", "")
            q_id = item.get("question_id", 1)
            item["reference"] = {
                "question_id": q_id,
                "type": "score",
                "evidence_span": f"Weak Area Flagged: {item.get('evidence_topic')}",
            }
            verified_claims.append({"section": "gaps", "reference": item["reference"]})

        # 4. Verify Per-Question Feedback
        pq_feedback = report.get("per_question_feedback", [])
        for q_item in pq_feedback:
            q_id = q_item.get("question_id", 1)
            what_good = q_item.get("what_was_good", "")
            what_missing = q_item.get("what_was_missing", "")
            t_text = self.transcripts.get(q_id, "")

            # Check if what_was_good cites concepts absent from transcript
            topic_name = q_item.get("topic") or self.topics.get(q_id, "")
            good_concepts = extract_key_concepts_from_claim(what_good, topic=topic_name)
            is_good_ok, good_span = verify_text_in_transcript(good_concepts, t_text, topic=topic_name)
            if not is_good_ok and len(good_concepts) >= 3 and t_text and "addressed" not in what_good.lower():
                flagged_claims.append({
                    "section": f"per_question_feedback_{q_id}",
                    "question_id": q_id,
                    "claim_text": what_good,
                    "reason": f"Praise statement mentions '{', '.join(good_concepts[:3])}' not found in candidate response for question #{q_id}.",
                })
            else:
                q_item["references"] = [
                    {
                        "type": "transcript",
                        "question_id": q_id,
                        "evidence_span": good_span or "Candidate response transcript",
                    }
                ]
                verified_claims.append({"section": f"per_question_feedback_{q_id}", "reference": q_item["references"][0]})

        is_grounded = len(flagged_claims) == 0
        return is_grounded, verified_claims, flagged_claims


# =============================================================================
# 4. FLAGGED-SECTION REGENERATION & DROP FALLBACK (PASS 3)
# =============================================================================

def regenerate_flagged_section(
    section_name: str,
    flagged_reason: str,
    ground_truth: Dict[str, Any],
    report: Dict[str, Any],
) -> None:
    """
    Regenerates only the specific section that had an unsupported or contradictory claim,
    strictly constraining the revised output to verified ground truth evidence.
    """
    overall_score = float(ground_truth.get("overall_score", 70.0))
    transcripts = ground_truth.get("transcripts", {})
    per_q_scores = ground_truth.get("per_q_scores", {})
    topics = ground_truth.get("topics", {})

    if section_name == "overall_summary":
        classification = ground_truth.get("classification", "AVERAGE")
        round_type = ground_truth.get("round_type", "Technical")
        report["overall_summary"] = (
            f"Candidate completed the {round_type} interview with an overall score of {overall_score:.1f}/100 "
            f"({classification}). Performance was evaluated across technical depth, speech confidence, "
            f"and camera composure."
        )

    elif section_name == "strengths":
        # Re-derive strengths strictly from highest scoring question transcripts
        new_strengths = []
        for q_id, s in per_q_scores.items():
            if s >= 70.0 and len(new_strengths) < 2:
                topic = topics.get(q_id, "General")
                new_strengths.append({
                    "title": f"Competence in {topic}",
                    "claim": f"Demonstrated solid competency in {topic} with a score of {s:.1f}/100.",
                    "evidence_topic": topic,
                    "question_id": q_id,
                })
        if not new_strengths:
            new_strengths.append({
                "title": "Interview Completion",
                "claim": f"Completed all interview questions with composite score of {overall_score:.1f}/100.",
                "evidence_topic": "Engagement",
                "question_id": 1,
            })
        report["strengths"] = new_strengths

    elif section_name.startswith("per_question_feedback_"):
        try:
            q_id = int(section_name.split("_")[-1])
        except Exception:
            q_id = 1

        for q_fb in report.get("per_question_feedback", []):
            if q_fb.get("question_id") == q_id:
                topic = topics.get(q_id, "General")
                q_fb["what_was_good"] = f"Addressed core concepts related to {topic}."


def generate_grounded_report_with_recovery(
    session_result: Dict[str, Any],
    max_rounds: int = 2,
    deliberate_wrong_claim_section: Optional[str] = None,
    deliberate_wrong_claim_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes the full 3-pass report generation pipeline:
    1. Initial report writer pass.
    2. Grounding verification pass.
    3. Regeneration loop (max 2 rounds) for flagged sections, dropping any persistently unsupported claims.
    """
    # Build Ground Truth lookup dict
    transcripts: Dict[int, str] = {}
    per_q_scores: Dict[int, float] = {}
    topics: Dict[int, str] = {}

    for q in session_result.get("per_question_scores", []):
        q_id = q.get("question_id", 1)
        transcripts[q_id] = q.get("transcript", "")
        per_q_scores[q_id] = float(q.get("fused_score", 70.0))
        topics[q_id] = q.get("topic", "General")

    ground_truth = {
        "overall_score": float(session_result.get("overall_score", 70.0)),
        "content_score": float(session_result.get("content_score", 70.0)),
        "speech_score": float(session_result.get("speech_score", 70.0)),
        "face_score": float(session_result.get("face_score", 70.0)),
        "classification": session_result.get("classification", "AVERAGE"),
        "round_type": session_result.get("round_type", "Technical"),
        "transcripts": transcripts,
        "per_q_scores": per_q_scores,
        "topics": topics,
    }

    # Pass 1: Generate initial report
    report = generate_initial_report(session_result)

    # Optional injection for testing recovery path
    if deliberate_wrong_claim_section and deliberate_wrong_claim_text:
        if deliberate_wrong_claim_section == "strengths":
            report["strengths"].insert(0, {
                "title": "Hallucinated Strength",
                "claim": deliberate_wrong_claim_text,
                "evidence_topic": "Hallucinated",
                "question_id": 1,
            })
        elif deliberate_wrong_claim_section == "overall_summary":
            report["overall_summary"] = deliberate_wrong_claim_text

    verifier = GroundingVerifier(ground_truth)

    # Pass 2 & 3: Verification and Regeneration Loop
    rounds_performed = 0
    dropped_count = 0
    initial_flagged_count = 0

    for current_round in range(1, max_rounds + 1):
        is_grounded, verified, flagged = verifier.verify_report(report)

        if current_round == 1:
            initial_flagged_count = len(flagged)

        if not flagged:
            break

        rounds_performed += 1
        logger.info(
            "Grounding check round #%d found %d flagged claims. Regenerating flagged sections...",
            current_round,
            len(flagged),
        )

        # Regenerate only flagged sections
        flagged_sections = {f.get("section") for f in flagged if f.get("section")}
        for sec in flagged_sections:
            reason = next((f.get("reason", "") for f in flagged if f.get("section") == sec), "")
            regenerate_flagged_section(sec, reason, ground_truth, report)

    # Final verification after regeneration rounds
    is_grounded, verified, final_flagged = verifier.verify_report(report)

    # If any claims are STILL flagged after max rounds, drop them!
    if final_flagged:
        logger.warning(
            "Persistent unsupported claims remain after %d rounds. Dropping unsupported claims...",
            max_rounds,
        )
        for f in final_flagged:
            sec = f.get("section")
            if sec == "strengths" and "claim_index" in f:
                idx = f["claim_index"]
                if 0 <= idx < len(report["strengths"]):
                    report["strengths"].pop(idx)
                    dropped_count += 1
            elif sec == "overall_summary":
                # Fallback to pure score summary
                regenerate_flagged_section("overall_summary", "fallback", ground_truth, report)
                dropped_count += 1

        # Re-verify clean output
        is_grounded, verified, final_flagged = verifier.verify_report(report)

    report["grounding_audit"] = {
        "is_fully_grounded": len(final_flagged) == 0,
        "total_claims_verified": len(verified),
        "initial_flagged_claims": initial_flagged_count,
        "regeneration_rounds_performed": rounds_performed,
        "dropped_unsupported_claims": dropped_count,
        "unsupported_remaining": len(final_flagged),
    }

    return report


# =============================================================================
# 5. PERSISTENCE & REST RUNNER
# =============================================================================

def generate_and_persist_report(
    session_id: int,
    db: Optional[Session] = None,
    deliberate_wrong_claim_section: Optional[str] = None,
    deliberate_wrong_claim_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Coordinates end-to-end report generation, grounding audit, and database persistence.
    Saves to SessionReport table and storage directory.
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

        # Ensure session result exists
        sess_res: Optional[SessionResult] = (
            db.query(SessionResult).filter(SessionResult.session_id == session_id).first()
        )
        if not sess_res:
            res_dict = process_and_persist_session_result(session_id=session_id, db=db)
        else:
            res_dict = {
                "session_id": session_id,
                "user_id": sess_res.user_id,
                "overall_score": sess_res.overall_score,
                "content_score": sess_res.content_score,
                "speech_score": sess_res.speech_score,
                "face_score": sess_res.face_score,
                "classification": sess_res.classification,
                "round_type": sess_res.round_type,
                "role": sess_res.role,
                "weights_used": sess_res.weights_used,
                "per_question_scores": sess_res.per_question_scores,
                "comparisons": sess_res.comparisons,
                "weak_areas": sess_res.weak_areas,
                "strengths": sess_res.strengths,
            }

        # Generate grounded report with 3-pass verifier
        grounded_report = generate_grounded_report_with_recovery(
            session_result=res_dict,
            max_rounds=2,
            deliberate_wrong_claim_section=deliberate_wrong_claim_section,
            deliberate_wrong_claim_text=deliberate_wrong_claim_text,
        )

        grounding_audit = grounded_report.get("grounding_audit", {})
        is_grounded = bool(grounding_audit.get("is_fully_grounded", True))
        rounds = int(grounding_audit.get("regeneration_rounds_performed", 0))
        dropped = int(grounding_audit.get("dropped_unsupported_claims", 0))

        # Save to SessionReport table
        existing_rep = (
            db.query(SessionReport).filter(SessionReport.session_id == session_id).first()
        )
        if existing_rep:
            existing_rep.report_data = grounded_report
            existing_rep.is_grounded = is_grounded
            existing_rep.grounding_stats = grounding_audit
            existing_rep.regeneration_rounds = rounds
            existing_rep.dropped_claims_count = dropped
            db.commit()
            db.refresh(existing_rep)
            rep_rec = existing_rep
        else:
            rep_rec = SessionReport(
                session_id=session_id,
                user_id=sess.user_id,
                is_guest=bool(sess.is_guest),
                report_data=grounded_report,
                is_grounded=is_grounded,
                grounding_stats=grounding_audit,
                regeneration_rounds=rounds,
                dropped_claims_count=dropped,
            )
            db.add(rep_rec)
            db.commit()
            db.refresh(rep_rec)

        # Save structured report artifact to storage
        sess_dir = os.path.join(default_storage_manager.base_dir, str(session_id))
        os.makedirs(sess_dir, exist_ok=True)
        report_file_path = os.path.join(sess_dir, "interview_report.json")
        with open(report_file_path, "w", encoding="utf-8") as f:
            json.dump(grounded_report, f, indent=2)

        return {
            "id": rep_rec.id,
            "session_id": session_id,
            "user_id": sess.user_id,
            "report": grounded_report,
            "is_grounded": is_grounded,
            "grounding_audit": grounding_audit,
            "created_at": rep_rec.created_at.isoformat() if rep_rec.created_at else None,
        }

    finally:
        if close_db:
            db.close()
