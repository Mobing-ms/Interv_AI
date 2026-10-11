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
from app.auth import get_current_user, get_current_user_or_guest, AuthContext
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
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
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

    user_id = auth_ctx.user.id if auth_ctx.user else None
    guest_id = auth_ctx.guest_id if auth_ctx.is_guest else None

    consent = UserConsent(
        user_id=user_id,
        is_guest=auth_ctx.is_guest,
        guest_id=guest_id,
        version=body.version,
        retention_days=1 if auth_ctx.is_guest else settings.RECORDING_RETENTION_DAYS,
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
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Retrieves the user's or guest's latest recorded consent.
    """
    if auth_ctx.user:
        consent = (
            db.query(UserConsent)
            .filter(UserConsent.user_id == auth_ctx.user.id, UserConsent.accepted == True)
            .order_by(UserConsent.accepted_at.desc())
            .first()
        )
    elif auth_ctx.is_guest and auth_ctx.guest_id:
        consent = (
            db.query(UserConsent)
            .filter(UserConsent.guest_id == auth_ctx.guest_id, UserConsent.accepted == True)
            .order_by(UserConsent.accepted_at.desc())
            .first()
        )
    else:
        consent = None

    if not consent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recorded consent found.",
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


@router.get("/dashboard-summary")
def get_dashboard_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns aggregated dashboard metrics (Phase 6.3):
    - Past session list with round types, dates, scores, and classifications
    - Latest session with overall score and subscores
    - Practice trend scores for historical charts
    - Current identified weak areas and topic masteries from UserMemory
    - Session count and average composite score
    - Quick action recommendations (Retake, Next round type, Practice weak topics)
    - Confirmed profile status (skip Phase 1 flag)
    """
    from app.models import Profile, UserMemory, SessionResult
    from app.services.interview_context import ensure_user_memory_updated

    # Ensure memory updated from latest session
    ensure_user_memory_updated(current_user.id, db)

    # Fetch user sessions
    user_sessions = (
        db.query(InterviewSession)
        .filter(InterviewSession.user_id == current_user.id)
        .order_by(InterviewSession.created_at.desc())
        .all()
    )

    formatted_sessions = []
    trend_scores = []
    completed_scores = []

    for sess in user_sessions:
        cfg = sess.interview_config
        res = sess.result

        round_type = cfg.round_type if cfg else "Technical"
        difficulty = cfg.difficulty if cfg else "Medium"
        created_str = sess.created_at.strftime("%b %d, %Y") if sess.created_at else ""

        sess_dict = {
            "id": sess.id,
            "round_type": round_type,
            "role": res.role if res else (getattr(current_user, "target_role", None) or "Software Engineer"),
            "difficulty": difficulty,
            "status": sess.status,
            "created_at": sess.created_at.isoformat() if sess.created_at else None,
            "date_display": created_str,
            "overall_score": res.overall_score if res else None,
            "content_score": res.content_score if res else None,
            "speech_score": res.speech_score if res else None,
            "face_score": res.face_score if res else None,
            "classification": res.classification if res else ("COMPLETED" if sess.status.lower() in ("closed", "completed") else "IN_PROGRESS"),
            "weak_areas": res.weak_areas if res else [],
            "has_report": sess.report is not None,
        }
        formatted_sessions.append(sess_dict)

        if res and res.overall_score is not None:
            completed_scores.append(res.overall_score)
            trend_scores.append({
                "session_id": sess.id,
                "date": sess.created_at.strftime("%b %d") if sess.created_at else f"S{sess.id}",
                "score": round(res.overall_score, 1),
                "round": round_type,
            })

    # Chronological left-to-right display
    trend_scores.reverse()

    # User Memory
    mem = db.query(UserMemory).filter(UserMemory.user_id == current_user.id).first()
    weak_topics = list(mem.weak_topics) if mem and mem.weak_topics else []
    topic_scores = dict(mem.topic_scores) if mem and mem.topic_scores else {}

    # Average score
    avg_score = round(sum(completed_scores) / len(completed_scores), 1) if completed_scores else 0.0

    # Profile confirmed check
    has_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first() is not None

    # Next recommended round calculation
    last_round = formatted_sessions[0]["round_type"] if formatted_sessions else "Technical"
    round_order = ["Technical", "HR", "Managerial", "Mixed"]
    try:
        next_idx = (round_order.index(last_round) + 1) % len(round_order)
        recommended_next_round = round_order[next_idx]
    except ValueError:
        recommended_next_round = "HR"

    last_session = formatted_sessions[0] if formatted_sessions else None

    return {
        "recent_sessions": formatted_sessions[:10],
        "all_sessions_count": len(formatted_sessions),
        "last_session": last_session,
        "trend_scores": trend_scores,
        "current_weak_areas": weak_topics,
        "topic_scores": topic_scores,
        "session_count": mem.session_count if mem else len(completed_scores),
        "average_score": avg_score,
        "recommended_next_round": recommended_next_round,
        "profile_confirmed": has_profile,
        "quick_actions": {
            "retake_same_round": {
                "round_type": last_round,
                "label": f"Retake {last_round} Round",
                "route": f"/interview/setup?round={last_round}&retake=true",
            },
            "try_next_round": {
                "round_type": recommended_next_round,
                "label": f"Try {recommended_next_round} Round",
                "route": f"/interview/setup?round={recommended_next_round}",
            },
            "practice_weak_areas": {
                "topics": weak_topics[:3],
                "label": "Focus on Weak Areas",
                "route": f"/interview/setup?round={last_round}&focus={','.join(weak_topics[:3])}",
            },
        },
    }


@router.get("")
def list_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns candidate's full list of interview sessions with score summaries (Phase 6.3).
    """
    from app.services.interview_context import ensure_user_memory_updated
    ensure_user_memory_updated(current_user.id, db)

    sessions = (
        db.query(InterviewSession)
        .filter(InterviewSession.user_id == current_user.id)
        .order_by(InterviewSession.created_at.desc())
        .all()
    )

    items = []
    for s in sessions:
        cfg = s.interview_config
        res = s.result
        items.append({
            "id": s.id,
            "round_type": cfg.round_type if cfg else "Technical",
            "role": res.role if res else (getattr(current_user, "target_role", None) or "Software Engineer"),
            "difficulty": cfg.difficulty if cfg else "Medium",
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "overall_score": res.overall_score if res else None,
            "content_score": res.content_score if res else None,
            "speech_score": res.speech_score if res else None,
            "face_score": res.face_score if res else None,
            "classification": res.classification if res else ("COMPLETED" if s.status.lower() in ("closed", "completed") else "IN_PROGRESS"),
            "weak_areas": res.weak_areas if res else [],
            "has_report": s.report is not None,
        })

    return {"sessions": items}


def _resolve_session(id: int, auth_ctx: AuthContext, db: Session) -> InterviewSession:
    """
    Validates caller permissions:
    - Registered users can access their own sessions (session.user_id == user.id)
    - Guests can access only their own session matching guest token (session.is_guest and session.id == guest_session_id)
    """
    if auth_ctx.is_guest:
        if auth_ctx.guest_session_id is not None and auth_ctx.guest_session_id != id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Guest token does not permit access to this interview session.",
            )
        session = (
            db.query(InterviewSession)
            .filter(InterviewSession.id == id, InterviewSession.is_guest == True)
            .first()
        )
    else:
        user = auth_ctx.user
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        session = (
            db.query(InterviewSession)
            .filter(InterviewSession.id == id, InterviewSession.user_id == user.id)
            .first()
        )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview session #{id} not found.",
        )
    return session


@router.get("/{id}", response_model=SessionOut)
def get_session(
    id: int,
    request: Request,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Retrieves details for a specific interview session.
    """
    session = _resolve_session(id, auth_ctx, db)

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
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Stores 30-second baseline metrics for face (neutral expression, gaze center, head pose),
    voice level (average volume, pitch range), and background noise floor.
    """
    session = _resolve_session(id, auth_ctx, db)

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
        caller_user_id = auth_ctx.user.id if auth_ctx.user else None
        cal = SessionCalibration(
            session_id=id,
            user_id=caller_user_id,
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
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Retrieves baseline calibration metrics for a session.
    """
    _resolve_session(id, auth_ctx, db)
    cal = (
        db.query(SessionCalibration)
        .filter(SessionCalibration.session_id == id)
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
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Retrieves real-time session state from Redis (current state, question,
    elapsed time, follow-up counts, and Q/A score context).
    """
    session = _resolve_session(id, auth_ctx, db)

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
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns stored question artifacts: audio chunk count, video frame count,
    and transcript with word-level timestamps.
    """
    session = _resolve_session(id, auth_ctx, db)
    from app.services.answer_capture_service import default_storage_manager
    return default_storage_manager.get_question_artifacts(session_id=id, question_id=question_id)


@router.get("/{id}/question/{question_id}/signals")
def get_question_signals(
    id: int,
    question_id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns parallel video & audio signal metrics for a question,
    including comparison against the candidate's calibration baseline.
    """
    session = _resolve_session(id, auth_ctx, db)

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
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """Convenience endpoint returning signals for question or active question."""
    q_id = question_id if question_id is not None else 1
    return get_question_signals(id=id, question_id=q_id, auth_ctx=auth_ctx, db=db)


@router.get("/{id}/integrity-events")
def get_session_integrity_events(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
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
    session = _resolve_session(id, auth_ctx, db)

    from app.services.integrity_monitor import IntegrityMonitor
    monitor = IntegrityMonitor(session_id=id)
    summary = monitor.get_integrity_summary()
    return summary


@router.get("/{id}/integrity")
def get_session_integrity_convenience(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """Convenience alias for /integrity-events."""
    return get_session_integrity_events(id=id, auth_ctx=auth_ctx, db=db)


# =============================================================================
# PHASE 5.1: SESSION CLOSE & ANALYSIS PIPELINE ENDPOINTS
# =============================================================================

@router.post("/{id}/finalize")
def finalize_and_analyze_session(
    id: int,
    sync: bool = Query(False, description="Run synchronously (useful for test suites)"),
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Finalizes recordings, updates Session status to CLOSED, stores file keys,
    and pushes an idempotent analysis job to the queue.
    """
    session = _resolve_session(id, auth_ctx, db)

    from app.services.analysis_pipeline import default_analysis_manager
    job_info = default_analysis_manager.enqueue_analysis_job(session_id=id, sync=sync)
    return {
        "session_id": id,
        "message": "Session recordings finalized and analysis job enqueued.",
        "status": session.status,
        "job": job_info,
    }


@router.post("/{id}/close")
def close_session_alias(
    id: int,
    sync: bool = Query(False),
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """Alias for /finalize."""
    return finalize_and_analyze_session(id=id, sync=sync, auth_ctx=auth_ctx, db=db)


@router.get("/{id}/analysis-status")
def get_session_analysis_status(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Polls real-time status of the analysis pipeline for the session:
    pending, processing, completed, partial, or failed, along with step progress.
    """
    session = _resolve_session(id, auth_ctx, db)

    from app.services.analysis_pipeline import default_analysis_manager
    status_data = default_analysis_manager.get_job_status(session_id=id)
    return status_data


@router.get("/{id}/aligned-data")
def get_session_aligned_data(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns the complete per-question aligned dataset for the session:
    transcript, word timings, face signals, speech signals, integrity events, evaluator scores.
    """
    session = _resolve_session(id, auth_ctx, db)

    from app.services.analysis_pipeline import default_alignment_engine
    aligned = default_alignment_engine.align_session(session_id=id)
    return aligned


@router.get("/{id}/scores")
def get_session_scores(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns the normalized scoring breakdown (0-100) for the interview session:
    - Face & Posture Score
    - Speech Confidence Score
    - Content Rubric Score
    - Composite Overall Score & Classification
    - Per-question factor breakdown and explanation list citing exact deductions.
    """
    session = _resolve_session(id, auth_ctx, db)

    from app.services.analysis_pipeline import default_alignment_engine
    from app.services.scoring_engine import compute_session_scores

    aligned = default_alignment_engine.align_session(session_id=id)
    scores = aligned.get("scores")
    if not scores:
        scores = compute_session_scores(aligned)

    return scores


@router.get("/{id}/result")
def get_session_result(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns the complete consolidated session result object (Phase 5.3):
    - Fused scores (round-type weighted combination of content, speech, face)
    - Comparison data (user baseline delta, session trend, cohort percentile rank)
    - Ranked weak areas with question IDs, scores, and exact deduction evidence
    - Verified UserMemory and AskedQuestion updates.
    """
    session = _resolve_session(id, auth_ctx, db)

    from app.services.score_fusion_service import process_and_persist_session_result
    result_data = process_and_persist_session_result(session_id=id, db=db)
    return result_data


@router.get("/{id}/report")
def get_session_report(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns the final structured grounded interview report (Phase 6.1):
    - Overall summary, strengths, gaps, per-question feedback.
    - Grounding evidence references for every claim.
    - Grounding audit statistics (verified claims, regenerations, dropped claims).
    """
    session = _resolve_session(id, auth_ctx, db)

    from app.services.report_generator_service import generate_and_persist_report
    report_data = generate_and_persist_report(session_id=id, db=db)
    if isinstance(report_data, dict):
        report_data["is_guest"] = bool(session.is_guest)
    return report_data


@router.post("/{id}/generate-report")
def trigger_report_generation(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Triggers explicit 3-pass grounded report generation for the session.
    """
    session = _resolve_session(id, auth_ctx, db)

    from app.services.report_generator_service import generate_and_persist_report
    report_data = generate_and_persist_report(session_id=id, db=db)
    if isinstance(report_data, dict):
        report_data["is_guest"] = bool(session.is_guest)
    return report_data


@router.get("/{id}/improvement-plan")
def get_session_improvement_plan(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns 3-5 concrete action items with practice questions and curated learning resources (Phase 6.2).
    """
    session = _resolve_session(id, auth_ctx, db)

    from app.models import SessionResult
    from app.services.improvement_plan_service import build_improvement_plan

    sess_res = db.query(SessionResult).filter(SessionResult.session_id == id).first()
    if not sess_res:
        from app.services.score_fusion_service import process_and_persist_session_result
        res_dict = process_and_persist_session_result(session_id=id, db=db)
    else:
        res_dict = {
            "overall_score": sess_res.overall_score,
            "content_score": sess_res.content_score,
            "speech_score": sess_res.speech_score,
            "face_score": sess_res.face_score,
            "classification": sess_res.classification,
            "round_type": sess_res.round_type,
            "role": sess_res.role,
            "weak_areas": sess_res.weak_areas,
        }

    plan = build_improvement_plan(res_dict)
    return {"session_id": id, "actions": plan, "is_guest": bool(session.is_guest)}


@router.get("/{id}/pdf")
def get_session_pdf(
    id: int,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Server-side generation of publication-quality PDF report with embedded charts (Phase 6.2).
    PDF export is forbidden for anonymous guests.
    """
    if auth_ctx.is_guest:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PDF export is reserved for registered users. Please create a free account or log in to download PDF reports.",
        )

    session = _resolve_session(id, auth_ctx, db)

    from app.services.pdf_export_service import build_pdf_report
    try:
        pdf_bytes = build_pdf_report(session_id=id, db=db)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="intervai_report_{id}.pdf"',
                "Content-Type": "application/pdf",
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF report: {str(e)}",
        )


# =============================================================================
# 6. SIGNED RECORDING URLS & RETENTION CLEANUP
# =============================================================================

@router.get("/{id}/recording-urls")
def get_session_recording_urls(
    id: int,
    request: Request,
    auth_ctx: AuthContext = Depends(get_current_user_or_guest),
    db: Session = Depends(get_db),
):
    """
    Returns cryptographically signed, expiring URLs (HMAC-SHA256, 1-hour expiry)
    for accessing the session's merged audio and video manifest.
    Authorized strictly to the session owner.
    """
    session = _resolve_session(id, auth_ctx, db)

    from app.services.signed_url_service import generate_signed_recording_url
    base = f"{request.url.scheme}://{request.headers.get('host', '127.0.0.1:8000')}"
    audio_signed = generate_signed_recording_url(id, file_type="audio", expires_in_seconds=3600, base_url=base)
    video_signed = generate_signed_recording_url(id, file_type="video", expires_in_seconds=3600, base_url=base)

    return {
        "session_id": id,
        "audio_url": audio_signed["url"],
        "video_manifest_url": video_signed["url"],
        "expires_at": audio_signed["expires_at"],
        "retention_days": 1 if session.is_guest else settings.RECORDING_RETENTION_DAYS,
    }


@router.get("/{id}/recording/{file_type}")
def get_signed_recording_file(
    id: int,
    file_type: str,
    expires: int = Query(..., description="Expiry timestamp"),
    sig: str = Query(..., description="HMAC-SHA256 signature"),
):
    """
    Downloads/streams recording media file validated by expiring cryptographic signature.
    Rejects expired or tampered requests with 403 Forbidden.
    """
    import os
    from app.services.signed_url_service import verify_signed_recording_url
    from app.services.answer_capture_service import default_storage_manager

    # 1. Cryptographic signature and TTL verification
    if not verify_signed_recording_url(id, file_type, expires_at=expires, signature=sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signed recording URL is invalid, tampered, or has expired.",
        )

    sess_dir = os.path.join(default_storage_manager.base_dir, str(id))

    if file_type == "audio":
        audio_path = os.path.join(sess_dir, "audio_merged.bin")
        if not os.path.exists(audio_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Audio recording for session #{id} not found.",
            )
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        return Response(content=audio_bytes, media_type="audio/webm")

    elif file_type in ("video", "manifest"):
        manifest_path = os.path.join(sess_dir, "video_manifest.json")
        if not os.path.exists(manifest_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Video manifest for session #{id} not found.",
            )
        with open(manifest_path, "rb") as f:
            manifest_bytes = f.read()
        return Response(content=manifest_bytes, media_type="application/json")

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported recording asset type: '{file_type}'",
        )


@router.post("/maintenance/cleanup-retention")
def trigger_retention_cleanup(
    db: Session = Depends(get_db),
):
    """
    Scheduled retention maintenance task:
    - Purges guest recordings older than 24 hours.
    - Purges user recording media blobs older than 30 days.
    """
    from app.services.retention_service import cleanup_all_expired_recordings
    result = cleanup_all_expired_recordings(db)
    return {"status": "ok", "cleanup_summary": result}






