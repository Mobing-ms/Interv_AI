import time
import secrets
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Request,
    Response,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.config import settings
from app.services.tts_service import default_tts_service
from app.models import (
    User,
    InterviewConfig,
    UserConsent,
    InterviewSession,
    SessionCalibration,
)
from app.auth import get_current_user
from app.schemas import (
    ConsentCreate,
    ConsentOut,
    SessionCreate,
    SessionOut,
    SessionCalibrationCreate,
    SessionCalibrationOut,
    NetworkPingOut,
    NetworkSpeedTestOut,
)

router = APIRouter(prefix="/session", tags=["session"])


# =============================================================================
# 1. CONSENT ENDPOINTS
# =============================================================================

@router.post("/consent", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
def record_consent(
    body: ConsentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stores a candidate Consent record with version, configurable retention days,
    and deletion permissions.
    """
    if not body.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent must be accepted to proceed with the interview.",
        )

    consent = UserConsent(
        user_id=current_user.id,
        version=body.version,
        retention_days=settings.RECORDING_RETENTION_DAYS,
        accepted=True,
        can_delete=True,
        accepted_at=datetime.now(timezone.utc),
    )
    db.add(consent)
    db.commit()
    db.refresh(consent)
    return consent


@router.get("/consent", response_model=ConsentOut)
def get_latest_consent(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves the user's latest recorded consent.
    """
    consent = (
        db.query(UserConsent)
        .filter(UserConsent.user_id == current_user.id, UserConsent.accepted == True)
        .order_by(UserConsent.accepted_at.desc())
        .first()
    )
    if not consent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recorded consent found for this user.",
        )
    return consent


# =============================================================================
# 2. NETWORK DIAGNOSTICS (Latency Ping & Speed Test)
# =============================================================================

@router.get("/ping", response_model=NetworkPingOut)
def ping_network(client_ts: Optional[float] = Query(None)):
    """
    Lightweight ping endpoint for measuring round-trip network latency.
    """
    return NetworkPingOut(
        server_time=datetime.now(timezone.utc),
        client_timestamp=client_ts,
        status="ok",
    )


@router.post("/speed-test", response_model=NetworkSpeedTestOut)
async def upload_speed_test(request: Request):
    """
    Upload speed test endpoint. Measures payload bytes received and transfer rate in Mbps.
    """
    start_time = time.perf_counter()
    body_bytes = await request.body()
    duration_sec = max(0.001, time.perf_counter() - start_time)
    duration_ms = duration_sec * 1000.0

    bytes_count = len(body_bytes)
    # Calculate megabits per second
    upload_mbps = round((bytes_count * 8 / 1_000_000) / duration_sec, 2)

    return NetworkSpeedTestOut(
        bytes_received=bytes_count,
        duration_ms=round(duration_ms, 2),
        upload_mbps=upload_mbps,
        status="ok",
    )


# =============================================================================
# 2.5 TEXT-TO-SPEECH (TTS) ENDPOINTS
# =============================================================================

@router.get("/tts/audio/{cache_key}")
def get_tts_audio(cache_key: str):
    """
    Streams cached synthesized audio bytes for the given cache key.
    """
    res = default_tts_service.get_cached_audio(cache_key)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audio cache key '{cache_key}' not found.",
        )
    audio_bytes, mime = res
    return Response(content=audio_bytes, media_type=mime)


@router.post("/tts/synthesize")
def synthesize_tts(payload: Dict[str, Any]):
    """
    Synthesizes speech audio for a text phrase, returns audio URL and cache status.
    """
    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text parameter is required for TTS synthesis.",
        )
    language = payload.get("language", "English")
    voice_style = payload.get("voice_style", "neutral")
    return default_tts_service.synthesize_speech(text, language=language, voice_style=voice_style)


# =============================================================================
# 3. INTERVIEW SESSION LIFECYCLE
# =============================================================================

def _build_ws_url(request: Request, session_id: int, token: str) -> str:
    """
    Constructs the WebSocket URL based on request scheme and host.
    """
    host = request.headers.get("host", "127.0.0.1:8000")
    scheme = "wss" if request.url.scheme == "https" else "ws"
    return f"{scheme}://{host}/session/{session_id}/stream?token={token}"


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    request: Request,
    body: Optional[SessionCreate] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Creates an active InterviewSession (id, user_id, interview_id, status, started_at).
    Enforces that user consent must be on file.
    Returns session metadata plus WebSocket URL and session token.
    """
    # 1. Enforce consent
    latest_consent = (
        db.query(UserConsent)
        .filter(UserConsent.user_id == current_user.id, UserConsent.accepted == True)
        .first()
    )
    if not latest_consent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Consent is required before starting an interview session. Please accept recording & data retention terms.",
        )

    # 2. Resolve InterviewConfig
    interview_cfg = None
    if body and body.interview_id:
        interview_cfg = (
            db.query(InterviewConfig)
            .filter(InterviewConfig.id == body.interview_id, InterviewConfig.user_id == current_user.id)
            .first()
        )
        if not interview_cfg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"InterviewConfig #{body.interview_id} not found.",
            )

    if not interview_cfg:
        # Fall back to candidate's latest config
        interview_cfg = (
            db.query(InterviewConfig)
            .filter(InterviewConfig.user_id == current_user.id)
            .order_by(InterviewConfig.created_at.desc())
            .first()
        )

    if not interview_cfg:
        # Auto-create baseline configuration if none existed
        interview_cfg = InterviewConfig(
            user_id=current_user.id,
            round_type="Technical",
            difficulty="Medium",
            duration_minutes=30,
            language="English",
            mode="normal",
            focus_topics=[],
        )
        db.add(interview_cfg)
        db.commit()
        db.refresh(interview_cfg)

    # 3. Create Session with secure token
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)

    new_session = InterviewSession(
        user_id=current_user.id,
        interview_id=interview_cfg.id,
        status="created",
        session_token=token,
        started_at=now,
        created_at=now,
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    ws_url = _build_ws_url(request, new_session.id, token)

    return SessionOut(
        id=new_session.id,
        user_id=new_session.user_id,
        interview_id=new_session.interview_id,
        status=new_session.status,
        session_token=new_session.session_token,
        started_at=new_session.started_at,
        ended_at=new_session.ended_at,
        ws_url=ws_url,
        calibration=None,
    )


@router.get("/{id}", response_model=SessionOut)
def get_session(
    id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves details for a specific interview session.
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

    ws_url = _build_ws_url(request, session.id, session.session_token)
    cal_out = (
        SessionCalibrationOut.model_validate(session.calibration)
        if session.calibration
        else None
    )

    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        interview_id=session.interview_id,
        status=session.status,
        session_token=session.session_token,
        started_at=session.started_at,
        ended_at=session.ended_at,
        ws_url=ws_url,
        calibration=cal_out,
    )


# =============================================================================
# 4. CALIBRATION ENDPOINTS
# =============================================================================

@router.post("/{id}/calibration", response_model=SessionCalibrationOut, status_code=status.HTTP_201_CREATED)
def record_session_calibration(
    id: int,
    body: SessionCalibrationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stores 30-second baseline metrics for face (neutral expression, gaze center, head pose),
    voice level (average volume, pitch range), and background noise floor.
    """
    session = (
        db.query(InterviewSession)
        .filter(InterviewSession.id == id, InterviewSession.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session #{id} not found.",
        )

    # Defaults for face baseline if partial or empty
    face_data = body.face_baseline or {
        "neutral_score": 0.94,
        "gaze_center": {"x": 0.5, "y": 0.5},
        "head_pose": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
    }

    # Defaults for voice baseline if partial or empty
    voice_data = body.voice_baseline or {
        "average_volume_db": -24.0,
        "pitch_range_hz": [110.0, 220.0],
        "speaking_rate_wpm": 130.0,
    }

    noise_db = (
        body.background_noise_level_db
        if body.background_noise_level_db is not None
        else -50.0
    )

    now = datetime.now(timezone.utc)

    # Upsert calibration
    cal = (
        db.query(SessionCalibration)
        .filter(SessionCalibration.session_id == id)
        .first()
    )
    if cal:
        cal.face_baseline = face_data
        cal.voice_baseline = voice_data
        cal.background_noise_level_db = noise_db
        cal.calibration_text = body.calibration_text
        cal.calibrated_at = now
    else:
        cal = SessionCalibration(
            session_id=id,
            user_id=current_user.id,
            face_baseline=face_data,
            voice_baseline=voice_data,
            background_noise_level_db=noise_db,
            calibration_text=body.calibration_text,
            calibrated_at=now,
        )
        db.add(cal)

    # Mark session as active/calibrated
    session.status = "calibrated"
    db.commit()
    db.refresh(cal)
    return cal


@router.get("/{id}/calibration", response_model=SessionCalibrationOut)
def get_session_calibration(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves baseline calibration metrics for a session.
    """
    cal = (
        db.query(SessionCalibration)
        .filter(SessionCalibration.session_id == id, SessionCalibration.user_id == current_user.id)
        .first()
    )
    if not cal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Calibration data for session #{id} not found.",
        )
    return cal


# =============================================================================
from app.services.session_orchestrator import SessionOrchestrator
from app.services.session_state import default_state_store, SessionState


# =============================================================================
# 5. WEBSOCKET REAL-TIME STREAMING & ORCHESTRATOR ENDPOINTS
# =============================================================================

@router.get("/{id}/state")
def get_session_state(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves real-time session state from Redis (current state, question,
    elapsed time, follow-up counts, and Q/A score context).
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

    state = default_state_store.load_state(id)
    if not state:
        return {
            "session_id": id,
            "status": session.status,
            "state": "NOT_STARTED",
            "elapsed_time": 0.0,
            "session_context": [],
        }

    return state.model_dump()


@router.websocket("/{id}/live")
@router.websocket("/{id}/orchestrate")
async def session_live_orchestrator_websocket(
    websocket: WebSocket,
    id: int,
    token: Optional[str] = Query(None),
):
    """
    Core Phase 4 Interview Session Orchestrator WebSocket endpoint.
    Drives state machine (GREETING -> WARMUP -> ASKING -> LISTENING ->
    EVALUATING -> ROUTING -> CLOSING -> ENDED) with Redis persistence and reconnection recovery.
    """
    db = SessionLocal()
    session = None
    try:
        if not token:
            await websocket.close(code=1008, reason="Missing session token")
            return

        session = (
            db.query(InterviewSession)
            .filter(InterviewSession.id == id, InterviewSession.session_token == token)
            .first()
        )
        if not session:
            # Also accept candidate's JWT access token for resilience
            try:
                from app.auth import decode_token
                payload = decode_token(token)
                sub = payload.get("sub")
                if sub:
                    session = (
                        db.query(InterviewSession)
                        .filter(InterviewSession.id == id, InterviewSession.user_id == int(sub))
                        .first()
                    )
            except Exception:
                pass

        if not session:
            await websocket.close(code=1008, reason="Invalid session token")
            return


        await websocket.accept()

        session.status = "active"
        db.commit()
        user_id = session.user_id
        db.close()
        db = None

        orchestrator = SessionOrchestrator(session_id=id, user_id=user_id)
        await orchestrator.start(websocket)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "detail": str(e)})
        except Exception:
            pass
    finally:
        if db:
            db.close()


@router.websocket("/{id}/stream")
async def session_stream_websocket(
    websocket: WebSocket,
    id: int,
    token: Optional[str] = Query(None),
    orchestrate: bool = Query(False),
):
    """
    WebSocket endpoint for real-time media chunk streaming (MediaRecorder chunks)
    and session control messages.
    If orchestrate=true, delegates to the full Phase 4 SessionOrchestrator state machine.
    Authenticates via ?token= query parameter.
    """
    db = SessionLocal()
    session = None
    try:
        if not token:
            await websocket.close(code=1008, reason="Missing session token")
            return

        session = (
            db.query(InterviewSession)
            .filter(InterviewSession.id == id, InterviewSession.session_token == token)
            .first()
        )
        if not session:
            await websocket.close(code=1008, reason="Invalid session token")
            return

        await websocket.accept()

        # Update session status to active on connection
        session.status = "active"
        db.commit()

        # If full orchestrator requested on stream endpoint, delegate to SessionOrchestrator
        if orchestrate:
            user_id = session.user_id
            db.close()
            db = None
            orchestrator = SessionOrchestrator(session_id=id, user_id=user_id)
            await orchestrator.start(websocket)
            return

        # Send greeting / connection established frame for Phase 3 stream compatibility
        await websocket.send_json({
            "type": "connected",
            "session_id": id,
            "status": "active",
            "message": "IntervAI live stream connection established.",
            "timestamp": time.time(),
        })

        chunk_counter = 0

        while True:
            # Receive text or binary message
            message = await websocket.receive()

            if "text" in message and message["text"]:
                try:
                    import json
                    data = json.loads(message["text"])
                    msg_type = data.get("type", "unknown")

                    if msg_type == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": time.time(),
                        })

                    elif msg_type == "media_chunk":
                        chunk_counter += 1
                        chunk_id = data.get("chunk_id", chunk_counter)
                        payload_size = len(data.get("data", ""))
                        await websocket.send_json({
                            "type": "chunk_ack",
                            "chunk_id": chunk_id,
                            "size": payload_size,
                            "received_at": time.time(),
                        })

                    elif msg_type == "calibration_event":
                        await websocket.send_json({
                            "type": "calibration_ack",
                            "timestamp": time.time(),
                        })

                    elif msg_type in ("start_interview", "heartbeat", "answer_started"):
                        # Dynamic transition to orchestrator if client issues orchestrator command
                        orchestrator = SessionOrchestrator(session_id=id, user_id=session.user_id)
                        await orchestrator.start(websocket)
                        return

                    else:
                        await websocket.send_json({
                            "type": "ack",
                            "original_type": msg_type,
                            "timestamp": time.time(),
                        })

                except Exception:
                    await websocket.send_json({
                        "type": "error",
                        "detail": "Failed to parse JSON text frame",
                    })

            elif "bytes" in message and message["bytes"]:
                chunk_counter += 1
                raw_bytes = message["bytes"]
                await websocket.send_json({
                    "type": "binary_chunk_ack",
                    "chunk_id": chunk_counter,
                    "size": len(raw_bytes),
                    "received_at": time.time(),
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if db:
            db.close()


@router.get("/{id}/question/{question_id}/artifacts")
def get_question_artifacts(
    id: int,
    question_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns stored question artifacts: audio chunk count, video frame count,
    and transcript with word-level timestamps.
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
    from app.services.answer_capture_service import default_storage_manager
    return default_storage_manager.get_question_artifacts(session_id=id, question_id=question_id)


@router.get("/{id}/question/{question_id}/signals")
def get_question_signals(
    id: int,
    question_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns parallel video & audio signal metrics for a question,
    including comparison against the candidate's calibration baseline.
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

    # 1. Fetch calibration record
    cal_rec = db.query(SessionCalibration).filter(SessionCalibration.session_id == id).first()
    calibration_baseline = {
        "face_baseline": cal_rec.face_baseline if cal_rec else {},
        "voice_baseline": cal_rec.voice_baseline if cal_rec else {},
        "background_noise_level_db": cal_rec.background_noise_level_db if cal_rec else -50.0,
    }

    # 2. Retrieve signals from store (in-memory cache or DB)
    from app.services.signal_workers import default_signal_store
    raw_signals = default_signal_store.get_signals_for_question(session_id=id, question_id=question_id)

    # 3. Aggregate metrics by category
    by_metric: Dict[str, List[float]] = {}
    for s in raw_signals:
        m = s["metric"]
        if m not in by_metric:
            by_metric[m] = []
        by_metric[m].append(s["value"])

    def _mean(metric_name: str, default: float = 0.0) -> float:
        vals = by_metric.get(metric_name, [])
        return round(float(sum(vals) / len(vals)), 3) if vals else default

    def _max(metric_name: str, default: float = 0.0) -> float:
        vals = by_metric.get(metric_name, [])
        return round(float(max(vals)), 3) if vals else default

    # Face summary
    face_summary = {
        "face_present_ratio": _mean("face_present", 1.0),
        "avg_eye_contact": _mean("eye_contact", 0.90),
        "avg_head_yaw": _mean("head_yaw", 0.0),
        "avg_head_pitch": _mean("head_pitch", 0.0),
        "avg_head_roll": _mean("head_roll", 0.0),
        "avg_emotion_valence": _mean("emotion_valence", 0.1),
        "avg_posture_alignment": _mean("posture_alignment", 0.95),
        "avg_movement_level": _mean("movement_level", 0.05),
    }

    # Speech summary
    speech_summary = {
        "avg_speech_pace_wpm": _mean("speech_pace_wpm", 135.0),
        "total_filler_words": int(_max("filler_count", 0)),
        "avg_filler_rate": _mean("filler_rate", 0.0),
        "avg_pitch_hz": _mean("pitch_hz", 150.0),
        "pitch_variance": _mean("pitch_variance", 25.0),
        "avg_volume_rms": _mean("volume_rms", 400.0),
        "volume_variability": _mean("volume_variability", 20.0),
        "total_pause_count": int(_max("pause_count", 0)),
        "avg_pause_length_sec": _mean("avg_pause_length", 0.0),
        "avg_clarity_proxy": _mean("clarity_proxy", 0.88),
    }

    # Comparison vs Calibration Baseline
    baseline_face = calibration_baseline.get("face_baseline", {})
    comparison = {
        "head_yaw_delta_from_baseline": round(face_summary["avg_head_yaw"] - baseline_face.get("head_pose", {}).get("yaw", 0.0), 2),
        "head_pitch_delta_from_baseline": round(face_summary["avg_head_pitch"] - baseline_face.get("head_pose", {}).get("pitch", 0.0), 2),
        "voice_volume_above_noise_db": round(speech_summary["avg_volume_rms"] - max(1.0, calibration_baseline.get("background_noise_level_db", -50.0)), 2),
        "eye_contact_relative_to_baseline": face_summary["avg_eye_contact"],
    }

    return {
        "session_id": id,
        "question_id": question_id,
        "has_calibration": cal_rec is not None,
        "calibration_baseline": calibration_baseline,
        "face_metrics": face_summary,
        "speech_metrics": speech_summary,
        "calibration_comparison": comparison,
        "time_series_count": len(raw_signals),
        "time_series": raw_signals,
    }


@router.get("/{id}/signals")
def get_session_signals(
    id: int,
    question_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Convenience endpoint returning signals for question or active question."""
    q_id = question_id if question_id is not None else 1
    return get_question_signals(id=id, question_id=q_id, current_user=current_user, db=db)


@router.get("/{id}/integrity-events")
def get_session_integrity_events(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns all logged integrity events for the interview session:
    - Tab switches / window blur (Page Visibility API)
    - Fullscreen exit
    - Clipboard copy / paste attempts
    - Multiple faces in camera frame
    - Face missing for > N seconds
    - Threshold evaluation and report flagging (without auto-terminating the interview).
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

    from app.services.integrity_monitor import IntegrityMonitor
    monitor = IntegrityMonitor(session_id=id)
    summary = monitor.get_integrity_summary()
    return summary


@router.get("/{id}/integrity")
def get_session_integrity_convenience(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Convenience alias for /integrity-events."""
    return get_session_integrity_events(id=id, current_user=current_user, db=db)



