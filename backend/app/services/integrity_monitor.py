"""
Integrity Monitor Service (Phase 4.6).
Tracks and validates candidate interview integrity in real time:
- Frontend events: Tab switch / window blur (Page Visibility API), fullscreen exit, clipboard copy/paste.
- Video worker events: Second face detected in frame, face missing for > N seconds.
- First-time gentle on-screen warning via WebSocket.
- Persistent IntegrityEvent records in database and session data.
- Configurable threshold flagging without auto-terminating the interview.
"""

import time
import logging
from typing import Dict, Any, List, Optional, Callable, Awaitable
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import IntegrityEvent, InterviewSession

logger = logging.getLogger("intervai.integrity_monitor")

# Default severity mappings
DEFAULT_SEVERITIES = {
    "tab_switch": "MEDIUM",
    "window_blur": "LOW",
    "fullscreen_exit": "MEDIUM",
    "clipboard_copy": "HIGH",
    "clipboard_paste": "HIGH",
    "multiple_faces": "HIGH",
    "face_missing": "MEDIUM",
    "hesitation": "LOW",
}

DEFAULT_WARNING_MESSAGES = {
    "tab_switch": "Gentle reminder: Please keep your interview browser tab active during the session.",
    "window_blur": "Gentle reminder: Please keep focus on the interview window.",
    "fullscreen_exit": "Gentle reminder: Fullscreen mode is recommended for your interview.",
    "clipboard_copy": "Gentle reminder: External copying is monitored during assessment rounds.",
    "clipboard_paste": "Gentle reminder: External pasting is monitored during assessment rounds.",
    "multiple_faces": "Gentle reminder: Please ensure only you are present in the camera view.",
    "face_missing": "Gentle reminder: Please remain visible in front of the camera.",
}


class IntegrityMonitor:
    """
    Session-scoped integrity monitor tracking real-time client & server telemetry.
    """

    def __init__(
        self,
        session_id: int,
        face_missing_threshold_seconds: float = 3.0,
        flag_threshold_count: int = 3,
        emit_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.session_id = session_id
        self.face_missing_threshold_seconds = face_missing_threshold_seconds
        self.flag_threshold_count = flag_threshold_count
        self.emit_callback = emit_callback

        self._warning_shown = False
        self._warning_count = 0
        self._missing_face_start: Optional[float] = None
        self._missing_face_question_id: Optional[int] = None
        self._missing_face_event_logged = False
        self._second_face_cooldown: float = 0.0

        # In-memory fast cache of events for this session
        self._events_cache: List[Dict[str, Any]] = []

    def set_emit_callback(self, callback: Callable[[str, Dict[str, Any]], Awaitable[None]]) -> None:
        """Sets or updates the WebSocket emit callback."""
        self.emit_callback = callback

    async def record_event(
        self,
        event_type: str,
        question_id: Optional[int] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        severity: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Records an integrity event, emits first-time warning if applicable, and writes to database.
        """
        now = time.time()
        st = float(start_time if start_time is not None else now)
        et = float(end_time if end_time is not None else st)
        dur = max(0.0, round(et - st, 2))

        sev = severity or DEFAULT_SEVERITIES.get(event_type, "MEDIUM")
        event_details = details or {}

        event_dict = {
            "session_id": self.session_id,
            "question_id": question_id,
            "type": event_type,
            "event_type": event_type,
            "start_time": st,
            "end_time": et,
            "duration_seconds": dur,
            "severity": sev,
            "details": event_details,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Write to database
        db: Session = SessionLocal()
        try:
            db_rec = IntegrityEvent(
                session_id=self.session_id,
                question_id=question_id,
                type=event_type,
                start_time=st,
                end_time=et,
                duration_seconds=dur,
                severity=sev,
                details=event_details,
            )
            db.add(db_rec)
            db.commit()
            db.refresh(db_rec)
            event_dict["id"] = db_rec.id
        except Exception as e:
            db.rollback()
            logger.warning("Failed to persist IntegrityEvent to DB for session #%d (%s)", self.session_id, e)
            event_dict["id"] = len(self._events_cache) + 1
        finally:
            db.close()

        self._events_cache.append(event_dict)
        logger.info(
            "Integrity event recorded [session #%d, q #%s, type=%s, severity=%s]",
            self.session_id,
            question_id,
            event_type,
            sev,
        )

        # 2. Show a gentle on-screen warning to user THE FIRST TIME
        if not self._warning_shown:
            self._warning_shown = True
            self._warning_count += 1
            if self.emit_callback:
                msg = DEFAULT_WARNING_MESSAGES.get(
                    event_type,
                    "Gentle reminder: Please remain facing the camera in full view and keep this window active.",
                )
                try:
                    await self.emit_callback("integrity_warning", {
                        "event_type": event_type,
                        "message": msg,
                        "severity": sev,
                        "question_id": question_id,
                        "warning_count": self._warning_count,
                        "timestamp": st,
                    })
                    logger.info("First-time gentle integrity warning emitted for session #%d", self.session_id)
                except Exception as ex:
                    logger.warning("Failed to emit gentle integrity warning: %s", ex)

        return event_dict

    async def on_video_metrics(
        self,
        question_id: Optional[int],
        timestamp: float,
        metrics: Dict[str, float],
    ) -> None:
        """
        Processes frame metrics from video worker:
        - Detects second face in frame.
        - Detects face missing for more than N seconds.
        """
        # 1. Face missing detection
        face_present = metrics.get("face_present", 1.0)
        if face_present <= 0.0:
            if self._missing_face_start is None:
                self._missing_face_start = timestamp
                self._missing_face_question_id = question_id
                self._missing_face_event_logged = False
            else:
                elapsed_missing = timestamp - self._missing_face_start
                if elapsed_missing >= self.face_missing_threshold_seconds and not self._missing_face_event_logged:
                    self._missing_face_event_logged = True
                    await self.record_event(
                        event_type="face_missing",
                        question_id=self._missing_face_question_id or question_id,
                        start_time=self._missing_face_start,
                        end_time=timestamp,
                        severity="MEDIUM",
                        details={
                            "threshold_seconds": self.face_missing_threshold_seconds,
                            "duration_seconds": round(elapsed_missing, 2),
                            "reason": f"Face missing for > {self.face_missing_threshold_seconds}s",
                        },
                    )
        else:
            # Face returned
            if self._missing_face_start is not None:
                elapsed_missing = timestamp - self._missing_face_start
                if elapsed_missing >= self.face_missing_threshold_seconds and not self._missing_face_event_logged:
                    await self.record_event(
                        event_type="face_missing",
                        question_id=self._missing_face_question_id or question_id,
                        start_time=self._missing_face_start,
                        end_time=timestamp,
                        severity="MEDIUM",
                        details={
                            "threshold_seconds": self.face_missing_threshold_seconds,
                            "duration_seconds": round(elapsed_missing, 2),
                        },
                    )
                self._missing_face_start = None
                self._missing_face_question_id = None
                self._missing_face_event_logged = False

        # 2. Second face detection
        second_face = metrics.get("second_face_detected", 0.0) >= 1.0 or metrics.get("face_count", 1.0) >= 2.0
        if second_face:
            if timestamp - self._second_face_cooldown >= 3.0:
                self._second_face_cooldown = timestamp
                await self.record_event(
                    event_type="multiple_faces",
                    question_id=question_id,
                    start_time=timestamp,
                    end_time=timestamp,
                    severity="HIGH",
                    details={
                        "face_count": metrics.get("face_count", 2.0),
                        "message": "Multiple faces detected in camera frame.",
                    },
                )

    def get_integrity_summary(self) -> Dict[str, Any]:
        """
        Returns full list of events, aggregated breakdown, and threshold flag assessment.
        Does not auto-terminate the session.
        """
        events = list(self._events_cache)
        if not events:
            # Fallback query from DB
            db: Session = SessionLocal()
            try:
                db_rows = (
                    db.query(IntegrityEvent)
                    .filter(IntegrityEvent.session_id == self.session_id)
                    .order_by(IntegrityEvent.start_time.asc())
                    .all()
                )
                events = [
                    {
                        "id": r.id,
                        "session_id": r.session_id,
                        "question_id": r.question_id,
                        "type": r.type,
                        "event_type": r.type,
                        "start_time": r.start_time,
                        "end_time": r.end_time,
                        "duration_seconds": r.duration_seconds,
                        "severity": r.severity,
                        "details": r.details or {},
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in db_rows
                ]
            finally:
                db.close()

        total = len(events)
        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}

        for ev in events:
            t = ev.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
            sev = ev.get("severity", "MEDIUM")
            by_severity[sev] = by_severity.get(sev, 0) + 1

        is_flagged = total >= self.flag_threshold_count
        flag_reasons = []
        if is_flagged:
            flag_reasons.append(
                f"Integrity event threshold exceeded: {total} events recorded (threshold: {self.flag_threshold_count})."
            )
        if by_type.get("multiple_faces", 0) > 0:
            flag_reasons.append("Multiple persons detected in camera view.")
        if by_type.get("clipboard_paste", 0) > 0:
            flag_reasons.append("External clipboard paste activity detected.")
        if by_type.get("tab_switch", 0) >= 2:
            flag_reasons.append(f"Multiple tab switch occurrences detected ({by_type['tab_switch']} times).")

        return {
            "session_id": self.session_id,
            "total_events": total,
            "events": events,
            "by_type": by_type,
            "by_severity": by_severity,
            "warning_count": self._warning_count,
            "flag_threshold_count": self.flag_threshold_count,
            "is_flagged": is_flagged,
            "flag_reasons": flag_reasons,
        }
