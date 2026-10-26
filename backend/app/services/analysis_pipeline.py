"""
Session Close & Analysis Pipeline (Phase 5.1).
- Closes the interview session and finalizes recordings (merged audio & video manifest).
- Manages an idempotent background analysis job queue (Redis + async task runner) with exponential backoff retry.
- Alignment Engine: Aligns transcript, word timings, face signals, speech signals, integrity events,
  and evaluator scores by timestamp into one per-question dataset.
- Resilient failure handling: Marks broken sections as partial and manifests missing sections for report generation.
"""

import os
import time
import json
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import (
    InterviewSession,
    SessionAnalysisJob,
    SignalTimeSeries,
    IntegrityEvent,
    SessionCalibration,
    QuestionBankItem,
)
from app.services.answer_capture_service import default_storage_manager, AnswerStorageManager
from app.services.session_state import default_state_store


def _avg(by: Dict[str, List[float]], key: str, nd: int) -> Optional[float]:
    vals = by.get(key)
    return round(sum(vals) / len(vals), nd) if vals else None


def _var(by: Dict[str, List[float]], key: str, nd: int) -> Optional[float]:
    vals = by.get(key)
    if not vals or len(vals) < 3:
        return None
    m = sum(vals) / len(vals)
    return round(sum((v - m) ** 2 for v in vals) / len(vals), nd)


def _std(by: Dict[str, List[float]], key: str, nd: int) -> Optional[float]:
    v = _var(by, key, 6)
    return round(v ** 0.5, nd) if v is not None else None

import threading


def _on_event_loop_thread() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False

logger = logging.getLogger("intervai.analysis_pipeline")


# =============================================================================
# 1. ALIGNMENT ENGINE
# =============================================================================

class AlignmentEngine:
    """
    Correlates and aligns signals, transcripts, word timings, integrity events,
    and evaluator scores into a unified per-question record.
    """

    def __init__(self, storage_manager: Optional[AnswerStorageManager] = None):
        self.storage = storage_manager or default_storage_manager

    def align_session(self, session_id: int) -> Dict[str, Any]:
        """
        Builds the unified per-question aligned dataset for the session.
        If any individual analysis component fails, records it in missing_sections and continues.
        """
        db: Session = SessionLocal()
        missing_sections: List[str] = []
        is_partial = False

        try:
            sess: Optional[InterviewSession] = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
            if not sess:
                raise ValueError(f"Interview session #{session_id} not found.")

            # Load question list and evaluations from Redis / state store session context
            saved_state = default_state_store.load_state(session_id)
            session_ctx = saved_state.session_context if saved_state else []

            # Also check QuestionBankItems or storage directories if session_ctx is empty
            question_ids: List[int] = []
            if session_ctx:
                for item in session_ctx:
                    qid = item.get("question_id") or item.get("id")
                    if qid and qid not in question_ids:
                        question_ids.append(qid)

            # Check question folders on disk as backup
            sess_disk_dir = os.path.join(self.storage.base_dir, str(session_id))
            if os.path.exists(sess_disk_dir):
                disk_qids = [int(d) for d in os.listdir(sess_disk_dir) if d.isdigit()]
                for dq in sorted(disk_qids):
                    if dq not in question_ids:
                        question_ids.append(dq)

            if not question_ids:
                question_ids = [1]  # Default fallback question 1

            # Query all signals and integrity events for this session
            all_signals: List[SignalTimeSeries] = (
                db.query(SignalTimeSeries)
                .filter(SignalTimeSeries.session_id == session_id)
                .order_by(SignalTimeSeries.timestamp.asc())
                .all()
            )

            all_integrity: List[IntegrityEvent] = (
                db.query(IntegrityEvent)
                .filter(IntegrityEvent.session_id == session_id)
                .order_by(IntegrityEvent.start_time.asc())
                .all()
            )

            # Query calibration for reference
            cal_rec = db.query(SessionCalibration).filter(SessionCalibration.session_id == session_id).first()
            calibration_dict = {
                "face_baseline": cal_rec.face_baseline if cal_rec else {},
                "voice_baseline": cal_rec.voice_baseline if cal_rec else {},
            }

            aligned_questions: List[Dict[str, Any]] = []

            for q_id in question_ids:
                q_missing: List[str] = []

                # Find session context item if available
                ctx_item = next((item for item in session_ctx if (item.get("question_id") == q_id or item.get("id") == q_id)), {})
                q_text = ctx_item.get("question_text") or ctx_item.get("question") or f"Question #{q_id}"
                topic = ctx_item.get("topic", "General")
                subtopic = ctx_item.get("subtopic", "")
                difficulty = ctx_item.get("difficulty", "Medium")

                # 1. Transcript & Word Timings
                transcript_text = ""
                word_timings = []
                try:
                    art = self.storage.get_question_artifacts(session_id, q_id)
                    t_data = art.get("transcript")
                    if t_data:
                        transcript_text = t_data.get("text", "")
                        word_timings = t_data.get("words", [])
                    elif ctx_item.get("answer"):
                        transcript_text = ctx_item.get("answer")
                    else:
                        q_missing.append("transcript")
                except Exception as e:
                    logger.warning("Error loading transcript for session %d q %d: %s", session_id, q_id, e)
                    q_missing.append("transcript")

                # 2. Face Signals Alignment
                face_signals = {}
                try:
                    q_signals = [s for s in all_signals if s.question_id == q_id]
                    if not q_signals and all_signals:
                        # Fallback: if only 1 question, assign all
                        if len(question_ids) == 1:
                            q_signals = all_signals

                    face_metric_names = [
                        "face_present", "eye_contact", "head_yaw", "head_pitch", "head_roll",
                        "emotion_valence", "posture_alignment", "movement_level",
                    ]
                    by_m: Dict[str, List[float]] = {}
                    ts_points: List[Dict[str, Any]] = []

                    for s in q_signals:
                        if s.metric in face_metric_names:
                            by_m.setdefault(s.metric, []).append(s.value)
                            ts_points.append({"timestamp": s.timestamp, "metric": s.metric, "value": s.value})

                    if by_m:
                        # Averages only over metrics that were actually measured; a metric
                        # with no samples is omitted (scoring treats it as "not measured").
                        face_signals = {
                            "avg_eye_contact": _avg(by_m, "eye_contact", 3),
                            "avg_head_yaw": _avg(by_m, "head_yaw", 2),
                            "avg_head_pitch": _avg(by_m, "head_pitch", 2),
                            "avg_head_roll": _avg(by_m, "head_roll", 2),
                            "avg_emotion_valence": _avg(by_m, "emotion_valence", 2),
                            "avg_posture_alignment": _avg(by_m, "posture_alignment", 3),
                            "avg_movement_level": _avg(by_m, "movement_level", 3),
                            "face_present_ratio": _avg(by_m, "face_present", 3),
                        }
                        face_signals = {k: v for k, v in face_signals.items() if v is not None}
                        face_signals["samples_count"] = len(ts_points)
                    else:
                        q_missing.append("face_signals")
                        face_signals = {"samples_count": 0}
                except Exception as e:
                    logger.warning("Error aligning face signals: %s", e)
                    q_missing.append("face_signals")

                # 3. Speech Signals Alignment
                speech_signals = {}
                try:
                    speech_metric_names = [
                        "volume_rms", "pitch_hz", "speech_pace_wpm", "filler_count",
                        "filler_rate", "pause_count", "avg_pause_length", "clarity_proxy",
                    ]
                    by_sm: Dict[str, List[float]] = {}
                    for s in q_signals:
                        if s.metric in speech_metric_names:
                            by_sm.setdefault(s.metric, []).append(s.value)

                    if by_sm:
                        speech_signals = {
                            "avg_speech_pace_wpm": _avg(by_sm, "speech_pace_wpm", 1),
                            "total_fillers": int(max(by_sm["filler_count"])) if by_sm.get("filler_count") else None,
                            "filler_rate": _avg(by_sm, "filler_rate", 3),
                            "avg_pitch_hz": _avg(by_sm, "pitch_hz", 1),
                            "pitch_variance": _var(by_sm, "pitch_hz", 2),
                            "avg_volume_rms": _avg(by_sm, "volume_rms", 1),
                            "volume_variability": _std(by_sm, "volume_rms", 2),
                            "total_pauses": int(max(by_sm["pause_count"])) if by_sm.get("pause_count") else None,
                            "avg_pause_length": _avg(by_sm, "avg_pause_length", 2),
                            "avg_clarity_proxy": _avg(by_sm, "clarity_proxy", 2),
                        }
                        speech_signals = {k: v for k, v in speech_signals.items() if v is not None}
                        speech_signals["samples_count"] = sum(len(v) for v in by_sm.values())
                    else:
                        q_missing.append("speech_signals")
                        speech_signals = {"samples_count": 0}
                except Exception as e:
                    logger.warning("Error aligning speech signals: %s", e)
                    q_missing.append("speech_signals")

                # 4. Integrity Events Alignment
                q_integrity_events = []
                try:
                    matched_events = [
                        {
                            "id": ev.id,
                            "type": ev.type,
                            "severity": ev.severity,
                            "start_time": ev.start_time,
                            "duration_seconds": ev.duration_seconds,
                            "details": ev.details or {},
                        }
                        for ev in all_integrity
                        if ev.question_id == q_id or ev.question_id is None
                    ]
                    q_integrity_events = matched_events
                except Exception as e:
                    logger.warning("Error aligning integrity events: %s", e)
                    q_missing.append("integrity_events")

                # 5. Evaluator Scores
                evaluator_scores = {}
                try:
                    eval_data = ctx_item.get("evaluation") or ctx_item.get("scores")
                    if eval_data:
                        evaluator_scores = eval_data
                    elif ctx_item.get("score") is not None:
                        # Live evaluation stored inline on the session context item
                        evaluator_scores = {
                            k: ctx_item[k]
                            for k in ("relevance", "correctness", "depth", "classification", "justification",
                                      "keyword_coverage", "star_completeness", "evaluation_source")
                            if ctx_item.get(k) is not None
                        }
                        evaluator_scores["overall_score"] = ctx_item["score"]
                    else:
                        # Never evaluated: leave empty so content is reported as not scored.
                        q_missing.append("evaluator_scores")
                except Exception as e:
                    logger.warning("Error aligning evaluator scores: %s", e)
                    q_missing.append("evaluator_scores")

                if q_missing:
                    is_partial = True
                    for m in q_missing:
                        if m not in missing_sections:
                            missing_sections.append(m)

                aligned_questions.append({
                    "question_id": q_id,
                    "question_text": q_text,
                    "topic": topic,
                    "subtopic": subtopic,
                    "difficulty": difficulty,
                    "transcript": transcript_text,
                    "word_timings": word_timings,
                    "face_signals": face_signals,
                    "speech_signals": speech_signals,
                    "integrity_events": q_integrity_events,
                    "evaluator_scores": evaluator_scores,
                    "is_partial": len(q_missing) > 0,
                    "missing_sections": q_missing,
                })

            # Save aligned JSON dataset artifact
            sess_dir = os.path.join(self.storage.base_dir, str(session_id))
            os.makedirs(sess_dir, exist_ok=True)
            aligned_file_path = os.path.join(sess_dir, "aligned_session_data.json")

            aligned_payload = {
                "session_id": session_id,
                "aligned_at": time.time(),
                "is_partial": is_partial,
                "missing_sections": missing_sections,
                "calibration": calibration_dict,
                "total_questions": len(aligned_questions),
                "questions": aligned_questions,
            }

            # Compute normalized scoring module results (Phase 5.2)
            try:
                from app.services.scoring_engine import compute_session_scores
                aligned_payload["scores"] = compute_session_scores(aligned_payload)
            except Exception as score_err:
                logger.warning("Error computing scores during alignment for session #%d: %s", session_id, score_err)
                aligned_payload["scores"] = {}

            with open(aligned_file_path, "w", encoding="utf-8") as f:
                json.dump(aligned_payload, f, indent=2)

            aligned_file_key = f"sessions/{session_id}/aligned_session_data.json"
            aligned_payload["file_key"] = aligned_file_key
            aligned_payload["file_path"] = aligned_file_path

            return aligned_payload

        finally:
            db.close()


default_alignment_engine = AlignmentEngine()


# =============================================================================
# 2. ANALYSIS JOB QUEUE & WORKER WITH RETRY / BACKOFF & IDEMPOTENCY
# =============================================================================

class AnalysisJobManager:
    """
    Manages analysis jobs with:
    - Queueing & worker execution (Redis backed with robust fallback)
    - Idempotency per session_id (session_analysis:{session_id})
    - Exponential backoff retry for transient errors
    - Fine-grained progress reporting
    """

    def __init__(
        self,
        storage_manager: Optional[AnswerStorageManager] = None,
        alignment_engine: Optional[AlignmentEngine] = None,
    ):
        self.storage = storage_manager or default_storage_manager
        self.aligner = alignment_engine or default_alignment_engine
        # In-memory active job status cache for instantaneous responses
        self._memory_jobs: Dict[int, Dict[str, Any]] = {}

    def _get_idempotency_key(self, session_id: int) -> str:
        return f"session_analysis:{session_id}"

    def get_job_status(self, session_id: int) -> Dict[str, Any]:
        """Returns the current status of the analysis job for a session."""
        # 1. Check in-memory active cache
        if session_id in self._memory_jobs:
            return dict(self._memory_jobs[session_id])

        # 2. Check Database
        db: Session = SessionLocal()
        try:
            job = db.query(SessionAnalysisJob).filter(SessionAnalysisJob.session_id == session_id).first()
            if job:
                return {
                    "session_id": session_id,
                    "job_id": job.job_id,
                    "status": job.status,
                    "progress": job.progress,
                    "current_step": job.current_step,
                    "is_partial": job.is_partial,
                    "missing_sections": job.missing_sections or [],
                    "error_message": job.error_message,
                    "retry_count": job.retry_count,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                }
        finally:
            db.close()

        # 3. Not found
        return {
            "session_id": session_id,
            "job_id": None,
            "status": "not_started",
            "progress": 0,
            "current_step": "idle",
            "is_partial": False,
            "missing_sections": [],
            "error_message": None,
        }

    def close_and_finalize_session(self, session_id: int) -> Dict[str, Any]:
        """
        Step 1: Finalizes recordings, updates Session status to CLOSED, and stores file keys.
        """
        # A. Finalize recordings
        rec_meta = self.storage.finalize_session_recordings(session_id)

        # B. Update database session status to CLOSED and store file keys
        db: Session = SessionLocal()
        try:
            sess = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
            if sess:
                sess.status = "CLOSED"
                sess.ended_at = datetime.now(timezone.utc)
                sess.audio_file_key = rec_meta.get("audio_file_key")
                sess.video_file_key = rec_meta.get("video_file_key")
                db.commit()
                db.refresh(sess)
        finally:
            db.close()

        logger.info("Session #%d closed and recordings finalized.", session_id)
        return rec_meta

    def run_analysis_pipeline_sync(
        self,
        session_id: int,
        job_id: str,
        max_retries: int = 3,
        simulate_failure_step: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes the analysis pipeline synchronously with idempotency and retry backoff.
        Used for predictable execution, worker loops, and testing.
        """
        retries = 0
        backoff_delay = 0.2

        while retries <= max_retries:
            try:
                # 1. Update status -> processing (10%)
                self._update_job(
                    session_id=session_id,
                    job_id=job_id,
                    status="processing",
                    progress=15,
                    current_step="Merging recordings & updating session status",
                )

                # Finalize recordings & mark CLOSED if not already
                rec_meta = self.close_and_finalize_session(session_id)

                if simulate_failure_step == "finalize" and retries == 0:
                    raise RuntimeError("Simulated transient error during recording finalization")

                # 2. Update status -> processing (45%)
                self._update_job(
                    session_id=session_id,
                    job_id=job_id,
                    status="processing",
                    progress=45,
                    current_step="Aligning signals, transcript, and evaluator scores",
                )

                # Run Alignment Engine
                aligned_dataset = self.aligner.align_session(session_id)

                # 3. Update status -> processing (80%)
                self._update_job(
                    session_id=session_id,
                    job_id=job_id,
                    status="processing",
                    progress=85,
                    current_step="Compiling aligned dataset artifact",
                )

                # 4. Save aligned dataset key in DB
                db: Session = SessionLocal()
                try:
                    sess = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
                    if sess:
                        sess.aligned_data_key = aligned_dataset.get("file_key")
                        db.commit()
                finally:
                    db.close()

                # Score Fusion, Comparisons, Weak-Area Ranking & U Memory Update (Phase 5.3)
                try:
                    from app.services.score_fusion_service import process_and_persist_session_result
                    fused_result = process_and_persist_session_result(session_id, aligned_dataset=aligned_dataset)
                    aligned_dataset["fused_result"] = fused_result
                except Exception as fuse_err:
                    logger.warning("Error executing score fusion & persistence for session #%d: %s", session_id, fuse_err)

                # 5. Mark Completed or Partial (100%)
                final_status = "partial" if aligned_dataset.get("is_partial") else "completed"
                result = self._update_job(
                    session_id=session_id,
                    job_id=job_id,
                    status=final_status,
                    progress=100,
                    current_step="Analysis complete",
                    is_partial=aligned_dataset.get("is_partial", False),
                    missing_sections=aligned_dataset.get("missing_sections", []),
                    aligned_data=aligned_dataset,
                    completed=True,
                )
                logger.info(
                    "Analysis pipeline finished for session #%d: status=%s, partial=%s, missing=%s",
                    session_id,
                    final_status,
                    aligned_dataset.get("is_partial"),
                    aligned_dataset.get("missing_sections"),
                )
                return result

            except Exception as e:
                retries += 1
                logger.warning(
                    "Analysis job error for session #%d (attempt %d/%d): %s",
                    session_id,
                    retries,
                    max_retries,
                    e,
                )
                if retries <= max_retries:
                    # Exponential backoff. This method always runs on a worker thread
                    # (executor / background thread / explicit sync call), never on the
                    # event loop; refuse to sleep if someone calls it from a loop thread.
                    if _on_event_loop_thread():
                        logger.error("run_analysis_pipeline_sync called on the event loop; skipping backoff sleep")
                    else:
                        time.sleep(backoff_delay)
                    backoff_delay *= 2.0
                else:
                    # Retries exhausted -> mark failed
                    logger.exception("Analysis job failed permanently for session #%d", session_id)
                    return self._update_job(
                        session_id=session_id,
                        job_id=job_id,
                        status="failed",
                        progress=0,
                        current_step="Failed",
                        error_message="Analysis failed. Please retry later.",
                        completed=True,
                    )

    def enqueue_analysis_job(
        self,
        session_id: int,
        sync: bool = False,
        simulate_failure_step: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Enqueues an analysis job with IDEMPOTENCY:
        If a job already exists and is active or completed, returns it directly without duplicating.
        """
        existing = self.get_job_status(session_id)
        if existing and existing.get("status") in ("processing", "completed", "partial"):
            logger.info("Idempotent check: session #%d analysis job already active/complete.", session_id)
            return existing

        job_id = f"job_analysis_{session_id}_{int(time.time())}"

        # Initialize job record in DB
        db: Session = SessionLocal()
        try:
            db_job = db.query(SessionAnalysisJob).filter(SessionAnalysisJob.session_id == session_id).first()
            if not db_job:
                db_job = SessionAnalysisJob(
                    session_id=session_id,
                    job_id=job_id,
                    status="pending",
                    progress=5,
                    current_step="Queued in analysis pipeline",
                    started_at=datetime.now(timezone.utc),
                )
                db.add(db_job)
            else:
                db_job.job_id = job_id
                db_job.status = "pending"
                db_job.progress = 5
                db_job.current_step = "Queued in analysis pipeline"
                db_job.error_message = None
                db_job.started_at = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()

        self._memory_jobs[session_id] = {
            "session_id": session_id,
            "job_id": job_id,
            "status": "pending",
            "progress": 5,
            "current_step": "Queued in analysis pipeline",
            "is_partial": False,
            "missing_sections": [],
            "error_message": None,
        }

        # If sync requested (e.g. testing or immediate return)
        if sync:
            return self.run_analysis_pipeline_sync(
                session_id=session_id,
                job_id=job_id,
                simulate_failure_step=simulate_failure_step,
            )

        # Asynchronous background execution
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(
                None,
                self.run_analysis_pipeline_sync,
                session_id,
                job_id,
                3,
                simulate_failure_step,
            )
        except RuntimeError:
            # No running loop (called from a sync endpoint or a worker thread): run in a
            # background thread instead of blocking the caller for the whole pipeline.
            threading.Thread(
                target=self.run_analysis_pipeline_sync,
                args=(session_id, job_id, 3, simulate_failure_step),
                name=f"analysis-{session_id}",
                daemon=True,
            ).start()

        return self.get_job_status(session_id)

    def _update_job(
        self,
        session_id: int,
        job_id: str,
        status: str,
        progress: int,
        current_step: str,
        is_partial: bool = False,
        missing_sections: Optional[List[str]] = None,
        aligned_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        completed: bool = False,
    ) -> Dict[str, Any]:
        """Updates job state in memory and database."""
        missing = missing_sections or []
        state_dict = {
            "session_id": session_id,
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "current_step": current_step,
            "is_partial": is_partial,
            "missing_sections": missing,
            "error_message": error_message,
        }
        self._memory_jobs[session_id] = state_dict

        db: Session = SessionLocal()
        try:
            db_job = db.query(SessionAnalysisJob).filter(SessionAnalysisJob.session_id == session_id).first()
            if db_job:
                db_job.status = status
                db_job.progress = progress
                db_job.current_step = current_step
                db_job.is_partial = is_partial
                db_job.missing_sections = missing
                if error_message:
                    db_job.error_message = error_message
                if aligned_data:
                    db_job.aligned_data = aligned_data
                if completed:
                    db_job.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception as e:
            logger.warning("Failed to update SessionAnalysisJob DB: %s", e)
            db.rollback()
        finally:
            db.close()

        return state_dict


default_analysis_manager = AnalysisJobManager()
