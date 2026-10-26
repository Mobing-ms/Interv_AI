"""
Scoring Engine (Phase 5.2).
Provides three pure-function scoring modules with normalized outputs (0-100):
1. Face & Posture Scorer: Eye-contact vs baseline, expression composure, head-pose stability, posture, fidgeting penalty.
2. Speech Confidence Scorer: Speaking pace (ideal 120-160 WPM), filler rate, pause pattern, pitch/volume variability, clarity.
3. Content Scorer: Accuracy, depth, keyword coverage, STAR structure for behavioral questions, and use of examples.

All weights and thresholds are driven by ScoringConfig. Every deduction and factor
is accompanied by clear, human-readable explanations citing impact and metric values.
"""

import re
import math
from typing import Dict, Any, List, Optional
from app.services.scoring_config import (
    ScoringConfig,
    FacePostureConfig,
    SpeechConfidenceConfig,
    ContentRubricConfig,
    SessionScoringWeights,
    DEFAULT_SCORING_CONFIG,
)


# =============================================================================
# HELPER: TEXT ANALYSIS FOR EXAMPLES & STAR
# =============================================================================

def detect_concrete_examples(transcript: str, marker_keywords: List[str]) -> Dict[str, Any]:
    """
    Detects presence of concrete examples, metrics, numbers, or case study citations in text.
    """
    if not transcript:
        return {"has_examples": False, "count": 0, "matched_markers": [], "metrics_cited": []}

    text_lower = transcript.lower()
    matched_markers = [m for m in marker_keywords if m in text_lower]

    # Detect numerical metrics, percentages, dollar amounts, or time reductions
    metric_patterns = [
        r"\b\d+(\.\d+)?%\b",  # e.g. 25%, 99.9%
        r"\b\d+x\b",  # e.g. 10x
        r"\b(reduced|increased|improved|saved|scaled|cut|boosted)\s+by\s+\w+",
        r"\b\d+\s+(ms|seconds|minutes|hours|days|percent|users|requests|qps|rps)\b",
    ]
    metrics_found = []
    for pat in metric_patterns:
        for match in re.finditer(pat, text_lower):
            metrics_found.append(match.group(0))

    has_examples = len(matched_markers) > 0 or len(metrics_found) > 0
    return {
        "has_examples": has_examples,
        "count": len(matched_markers) + len(metrics_found),
        "matched_markers": matched_markers,
        "metrics_cited": metrics_found,
    }



# =============================================================================
# MISSING-SIGNAL HANDLING
# =============================================================================

FACE_FACTOR_METRICS = {
    "eye_contact": ["avg_eye_contact"],
    "expression_stability": ["avg_emotion_valence"],
    "head_pose_stability": ["avg_head_yaw", "avg_head_pitch", "avg_head_roll"],
    "posture": ["avg_posture_alignment"],
    "fidgeting": ["avg_movement_level"],
}

SPEECH_FACTOR_METRICS = {
    "speech_pace": ["avg_speech_pace_wpm"],
    "filler_rate": ["filler_rate"],
    "pause_pattern": ["total_pauses", "avg_pause_length"],
    "pitch_variability": ["pitch_variance"],
    "volume_variability": ["volume_variability"],
    "clarity": ["avg_clarity_proxy"],
}


def _f(d: Dict[str, Any], key: str, default: float) -> float:
    """Value for the scoring formula; unmeasured factors are dropped later by _restrict_to_measured."""
    v = (d or {}).get(key)
    return float(default) if v is None else float(v)


def _restrict_to_measured(result: Dict[str, Any], signals: Dict[str, Any], factor_metrics: Dict[str, List[str]], label: str) -> Dict[str, Any]:
    """
    Keeps only factors whose input metrics were actually measured and rescales the
    score over those factors. If nothing was measured the module score is None,
    never a made-up default.
    """
    signals = signals or {}
    measured = [f for f, keys in factor_metrics.items() if all(signals.get(k) is not None for k in keys)]
    unmeasured = [f for f in factor_metrics if f not in measured]
    result["measured_factors"] = measured
    result["unmeasured_factors"] = unmeasured
    if not unmeasured:
        result["measured"] = True
        return result
    if not measured:
        return {
            "score": None,
            "measured": False,
            "measured_factors": [],
            "unmeasured_factors": unmeasured,
            "sub_scores": {},
            "max_sub_scores": {},
            "explanations": [],
            "deductions": [],
            "raw_metrics": {},
            "note": f"{label} signals were not measured for this answer.",
        }
    keep = set(measured)
    sub_scores = {k: v for k, v in result["sub_scores"].items() if k in keep}
    max_sub = {k: v for k, v in result["max_sub_scores"].items() if k in keep}
    total_max = sum(max_sub.values())
    score = round(100.0 * sum(sub_scores.values()) / total_max, 1) if total_max > 0 else None
    result.update({
        "score": score,
        "measured": True,
        "sub_scores": sub_scores,
        "max_sub_scores": max_sub,
        "explanations": [e for e in result["explanations"] if e.get("factor") in keep],
        "deductions": [d for d in result["deductions"] if d.get("factor") in keep],
        "note": f"Not measured (excluded from score): {', '.join(unmeasured)}.",
    })
    return result


def _weighted_available(parts: List[tuple]) -> Optional[float]:
    """Weighted mean over (score, weight) pairs whose score is not None, weights renormalized."""
    avail = [(sc, w) for sc, w in parts if sc is not None and w > 0]
    total_w = sum(w for _, w in avail)
    if not avail or total_w <= 0:
        return None
    return sum(sc * w for sc, w in avail) / total_w


def _mean_or_none(vals: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

# =============================================================================
# MODULE 1: FACE AND POSTURE SCORE (PURE FUNCTION)
# =============================================================================

def compute_face_and_posture_score(
    face_signals: Dict[str, Any],
    baseline: Optional[Dict[str, Any]] = None,
    config: Optional[FacePostureConfig] = None,
) -> Dict[str, Any]:
    """
    Computes a normalized face and posture score (0-100) based on:
    - Eye-contact percentage vs calibration baseline
    - Expression stability / composure
    - Head-pose stability (yaw/pitch/roll deviation relative to baseline)
    - Posture alignment
    - Fidgeting / movement level penalty

    Returns:
        {
            "score": float (0-100),
            "sub_scores": Dict[str, float],
            "max_sub_scores": Dict[str, float],
            "explanations": List[Dict[str, Any]],
            "deductions": List[Dict[str, Any]],
            "raw_metrics": Dict[str, Any],
        }
    """
    cfg = config or FacePostureConfig()
    baseline = baseline or {}
    face_base = baseline.get("face_baseline", {})
    base_eye = float(face_base.get("eye_contact", 0.90))

    explanations: List[Dict[str, Any]] = []
    deductions: List[Dict[str, Any]] = []
    sub_scores: Dict[str, float] = {}
    max_sub_scores: Dict[str, float] = {}

    # Extract raw signal values with resilient defaults
    raw_eye = _f(face_signals, "avg_eye_contact", 0.85)
    raw_yaw = _f(face_signals, "avg_head_yaw", 0.0)
    raw_pitch = _f(face_signals, "avg_head_pitch", 0.0)
    raw_roll = _f(face_signals, "avg_head_roll", 0.0)
    raw_emotion = _f(face_signals, "avg_emotion_valence", 0.15)
    raw_posture = _f(face_signals, "avg_posture_alignment", 0.88)
    raw_movement = _f(face_signals, "avg_movement_level", 0.04)

    # 1. Eye-contact percentage vs calibration baseline
    max_eye_pts = cfg.weight_eye_contact * 100.0
    max_sub_scores["eye_contact"] = max_eye_pts
    # Compare observed eye-contact against target baseline
    target_eye = max(0.2, base_eye * cfg.target_eye_contact_ratio)
    if raw_eye >= target_eye:
        eye_pts = max_eye_pts
        eye_ded = 0.0
        eye_reason = f"Excellent eye contact at {raw_eye * 100:.1f}%, meeting or exceeding the {target_eye * 100:.1f}% baseline target."
    elif raw_eye <= cfg.min_acceptable_eye_contact:
        eye_pts = 0.0
        eye_ded = -max_eye_pts
        eye_reason = f"Low eye contact at {raw_eye * 100:.1f}% (below {cfg.min_acceptable_eye_contact * 100:.1f}% minimum threshold relative to {base_eye * 100:.1f}% baseline)."
    else:
        fraction = (raw_eye - cfg.min_acceptable_eye_contact) / max(0.01, (target_eye - cfg.min_acceptable_eye_contact))
        eye_pts = max(0.0, min(max_eye_pts, fraction * max_eye_pts))
        eye_ded = round(eye_pts - max_eye_pts, 1)
        eye_reason = f"Eye contact was {raw_eye * 100:.1f}%, slightly below target {target_eye * 100:.1f}% relative to calibration baseline."

    sub_scores["eye_contact"] = round(eye_pts, 1)
    exp_eye = {
        "factor": "eye_contact",
        "earned_points": round(eye_pts, 1),
        "max_points": round(max_eye_pts, 1),
        "deduction": round(eye_ded, 1),
        "metric_value": f"{raw_eye * 100:.1f}%",
        "reason": eye_reason,
    }
    explanations.append(exp_eye)
    if eye_ded < -0.1:
        deductions.append(exp_eye)

    # 2. Expression stability / composure
    max_exp_pts = cfg.weight_expression_stability * 100.0
    max_sub_scores["expression_stability"] = max_exp_pts
    # Emotion valence: composed range is -0.1 to 0.45.
    # Severe negative (frown/stress < -0.3) or extreme valence fluctuation penalizes.
    if raw_emotion < -0.30:
        exp_pts = max(0.0, max_exp_pts * (1.0 - (abs(raw_emotion) - 0.30) * 1.5))
        exp_ded = round(exp_pts - max_exp_pts, 1)
        exp_reason = f"Facial tension or negative expression detected (valence score: {raw_emotion:.2f})."
    else:
        exp_pts = max_exp_pts
        exp_ded = 0.0
        exp_reason = f"Maintained stable, calm, and composed facial expressions throughout the response."

    sub_scores["expression_stability"] = round(exp_pts, 1)
    exp_expr = {
        "factor": "expression_stability",
        "earned_points": round(exp_pts, 1),
        "max_points": round(max_exp_pts, 1),
        "deduction": round(exp_ded, 1),
        "metric_value": round(raw_emotion, 2),
        "reason": exp_reason,
    }
    explanations.append(exp_expr)
    if exp_ded < -0.1:
        deductions.append(exp_expr)

    # 3. Head-pose stability (yaw/pitch/roll deviation relative to baseline)
    max_head_pts = cfg.weight_head_pose_stability * 100.0
    max_sub_scores["head_pose_stability"] = max_head_pts
    dev_yaw = abs(raw_yaw)
    dev_pitch = abs(raw_pitch)
    dev_roll = abs(raw_roll)

    # Compute normalized penalties across each axis
    pen_yaw = min(1.0, max(0.0, (dev_yaw - 5.0) / max(1.0, cfg.max_yaw_dev_deg - 5.0))) if dev_yaw > 5.0 else 0.0
    pen_pitch = min(1.0, max(0.0, (dev_pitch - 5.0) / max(1.0, cfg.max_pitch_dev_deg - 5.0))) if dev_pitch > 5.0 else 0.0
    pen_roll = min(1.0, max(0.0, (dev_roll - 4.0) / max(1.0, cfg.max_roll_dev_deg - 4.0))) if dev_roll > 4.0 else 0.0

    avg_pose_penalty = (pen_yaw * 0.5) + (pen_pitch * 0.3) + (pen_roll * 0.2)
    head_pts = max(0.0, max_head_pts * (1.0 - avg_pose_penalty))
    head_ded = round(head_pts - max_head_pts, 1)

    if avg_pose_penalty > 0.05:
        details = []
        if dev_yaw > 8.0:
            details.append(f"head yaw turned {dev_yaw:.1f}°")
        if dev_pitch > 8.0:
            details.append(f"head pitch tilted {dev_pitch:.1f}°")
        if dev_roll > 6.0:
            details.append(f"head roll tilted {dev_roll:.1f}°")
        head_reason = f"Head pose deviated from camera center ({', '.join(details)})."
    else:
        head_reason = "Consistent forward-facing head pose and direct camera engagement."

    sub_scores["head_pose_stability"] = round(head_pts, 1)
    exp_head = {
        "factor": "head_pose_stability",
        "earned_points": round(head_pts, 1),
        "max_points": round(max_head_pts, 1),
        "deduction": round(head_ded, 1),
        "metric_value": f"yaw:{raw_yaw:.1f}°, pitch:{raw_pitch:.1f}°, roll:{raw_roll:.1f}°",
        "reason": head_reason,
    }
    explanations.append(exp_head)
    if head_ded < -0.1:
        deductions.append(exp_head)

    # 4. Posture alignment
    max_posture_pts = cfg.weight_posture * 100.0
    max_sub_scores["posture"] = max_posture_pts
    if raw_posture >= cfg.target_posture:
        posture_pts = max_posture_pts
        posture_ded = 0.0
        posture_reason = f"Excellent posture alignment ({raw_posture * 100:.1f}%), upright and balanced."
    elif raw_posture <= cfg.min_posture:
        posture_pts = 0.0
        posture_ded = -max_posture_pts
        posture_reason = f"Poor posture alignment ({raw_posture * 100:.1f}%), noticeably slouched or off-center."
    else:
        ratio = (raw_posture - cfg.min_posture) / max(0.01, (cfg.target_posture - cfg.min_posture))
        posture_pts = max(0.0, min(max_posture_pts, ratio * max_posture_pts))
        posture_ded = round(posture_pts - max_posture_pts, 1)
        posture_reason = f"Sub-optimal posture ({raw_posture * 100:.1f}%), with minor slouching or uneven shoulders."

    sub_scores["posture"] = round(posture_pts, 1)
    exp_posture = {
        "factor": "posture",
        "earned_points": round(posture_pts, 1),
        "max_points": round(max_posture_pts, 1),
        "deduction": round(posture_ded, 1),
        "metric_value": f"{raw_posture * 100:.1f}%",
        "reason": posture_reason,
    }
    explanations.append(exp_posture)
    if posture_ded < -0.1:
        deductions.append(exp_posture)

    # 5. Fidgeting / Movement level penalty
    max_fidget_pts = cfg.weight_fidgeting * 100.0
    max_sub_scores["fidgeting"] = max_fidget_pts
    if raw_movement <= cfg.fidgeting_tolerance:
        fidget_pts = max_fidget_pts
        fidget_ded = 0.0
        fidget_reason = f"Minimal body movement ({raw_movement:.3f}), showing composure and focus."
    elif raw_movement >= cfg.fidgeting_max_penalty_threshold:
        fidget_pts = 0.0
        fidget_ded = -max_fidget_pts
        fidget_reason = f"Excessive fidgeting or rapid body movements detected (movement index: {raw_movement:.3f})."
    else:
        span = cfg.fidgeting_max_penalty_threshold - cfg.fidgeting_tolerance
        ratio = (raw_movement - cfg.fidgeting_tolerance) / max(0.01, span)
        fidget_pts = max(0.0, max_fidget_pts * (1.0 - ratio))
        fidget_ded = round(fidget_pts - max_fidget_pts, 1)
        fidget_reason = f"Noticeable shifting or nervous fidgeting during answer (movement index: {raw_movement:.3f})."

    sub_scores["fidgeting"] = round(fidget_pts, 1)
    exp_fidget = {
        "factor": "fidgeting",
        "earned_points": round(fidget_pts, 1),
        "max_points": round(max_fidget_pts, 1),
        "deduction": round(fidget_ded, 1),
        "metric_value": round(raw_movement, 3),
        "reason": fidget_reason,
    }
    explanations.append(exp_fidget)
    if fidget_ded < -0.1:
        deductions.append(exp_fidget)

    total_score = sum(sub_scores.values())
    total_score = max(0.0, min(100.0, round(total_score, 1)))

    return _restrict_to_measured({
        "score": total_score,
        "sub_scores": sub_scores,
        "max_sub_scores": max_sub_scores,
        "explanations": explanations,
        "deductions": deductions,
        "raw_metrics": {
            "avg_eye_contact": raw_eye,
            "avg_head_yaw": raw_yaw,
            "avg_head_pitch": raw_pitch,
            "avg_head_roll": raw_roll,
            "avg_emotion_valence": raw_emotion,
            "avg_posture_alignment": raw_posture,
            "avg_movement_level": raw_movement,
        },
    }, face_signals, FACE_FACTOR_METRICS, "Face/posture")


# =============================================================================
# MODULE 2: SPEECH CONFIDENCE SCORE (PURE FUNCTION)
# =============================================================================

def compute_speech_confidence_score(
    speech_signals: Dict[str, Any],
    transcript: str = "",
    word_timings: Optional[List[Dict[str, Any]]] = None,
    config: Optional[SpeechConfidenceConfig] = None,
) -> Dict[str, Any]:
    """
    Computes a normalized speech confidence score (0-100) based on:
    - Pace within an ideal range (configurable 120-160 WPM)
    - Filler word rate (penalizing um, uh, like, etc. above 2%)
    - Pause patterns (natural pauses vs long awkward silences)
    - Pitch and volume variability (expressive vs monotone/flat)
    - Audio clarity proxy

    Returns:
        {
            "score": float (0-100),
            "sub_scores": Dict[str, float],
            "max_sub_scores": Dict[str, float],
            "explanations": List[Dict[str, Any]],
            "deductions": List[Dict[str, Any]],
            "raw_metrics": Dict[str, Any],
        }
    """
    cfg = config or SpeechConfidenceConfig()

    explanations: List[Dict[str, Any]] = []
    deductions: List[Dict[str, Any]] = []
    sub_scores: Dict[str, float] = {}
    max_sub_scores: Dict[str, float] = {}

    # Extract raw metrics with sensible defaults
    raw_pace = _f(speech_signals, "avg_speech_pace_wpm", 135.0)
    raw_filler_rate = _f(speech_signals, "filler_rate", 0.015)
    raw_filler_count = int(_f(speech_signals, "total_fillers", 1))
    raw_pauses = int(_f(speech_signals, "total_pauses", 2))
    raw_pause_len = _f(speech_signals, "avg_pause_length", 1.2)
    raw_pitch_var = _f(speech_signals, "pitch_variance", 35.0)
    raw_vol_var = _f(speech_signals, "volume_variability", 22.0)
    raw_clarity = _f(speech_signals, "avg_clarity_proxy", 0.88)

    # 1. Speaking Pace (WPM)
    max_pace_pts = cfg.weight_pace * 100.0
    max_sub_scores["speech_pace"] = max_pace_pts
    if cfg.ideal_pace_min_wpm <= raw_pace <= cfg.ideal_pace_max_wpm:
        pace_pts = max_pace_pts
        pace_ded = 0.0
        pace_reason = f"Ideal speaking pace of {raw_pace:.1f} WPM (within target {cfg.ideal_pace_min_wpm:.0f}-{cfg.ideal_pace_max_wpm:.0f} WPM)."
    elif raw_pace < cfg.ideal_pace_min_wpm:
        deficit = cfg.ideal_pace_min_wpm - raw_pace
        max_deficit = cfg.ideal_pace_min_wpm - cfg.acceptable_pace_min_wpm
        fraction = max(0.0, min(1.0, 1.0 - (deficit / max(1.0, max_deficit))))
        pace_pts = fraction * max_pace_pts
        pace_ded = round(pace_pts - max_pace_pts, 1)
        pace_reason = f"Speaking pace of {raw_pace:.1f} WPM was too slow (below ideal {cfg.ideal_pace_min_wpm:.0f}-{cfg.ideal_pace_max_wpm:.0f} WPM)."
    else:  # raw_pace > cfg.ideal_pace_max_wpm
        excess = raw_pace - cfg.ideal_pace_max_wpm
        max_excess = cfg.acceptable_pace_max_wpm - cfg.ideal_pace_max_wpm
        fraction = max(0.0, min(1.0, 1.0 - (excess / max(1.0, max_excess))))
        pace_pts = fraction * max_pace_pts
        pace_ded = round(pace_pts - max_pace_pts, 1)
        pace_reason = f"Speaking pace of {raw_pace:.1f} WPM was rushed (above ideal {cfg.ideal_pace_min_wpm:.0f}-{cfg.ideal_pace_max_wpm:.0f} WPM)."

    sub_scores["speech_pace"] = round(pace_pts, 1)
    exp_pace = {
        "factor": "speech_pace",
        "earned_points": round(pace_pts, 1),
        "max_points": round(max_pace_pts, 1),
        "deduction": round(pace_ded, 1),
        "metric_value": f"{raw_pace:.1f} WPM",
        "reason": pace_reason,
    }
    explanations.append(exp_pace)
    if pace_ded < -0.1:
        deductions.append(exp_pace)

    # 2. Filler Word Rate
    max_filler_pts = cfg.weight_fillers * 100.0
    max_sub_scores["filler_rate"] = max_filler_pts
    if raw_filler_rate <= cfg.target_filler_rate:
        filler_pts = max_filler_pts
        filler_ded = 0.0
        filler_reason = f"Low filler word usage ({raw_filler_rate * 100:.1f}%, {raw_filler_count} fillers detected), indicating articulate delivery."
    elif raw_filler_rate >= cfg.max_filler_rate:
        filler_pts = 0.0
        filler_ded = -max_filler_pts
        filler_reason = f"High filler word rate ({raw_filler_rate * 100:.1f}%, {raw_filler_count} fillers: 'um', 'like', 'uh'), indicating frequent hesitation."
    else:
        span = cfg.max_filler_rate - cfg.target_filler_rate
        ratio = (raw_filler_rate - cfg.target_filler_rate) / max(0.001, span)
        filler_pts = max_filler_pts * (1.0 - ratio)
        filler_ded = round(filler_pts - max_filler_pts, 1)
        filler_reason = f"Moderate filler word rate of {raw_filler_rate * 100:.1f}% ({raw_filler_count} fillers), exceeding {cfg.target_filler_rate * 100:.1f}% target."

    sub_scores["filler_rate"] = round(filler_pts, 1)
    exp_filler = {
        "factor": "filler_rate",
        "earned_points": round(filler_pts, 1),
        "max_points": round(max_filler_pts, 1),
        "deduction": round(filler_ded, 1),
        "metric_value": f"{raw_filler_rate * 100:.1f}% ({raw_filler_count} fillers)",
        "reason": filler_reason,
    }
    explanations.append(exp_filler)
    if filler_ded < -0.1:
        deductions.append(exp_filler)

    # 3. Pause Patterns
    max_pause_pts = cfg.weight_pauses * 100.0
    max_sub_scores["pause_pattern"] = max_pause_pts
    if cfg.ideal_pause_length_min_sec <= raw_pause_len <= cfg.ideal_pause_length_max_sec and raw_pauses <= 6:
        pause_pts = max_pause_pts
        pause_ded = 0.0
        pause_reason = f"Natural pause cadence (average {raw_pause_len:.1f}s, {raw_pauses} pauses), reflecting comfortable pacing."
    elif raw_pause_len > cfg.excessive_pause_threshold_sec:
        excess = raw_pause_len - cfg.ideal_pause_length_max_sec
        fraction = max(0.2, 1.0 - (excess / 3.0))
        pause_pts = fraction * max_pause_pts
        pause_ded = round(pause_pts - max_pause_pts, 1)
        pause_reason = f"Noticeably long pauses between thoughts (average {raw_pause_len:.1f}s), suggesting hesitation or difficulty retrieving concepts."
    else:
        pause_pts = max_pause_pts * 0.85
        pause_ded = round(pause_pts - max_pause_pts, 1)
        pause_reason = f"Slightly irregular pause patterns (average {raw_pause_len:.1f}s, {raw_pauses} pauses)."

    sub_scores["pause_pattern"] = round(pause_pts, 1)
    exp_pause = {
        "factor": "pause_pattern",
        "earned_points": round(pause_pts, 1),
        "max_points": round(max_pause_pts, 1),
        "deduction": round(pause_ded, 1),
        "metric_value": f"{raw_pause_len:.1f}s avg ({raw_pauses} pauses)",
        "reason": pause_reason,
    }
    explanations.append(exp_pause)
    if pause_ded < -0.1:
        deductions.append(exp_pause)

    # 4. Pitch Variability
    max_pitch_pts = cfg.weight_pitch * 100.0
    max_sub_scores["pitch_variability"] = max_pitch_pts
    if cfg.ideal_pitch_variance_min <= raw_pitch_var <= cfg.ideal_pitch_variance_max:
        pitch_pts = max_pitch_pts
        pitch_ded = 0.0
        pitch_reason = f"Expressive vocal pitch inflection (pitch variance: {raw_pitch_var:.1f} Hz)."
    elif raw_pitch_var < cfg.ideal_pitch_variance_min:
        ratio = raw_pitch_var / max(1.0, cfg.ideal_pitch_variance_min)
        pitch_pts = max(0.0, max_pitch_pts * ratio)
        pitch_ded = round(pitch_pts - max_pitch_pts, 1)
        pitch_reason = f"Monotone vocal delivery with minimal inflection (pitch variance: {raw_pitch_var:.1f} Hz, below target {cfg.ideal_pitch_variance_min:.1f})."
    else:
        pitch_pts = max_pitch_pts * 0.8
        pitch_ded = round(pitch_pts - max_pitch_pts, 1)
        pitch_reason = f"Unusually high pitch fluctuation (pitch variance: {raw_pitch_var:.1f} Hz)."

    sub_scores["pitch_variability"] = round(pitch_pts, 1)
    exp_pitch = {
        "factor": "pitch_variability",
        "earned_points": round(pitch_pts, 1),
        "max_points": round(max_pitch_pts, 1),
        "deduction": round(pitch_ded, 1),
        "metric_value": f"{raw_pitch_var:.1f} Hz variance",
        "reason": pitch_reason,
    }
    explanations.append(exp_pitch)
    if pitch_ded < -0.1:
        deductions.append(exp_pitch)

    # 5. Volume Variability & Dynamics
    max_vol_pts = cfg.weight_volume * 100.0
    max_sub_scores["volume_variability"] = max_vol_pts
    if cfg.ideal_volume_variability_min <= raw_vol_var <= cfg.ideal_volume_variability_max:
        vol_pts = max_vol_pts
        vol_ded = 0.0
        vol_reason = f"Clear and balanced voice projection with healthy dynamic range (volume variability: {raw_vol_var:.1f})."
    elif raw_vol_var < cfg.ideal_volume_variability_min:
        ratio = raw_vol_var / max(1.0, cfg.ideal_volume_variability_min)
        vol_pts = max(0.0, max_vol_pts * ratio)
        vol_ded = round(vol_pts - max_vol_pts, 1)
        vol_reason = f"Flat voice projection with subdued energy (volume variability: {raw_vol_var:.1f})."
    else:
        vol_pts = max_vol_pts * 0.85
        vol_ded = round(vol_pts - max_vol_pts, 1)
        vol_reason = f"Inconsistent volume levels with sudden spikes or drops (volume variability: {raw_vol_var:.1f})."

    sub_scores["volume_variability"] = round(vol_pts, 1)
    exp_vol = {
        "factor": "volume_variability",
        "earned_points": round(vol_pts, 1),
        "max_points": round(max_vol_pts, 1),
        "deduction": round(vol_ded, 1),
        "metric_value": f"{raw_vol_var:.1f} variability",
        "reason": vol_reason,
    }
    explanations.append(exp_vol)
    if vol_ded < -0.1:
        deductions.append(exp_vol)

    # 6. Audio Clarity Proxy
    max_clarity_pts = cfg.weight_clarity * 100.0
    max_sub_scores["clarity"] = max_clarity_pts
    if raw_clarity >= cfg.target_clarity:
        clarity_pts = max_clarity_pts
        clarity_ded = 0.0
        clarity_reason = f"Crisp, clear audio signal with minimal background interference ({raw_clarity * 100:.1f}% clarity)."
    else:
        ratio = raw_clarity / max(0.1, cfg.target_clarity)
        clarity_pts = max(0.0, max_clarity_pts * ratio)
        clarity_ded = round(clarity_pts - max_clarity_pts, 1)
        clarity_reason = f"Subdued audio clarity ({raw_clarity * 100:.1f}%), suggesting muddled speech or room echo."

    sub_scores["clarity"] = round(clarity_pts, 1)
    exp_clarity = {
        "factor": "clarity",
        "earned_points": round(clarity_pts, 1),
        "max_points": round(max_clarity_pts, 1),
        "deduction": round(clarity_ded, 1),
        "metric_value": f"{raw_clarity * 100:.1f}%",
        "reason": clarity_reason,
    }
    explanations.append(exp_clarity)
    if clarity_ded < -0.1:
        deductions.append(exp_clarity)

    total_score = sum(sub_scores.values())
    total_score = max(0.0, min(100.0, round(total_score, 1)))

    return _restrict_to_measured({
        "score": total_score,
        "sub_scores": sub_scores,
        "max_sub_scores": max_sub_scores,
        "explanations": explanations,
        "deductions": deductions,
        "raw_metrics": {
            "avg_speech_pace_wpm": raw_pace,
            "filler_rate": raw_filler_rate,
            "total_fillers": raw_filler_count,
            "total_pauses": raw_pauses,
            "avg_pause_length": raw_pause_len,
            "pitch_variance": raw_pitch_var,
            "volume_variability": raw_vol_var,
            "avg_clarity_proxy": raw_clarity,
        },
    }, speech_signals, SPEECH_FACTOR_METRICS, "Speech")


# =============================================================================
# MODULE 3: CONTENT SCORE (RUBRIC) (PURE FUNCTION)
# =============================================================================

def compute_content_score(
    evaluator_scores: Dict[str, Any],
    question_metadata: Optional[Dict[str, Any]] = None,
    transcript: str = "",
    config: Optional[ContentRubricConfig] = None,
) -> Dict[str, Any]:
    """
    Computes a normalized content score (0-100) built from evaluator outputs:
    - Accuracy / correctness (from evaluator scores 0-10)
    - Depth (from evaluator scores 0-10)
    - Keyword coverage (matched keywords vs expected list)
    - STAR structure (for behavioral questions: Situation, Task, Action, Result)
    - Use of concrete examples, metrics, and case citations

    Returns:
        {
            "score": float (0-100),
            "sub_scores": Dict[str, float],
            "max_sub_scores": Dict[str, float],
            "explanations": List[Dict[str, Any]],
            "deductions": List[Dict[str, Any]],
            "raw_metrics": Dict[str, Any],
        }
    """
    cfg = config or ContentRubricConfig()
    q_meta = question_metadata or {}

    evaluator_scores = evaluator_scores or {}
    if not any(evaluator_scores.get(k) is not None for k in ("correctness", "relevance", "depth", "overall_score")):
        return {
            "score": None,
            "measured": False,
            "sub_scores": {},
            "max_sub_scores": {},
            "explanations": [],
            "deductions": [],
            "raw_metrics": {},
            "note": "This answer was not evaluated.",
        }

    explanations: List[Dict[str, Any]] = []
    deductions: List[Dict[str, Any]] = []
    sub_scores: Dict[str, float] = {}
    max_sub_scores: Dict[str, float] = {}

    # Extract evaluator metrics (each scored 0.0 - 10.0 in evaluator_service)
    raw_acc = float(evaluator_scores.get("correctness") or evaluator_scores.get("relevance") or 7.0)
    raw_depth = float(evaluator_scores.get("depth", 7.0))
    raw_relevance = float(evaluator_scores.get("relevance", 7.0))
    classification = str(evaluator_scores.get("classification", "OK")).upper()
    justification = str(evaluator_scores.get("justification", ""))

    # Keyword coverage metrics
    kw_data = evaluator_scores.get("keyword_coverage") or {}
    if isinstance(kw_data, dict):
        raw_kw_cov = float(kw_data.get("coverage_ratio", 0.75))
        matched_kw = kw_data.get("matched", [])
        missing_kw = kw_data.get("missing", [])
    else:
        raw_kw_cov = 0.75
        matched_kw = []
        missing_kw = []

    # STAR completeness metrics (for behavioral questions)
    star_data = evaluator_scores.get("star_completeness") or {}
    is_behavioral = False
    if isinstance(star_data, dict):
        is_behavioral = bool(star_data.get("is_behavioral", False))
    q_type = str(q_meta.get("type", "")).lower()
    q_topic = str(q_meta.get("topic", "")).lower()
    if q_type in ("behavioral", "situational", "hr", "leadership") or q_topic in ("hr", "behavioral", "leadership"):
        is_behavioral = True

    # Detect examples & metrics from transcript
    examples_res = detect_concrete_examples(transcript, cfg.example_marker_keywords)

    if not is_behavioral:
        # -------------------------------------------------------------
        # TECHNICAL / DOMAIN QUESTION RUBRIC
        # -------------------------------------------------------------
        # 1. Technical Accuracy / Correctness
        max_acc_pts = cfg.weight_technical_accuracy * 100.0
        max_sub_scores["accuracy"] = max_acc_pts
        acc_pts = max(0.0, min(max_acc_pts, (raw_acc / 10.0) * max_acc_pts))
        acc_ded = round(acc_pts - max_acc_pts, 1)
        if acc_ded < -0.1:
            acc_reason = f"Technical accuracy was rated {raw_acc:.1f}/10: {justification or 'Minor conceptual inaccuracies noted.'}"
        else:
            acc_reason = f"Sound technical accuracy rated {raw_acc:.1f}/10, demonstrating strong grasp of fundamentals."
        sub_scores["accuracy"] = round(acc_pts, 1)
        exp_acc = {
            "factor": "accuracy",
            "earned_points": round(acc_pts, 1),
            "max_points": round(max_acc_pts, 1),
            "deduction": round(acc_ded, 1),
            "metric_value": f"{raw_acc:.1f}/10",
            "reason": acc_reason,
        }
        explanations.append(exp_acc)
        if acc_ded < -0.1:
            deductions.append(exp_acc)

        # 2. Technical Depth
        max_depth_pts = cfg.weight_technical_depth * 100.0
        max_sub_scores["depth"] = max_depth_pts
        depth_pts = max(0.0, min(max_depth_pts, (raw_depth / 10.0) * max_depth_pts))
        depth_ded = round(depth_pts - max_depth_pts, 1)
        if depth_ded < -0.1:
            depth_reason = f"Explanation depth rated {raw_depth:.1f}/10: Lacked in-depth discussion of edge cases, trade-offs, or internal mechanisms."
        else:
            depth_reason = f"Thorough explanation depth rated {raw_depth:.1f}/10, discussing architectural nuances and trade-offs."
        sub_scores["depth"] = round(depth_pts, 1)
        exp_depth = {
            "factor": "depth",
            "earned_points": round(depth_pts, 1),
            "max_points": round(max_depth_pts, 1),
            "deduction": round(depth_ded, 1),
            "metric_value": f"{raw_depth:.1f}/10",
            "reason": depth_reason,
        }
        explanations.append(exp_depth)
        if depth_ded < -0.1:
            deductions.append(exp_depth)

        # 3. Keyword Coverage
        max_kw_pts = cfg.weight_technical_keywords * 100.0
        max_sub_scores["keyword_coverage"] = max_kw_pts
        if raw_kw_cov >= cfg.target_keyword_coverage:
            kw_pts = max_kw_pts
            kw_ded = 0.0
            kw_reason = f"Strong keyword coverage ({raw_kw_cov * 100:.1f}%), mentioning core terminology: {', '.join(matched_kw[:4])}."
        else:
            ratio = raw_kw_cov / max(0.01, cfg.target_keyword_coverage)
            kw_pts = max(0.0, min(max_kw_pts, ratio * max_kw_pts))
            kw_ded = round(kw_pts - max_kw_pts, 1)
            missing_str = f"Missing key terms: {', '.join(missing_kw[:4])}." if missing_kw else "Did not cover expected domain terms."
            kw_reason = f"Keyword coverage was {raw_kw_cov * 100:.1f}% (below {cfg.target_keyword_coverage * 100:.0f}% target). {missing_str}"
        sub_scores["keyword_coverage"] = round(kw_pts, 1)
        exp_kw = {
            "factor": "keyword_coverage",
            "earned_points": round(kw_pts, 1),
            "max_points": round(max_kw_pts, 1),
            "deduction": round(kw_ded, 1),
            "metric_value": f"{raw_kw_cov * 100:.1f}%",
            "reason": kw_reason,
        }
        explanations.append(exp_kw)
        if kw_ded < -0.1:
            deductions.append(exp_kw)

        # 4. Use of Concrete Examples
        max_ex_pts = cfg.weight_technical_examples * 100.0
        max_sub_scores["use_of_examples"] = max_ex_pts
        if examples_res["has_examples"]:
            ex_pts = max_ex_pts
            ex_ded = 0.0
            ex_reason = f"Grounded response in real-world examples and metrics ({', '.join(examples_res['metrics_cited'][:2]) or 'case study context'})."
        else:
            ex_pts = max(0.0, max_ex_pts * 0.4)
            ex_ded = round(ex_pts - max_ex_pts, 1)
            ex_reason = "Answer was theoretical without concrete production examples, quantitative metrics, or code snippets."
        sub_scores["use_of_examples"] = round(ex_pts, 1)
        exp_ex = {
            "factor": "use_of_examples",
            "earned_points": round(ex_pts, 1),
            "max_points": round(max_ex_pts, 1),
            "deduction": round(ex_ded, 1),
            "metric_value": f"{examples_res['count']} citations",
            "reason": ex_reason,
        }
        explanations.append(exp_ex)
        if ex_ded < -0.1:
            deductions.append(exp_ex)

    else:
        # -------------------------------------------------------------
        # BEHAVIORAL / SITUATIONAL QUESTION RUBRIC (STAR)
        # -------------------------------------------------------------
        # 1. Relevance & Accuracy
        max_acc_pts = cfg.weight_behavioral_accuracy * 100.0
        max_sub_scores["accuracy"] = max_acc_pts
        acc_pts = max(0.0, min(max_acc_pts, (raw_relevance / 10.0) * max_acc_pts))
        acc_ded = round(acc_pts - max_acc_pts, 1)
        if acc_ded < -0.1:
            acc_reason = f"Response relevance rated {raw_relevance:.1f}/10: Did not directly address the behavioral prompt."
        else:
            acc_reason = f"Direct and focused response to the scenario ({raw_relevance:.1f}/10 relevance)."
        sub_scores["accuracy"] = round(acc_pts, 1)
        exp_acc = {
            "factor": "accuracy",
            "earned_points": round(acc_pts, 1),
            "max_points": round(max_acc_pts, 1),
            "deduction": round(acc_ded, 1),
            "metric_value": f"{raw_relevance:.1f}/10",
            "reason": acc_reason,
        }
        explanations.append(exp_acc)
        if acc_ded < -0.1:
            deductions.append(exp_acc)

        # 2. Reflection & Depth
        max_depth_pts = cfg.weight_behavioral_depth * 100.0
        max_sub_scores["depth"] = max_depth_pts
        depth_pts = max(0.0, min(max_depth_pts, (raw_depth / 10.0) * max_depth_pts))
        depth_ded = round(depth_pts - max_depth_pts, 1)
        if depth_ded < -0.1:
            depth_reason = f"Depth of reflection rated {raw_depth:.1f}/10: Lacked personal takeaway, learning, or impact."
        else:
            depth_reason = f"Thoughtful self-reflection and ownership demonstrated ({raw_depth:.1f}/10 depth)."
        sub_scores["depth"] = round(depth_pts, 1)
        exp_depth = {
            "factor": "depth",
            "earned_points": round(depth_pts, 1),
            "max_points": round(max_depth_pts, 1),
            "deduction": round(depth_ded, 1),
            "metric_value": f"{raw_depth:.1f}/10",
            "reason": depth_reason,
        }
        explanations.append(exp_depth)
        if depth_ded < -0.1:
            deductions.append(exp_depth)

        # 3. Behavioral Keywords / Competencies
        max_kw_pts = cfg.weight_behavioral_keywords * 100.0
        max_sub_scores["keyword_coverage"] = max_kw_pts
        ratio = min(1.0, raw_kw_cov / max(0.01, cfg.target_keyword_coverage))
        kw_pts = ratio * max_kw_pts
        kw_ded = round(kw_pts - max_kw_pts, 1)
        kw_reason = f"Behavioral competency coverage was {raw_kw_cov * 100:.1f}%."
        sub_scores["keyword_coverage"] = round(kw_pts, 1)
        exp_kw = {
            "factor": "keyword_coverage",
            "earned_points": round(kw_pts, 1),
            "max_points": round(max_kw_pts, 1),
            "deduction": round(kw_ded, 1),
            "metric_value": f"{raw_kw_cov * 100:.1f}%",
            "reason": kw_reason,
        }
        explanations.append(exp_kw)
        if kw_ded < -0.1:
            deductions.append(exp_kw)

        # 4. STAR Structure Completeness (30 pts max)
        max_star_pts = cfg.weight_behavioral_star * 100.0
        max_sub_scores["star_structure"] = max_star_pts
        # 4 components: Situation (7.5), Task (7.5), Action (7.5), Result (7.5)
        sit = bool(star_data.get("situation", True))
        tsk = bool(star_data.get("task", True))
        act = bool(star_data.get("action", True))
        res = bool(star_data.get("result", True))

        pts_per_elem = max_star_pts / 4.0
        star_pts = (
            (pts_per_elem if sit else 0.0) +
            (pts_per_elem if tsk else 0.0) +
            (pts_per_elem if act else 0.0) +
            (pts_per_elem if res else 0.0)
        )
        star_ded = round(star_pts - max_star_pts, 1)

        missing_elements = []
        if not sit:
            missing_elements.append("Situation")
        if not tsk:
            missing_elements.append("Task")
        if not act:
            missing_elements.append("Action")
        if not res:
            missing_elements.append("Result")

        if missing_elements:
            star_reason = f"STAR structure incomplete: Missing [{', '.join(missing_elements)}]. Failed to specify context or measurable business results."
        else:
            star_reason = "Complete STAR structure followed seamlessly (clear Situation, Task, Action, and quantifiable Result)."

        sub_scores["star_structure"] = round(star_pts, 1)
        exp_star = {
            "factor": "star_structure",
            "earned_points": round(star_pts, 1),
            "max_points": round(max_star_pts, 1),
            "deduction": round(star_ded, 1),
            "metric_value": f"{4 - len(missing_elements)}/4 STAR components",
            "reason": star_reason,
        }
        explanations.append(exp_star)
        if star_ded < -0.1:
            deductions.append(exp_star)

        # 5. Use of Concrete Examples & Metrics
        max_ex_pts = cfg.weight_behavioral_examples * 100.0
        max_sub_scores["use_of_examples"] = max_ex_pts
        if examples_res["has_examples"] and res:
            ex_pts = max_ex_pts
            ex_ded = 0.0
            ex_reason = f"Included tangible metrics and outcomes ({', '.join(examples_res['metrics_cited'][:2]) or 'concrete project numbers'})."
        else:
            ex_pts = max(0.0, max_ex_pts * 0.4)
            ex_ded = round(ex_pts - max_ex_pts, 1)
            ex_reason = "Lacked concrete measurable outcomes or specific project metrics in the response."
        sub_scores["use_of_examples"] = round(ex_pts, 1)
        exp_ex = {
            "factor": "use_of_examples",
            "earned_points": round(ex_pts, 1),
            "max_points": round(max_ex_pts, 1),
            "deduction": round(ex_ded, 1),
            "metric_value": f"{examples_res['count']} citations",
            "reason": ex_reason,
        }
        explanations.append(exp_ex)
        if ex_ded < -0.1:
            deductions.append(exp_ex)

    total_score = sum(sub_scores.values())
    total_score = max(0.0, min(100.0, round(total_score, 1)))

    return {
        "score": total_score,
        "is_behavioral": is_behavioral,
        "classification": classification,
        "sub_scores": sub_scores,
        "max_sub_scores": max_sub_scores,
        "explanations": explanations,
        "deductions": deductions,
        "raw_metrics": {
            "correctness": raw_acc,
            "depth": raw_depth,
            "relevance": raw_relevance,
            "keyword_coverage_ratio": raw_kw_cov,
            "matched_keywords": matched_kw,
            "missing_keywords": missing_kw,
            "is_behavioral": is_behavioral,
            "example_count": examples_res["count"],
        },
    }


# =============================================================================
# PER-QUESTION COMPOSITE SCORER (PURE FUNCTION)
# =============================================================================

def compute_question_score(
    question_aligned_data: Dict[str, Any],
    baseline: Optional[Dict[str, Any]] = None,
    config: Optional[ScoringConfig] = None,
) -> Dict[str, Any]:
    """
    Computes all three scoring modules for a single aligned question record
    and calculates a normalized composite score for that question.

    Returns:
        {
            "question_id": int,
            "topic": str,
            "composite_score": float (0-100),
            "face_posture": Dict[str, Any],
            "speech_confidence": Dict[str, Any],
            "content": Dict[str, Any],
            "all_deductions": List[Dict[str, Any]],
            "all_explanations": List[Dict[str, Any]],
        }
    """
    cfg = config or DEFAULT_SCORING_CONFIG
    q_id = question_aligned_data.get("question_id", 1)
    topic = question_aligned_data.get("topic", "General")
    transcript = question_aligned_data.get("transcript", "")
    face_sigs = question_aligned_data.get("face_signals", {})
    speech_sigs = question_aligned_data.get("speech_signals", {})
    eval_scores = question_aligned_data.get("evaluator_scores", {})
    timings = question_aligned_data.get("word_timings", [])

    # 1. Face & Posture Module
    face_res = compute_face_and_posture_score(face_sigs, baseline=baseline, config=cfg.face_posture)

    # 2. Speech Confidence Module
    speech_res = compute_speech_confidence_score(speech_sigs, transcript=transcript, word_timings=timings, config=cfg.speech_confidence)

    # 3. Content Rubric Module
    content_res = compute_content_score(eval_scores, question_metadata=question_aligned_data, transcript=transcript, config=cfg.content_rubric)

    # Composite weighted average
    w_content = cfg.session_weights.content_weight
    w_speech = cfg.session_weights.speech_confidence_weight
    w_face = cfg.session_weights.face_posture_weight

    # Unmeasured modules (score None) are excluded and the weights renormalized.
    composite = _weighted_available([
        (content_res["score"], w_content),
        (speech_res["score"], w_speech),
        (face_res["score"], w_face),
    ])
    composite = max(0.0, min(100.0, round(composite, 1))) if composite is not None else None

    all_deductions = []
    for d in (content_res["deductions"] + speech_res["deductions"] + face_res["deductions"]):
        all_deductions.append({
            "question_id": q_id,
            "category": "content" if d in content_res["deductions"] else ("speech" if d in speech_res["deductions"] else "face"),
            **d,
        })
    # Sort deductions by impact (largest negative first)
    all_deductions.sort(key=lambda x: x["deduction"])

    all_explanations = []
    for e in (content_res["explanations"] + speech_res["explanations"] + face_res["explanations"]):
        all_explanations.append({
            "question_id": q_id,
            "category": "content" if e in content_res["explanations"] else ("speech" if e in speech_res["explanations"] else "face"),
            **e,
        })

    return {
        "question_id": q_id,
        "question_text": question_aligned_data.get("question_text", ""),
        "topic": topic,
        "composite_score": composite,
        "face_posture": face_res,
        "speech_confidence": speech_res,
        "content": content_res,
        "all_deductions": all_deductions,
        "all_explanations": all_explanations,
    }


# =============================================================================
# SESSION-LEVEL AGGREGATOR & REPORT BUILDER (PURE FUNCTION)
# =============================================================================

def compute_session_scores(
    aligned_session_data: Dict[str, Any],
    config: Optional[ScoringConfig] = None,
) -> Dict[str, Any]:
    """
    Pure function that evaluates an entire session's aligned dataset,
    aggregating across all questions to generate session-level scores,
    per-question breakdowns, and ordered explanations.

    Returns:
        {
            "session_id": int,
            "overall_scores": {
                "face_posture_score": float,
                "speech_confidence_score": float,
                "content_score": float,
                "composite_score": float,
            },
            "classification": "STRONG" | "AVERAGE" | "WEAK",
            "per_question_breakdown": List[Dict[str, Any]],
            "top_deductions": List[Dict[str, Any]],
            "key_strengths": List[str],
            "areas_for_improvement": List[str],
            "total_questions": int,
        }
    """
    cfg = config or DEFAULT_SCORING_CONFIG
    sess_id = aligned_session_data.get("session_id", 1)
    baseline = aligned_session_data.get("calibration", {})
    questions = aligned_session_data.get("questions", [])

    if not questions:
        # Nothing was answered: nothing to score.
        return {
            "session_id": sess_id,
            "overall_scores": {
                "face_posture_score": None,
                "speech_confidence_score": None,
                "content_score": None,
                "composite_score": None,
            },
            "classification": "NOT_SCORED",
            "per_question_breakdown": [],
            "top_deductions": [],
            "key_strengths": [],
            "areas_for_improvement": ["No questions completed in this session."],
            "total_questions": 0,
        }

    q_breakdowns: List[Dict[str, Any]] = []
    face_scores: List[float] = []
    speech_scores: List[float] = []
    content_scores: List[float] = []
    composite_scores: List[float] = []
    all_session_deductions: List[Dict[str, Any]] = []

    for q_data in questions:
        q_res = compute_question_score(q_data, baseline=baseline, config=cfg)
        q_breakdowns.append(q_res)
        face_scores.append(q_res["face_posture"]["score"])
        speech_scores.append(q_res["speech_confidence"]["score"])
        content_scores.append(q_res["content"]["score"])
        composite_scores.append(q_res["composite_score"])
        all_session_deductions.extend(q_res["all_deductions"])

    avg_face = _mean_or_none(face_scores)
    avg_speech = _mean_or_none(speech_scores)
    avg_content = _mean_or_none(content_scores)

    w_content = cfg.session_weights.content_weight
    w_speech = cfg.session_weights.speech_confidence_weight
    w_face = cfg.session_weights.face_posture_weight

    overall_composite = _weighted_available([(avg_content, w_content), (avg_speech, w_speech), (avg_face, w_face)])
    overall_composite = max(0.0, min(100.0, round(overall_composite, 1))) if overall_composite is not None else None

    if overall_composite is None:
        classification = "NOT_SCORED"
    elif overall_composite >= 80.0:
        classification = "STRONG"
    elif overall_composite >= 60.0:
        classification = "AVERAGE"
    else:
        classification = "WEAK"

    # Sort all session deductions by impact
    all_session_deductions.sort(key=lambda x: x["deduction"])

    # Extract distinct key strengths and areas for improvement
    key_strengths: List[str] = []
    if avg_content is not None and avg_content >= 80.0:
        key_strengths.append(f"Strong content proficiency ({avg_content}/100) with accurate technical depth.")
    if avg_speech is not None and avg_speech >= 80.0:
        key_strengths.append(f"Confident, articulate vocal pacing ({avg_speech}/100) with minimal fillers.")
    if avg_face is not None and avg_face >= 80.0:
        key_strengths.append(f"Exceptional eye contact and composed camera presence ({avg_face}/100).")
    if not key_strengths:
        key_strengths.append("Demonstrated foundational familiarity with interview topics.")

    areas_for_improvement: List[str] = []
    seen_factors = set()
    for ded in all_session_deductions:
        factor = ded.get("factor")
        if factor not in seen_factors and ded.get("deduction", 0) <= -2.0:
            seen_factors.add(factor)
            areas_for_improvement.append(
                f"[Q#{ded.get('question_id')} {ded.get('factor').replace('_', ' ').title()}: {ded.get('deduction')} pts] {ded.get('reason')}"
            )
            if len(areas_for_improvement) >= 5:
                break

    if not areas_for_improvement:
        areas_for_improvement.append("Maintain current high performance consistency across all question types.")

    return {
        "session_id": sess_id,
        "overall_scores": {
            "face_posture_score": avg_face,
            "speech_confidence_score": avg_speech,
            "content_score": avg_content,
            "composite_score": overall_composite,
        },
        "classification": classification,
        "per_question_breakdown": q_breakdowns,
        "top_deductions": all_session_deductions[:10],
        "key_strengths": key_strengths,
        "areas_for_improvement": areas_for_improvement,
        "total_questions": len(questions),
        "not_measured": [name for name, v in (("face_posture", avg_face), ("speech_confidence", avg_speech)) if v is None],
    }
