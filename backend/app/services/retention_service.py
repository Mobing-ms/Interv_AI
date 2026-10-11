"""
Retention Service.
Automates scheduled cleanup of expired interview recordings and guest sessions
in accordance with data retention guarantees (30 days for registered users, 24 hours for guests).
"""

import os
import shutil
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.models import InterviewSession
from app.services.answer_capture_service import default_storage_manager
from app.services.guest_service import cleanup_expired_guest_sessions

logger = logging.getLogger("intervai.retention")


def cleanup_all_expired_recordings(
    db: Session,
    user_retention_days: Optional[int] = None,
    guest_retention_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Executes automated data retention lifecycle:
    1. Purges guest sessions, recordings, and transcripts older than 24h.
    2. Purges recording media files (audio/video blobs) for registered user sessions
       older than the configured retention period (default 30 days).
    Preserves audit trails, structured reports, and results.
    """
    u_days = user_retention_days or settings.RECORDING_RETENTION_DAYS
    g_hours = guest_retention_hours or settings.GUEST_RETENTION_HOURS

    # 1. Clean expired guest sessions
    guest_deleted = cleanup_expired_guest_sessions(db, max_age_hours=g_hours)

    # 2. Clean expired user session recordings on disk
    user_cutoff = datetime.now(timezone.utc) - timedelta(days=u_days)
    expired_user_sessions = (
        db.query(InterviewSession)
        .filter(
            InterviewSession.is_guest == False,
            InterviewSession.created_at <= user_cutoff,
        )
        .all()
    )

    user_recordings_pruned = 0
    bytes_freed = 0

    for sess in expired_user_sessions:
        sess_dir = os.path.join(default_storage_manager.base_dir, str(sess.id))
        if os.path.exists(sess_dir):
            try:
                # Calculate size freed
                for root, _, files in os.walk(sess_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            bytes_freed += os.path.getsize(fp)
                        except OSError:
                            pass
                shutil.rmtree(sess_dir, ignore_errors=True)
                user_recordings_pruned += 1
                logger.info(
                    "Pruned expired recording directory for session_id=%d (retention=%d days)",
                    sess.id,
                    u_days,
                )
            except Exception as e:
                logger.warning(
                    "Error pruning recording directory for session_id=%d: %s",
                    sess.id,
                    e,
                )

        # Prune cloud object storage assets
        try:
            from app.services.storage_service import default_storage_provider
            default_storage_provider.delete_prefix(f"sessions/{sess.id}")
        except Exception as e:
            logger.warning(f"Error deleting cloud objects for session #{sess.id}: {e}")

        # Clear file keys in database to reflect that media has expired
        sess.audio_file_key = None
        sess.video_file_key = None

    db.commit()

    return {
        "guest_sessions_purged": guest_deleted,
        "user_recording_directories_pruned": user_recordings_pruned,
        "bytes_freed": bytes_freed,
        "user_retention_days": u_days,
        "guest_retention_hours": g_hours,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
