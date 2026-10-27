"""Unmeasured signals must surface as None / 'not measured', never as plausible defaults."""
from app.services.scoring_engine import compute_session_scores, compute_face_and_posture_score
from app.services.score_fusion_service import fuse_session_scores, compute_cohort_percentile
from app.services.report_generator_service import generate_initial_report
from app.services.signal_workers import AudioSignalWorker


def _aligned(face=None, speech=None, evaluator=None):
    return {
        "session_id": 1,
        "calibration": {},
        "questions": [{
            "question_id": 1,
            "topic": "DSA",
            "transcript": "I would use a hash map and two pointers for O(n).",
            "word_timings": [],
            "face_signals": face if face is not None else {"samples_count": 0},
            "speech_signals": speech if speech is not None else {"samples_count": 0},
            "evaluator_scores": evaluator if evaluator is not None else {
                "relevance": 8.0, "correctness": 7.0, "depth": 6.0, "overall_score": 7.0, "classification": "OK",
            },
        }],
    }


def test_no_face_or_speech_signals_are_not_scored():
    rep = compute_session_scores(_aligned())
    q = rep["per_question_breakdown"][0]
    assert q["face_posture"]["score"] is None and q["face_posture"]["measured"] is False
    assert q["speech_confidence"]["score"] is None
    assert rep["overall_scores"]["face_posture_score"] is None
    assert rep["overall_scores"]["speech_confidence_score"] is None
    # composite falls back to the measured component only (content)
    assert rep["overall_scores"]["composite_score"] == rep["overall_scores"]["content_score"]
    assert set(rep["not_measured"]) == {"face_posture", "speech_confidence"}


def test_partially_measured_face_excludes_missing_factors():
    res = compute_face_and_posture_score({"avg_eye_contact": 0.95})
    assert res["measured_factors"] == ["eye_contact"]
    assert "posture" in res["unmeasured_factors"]
    assert res["score"] == 100.0  # 100% of the one measured factor, not padded with defaults
    assert all(e["factor"] == "eye_contact" for e in res["explanations"])


def test_unevaluated_answer_has_no_content_score():
    rep = compute_session_scores(_aligned(evaluator={}))
    assert rep["overall_scores"]["content_score"] is None
    assert rep["overall_scores"]["composite_score"] is None
    assert rep["classification"] == "NOT_SCORED"


def test_fusion_and_report_handle_none():
    fused = fuse_session_scores(compute_session_scores(_aligned()), round_type="Technical")
    assert fused["overall_scores"]["face_posture_score"] is None
    assert fused["overall_scores"]["composite_score"] is not None
    report = generate_initial_report({
        "overall_score": fused["overall_scores"]["composite_score"],
        "content_score": fused["overall_scores"]["content_score"],
        "speech_score": None,
        "face_score": None,
        "classification": fused["classification"],
        "per_question_scores": fused["per_question_breakdown"],
        "comparisons": {"cohort": compute_cohort_percentile(70.0, "Technical", [])},
        "weights_used": fused["weights_used"],
        "weak_areas": [],
    })
    assert "not measured" in report["overall_summary"]
    assert "percentile" not in report["overall_summary"]


def test_silent_audio_reports_no_pace_or_pitch():
    m = AudioSignalWorker().process_chunk(session_id=5, audio_bytes=b"\x00\x00" * 4000, timestamp=0.0, duration=0.25)
    assert "speech_pace_wpm" not in m
    assert "pitch_hz" not in m
    assert "filler_rate" not in m
