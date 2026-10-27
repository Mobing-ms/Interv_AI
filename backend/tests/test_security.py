"""Regression tests for WS auth, guest-link proof and production config fail-closed."""
import secrets
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.database import SessionLocal, Base, engine
from app.models import User, InterviewSession, InterviewConfig
from app.auth import (
    create_access_token,
    create_refresh_token,
    create_guest_token,
    authenticate_ws_session,
)
from app.config import Settings, validate_settings, ConfigError

Base.metadata.create_all(bind=engine)
client = TestClient(app)


@pytest.fixture
def two_users_and_session():
    db = SessionLocal()
    tag = uuid.uuid4().hex[:8]
    a = User(name="A", email=f"sec_a_{tag}@example.com", auth_provider="email", is_verified=True)
    b = User(name="B", email=f"sec_b_{tag}@example.com", auth_provider="email", is_verified=True)
    db.add_all([a, b])
    db.commit()
    cfg = InterviewConfig(user_id=a.id, round_type="Technical", difficulty="Medium", duration_minutes=30,
                          language="English", mode="normal", focus_topics=[])
    db.add(cfg)
    db.commit()
    sess = InterviewSession(user_id=a.id, interview_id=cfg.id, status="created", session_token=secrets.token_urlsafe(32))
    gsess = InterviewSession(user_id=None, interview_id=cfg.id, status="created", is_guest=True, guest_id=f"guest_{tag}",
                             session_token=secrets.token_urlsafe(32))
    db.add_all([sess, gsess])
    db.commit()
    ids = dict(cfg=cfg.id, a=a.id, b=b.id, sess=sess.id, sess_token=sess.session_token, gsess=gsess.id, gid=gsess.guest_id)
    db.close()
    yield ids
    db = SessionLocal()
    db.query(InterviewSession).filter(InterviewSession.id.in_([ids["sess"], ids["gsess"]])).delete()
    db.query(InterviewConfig).filter(InterviewConfig.id == ids["cfg"]).delete()
    db.query(User).filter(User.id.in_([ids["a"], ids["b"]])).delete()
    db.commit()
    db.close()


def _auth(sid, token):
    db = SessionLocal()
    try:
        return authenticate_ws_session(db, sid, token) is not None
    finally:
        db.close()


def test_ws_auth_matrix(two_users_and_session):
    ids = two_users_and_session
    sid, gsid = ids["sess"], ids["gsess"]
    # accepted
    assert _auth(sid, ids["sess_token"])
    assert _auth(sid, create_access_token({"sub": str(ids["a"])}))
    assert _auth(gsid, create_guest_token(ids["gid"], gsid))
    # rejected: old fallback cases
    assert not _auth(sid, "demo")
    assert not _auth(sid, "x" * 40)
    assert not _auth(sid, None)
    # rejected: another user's JWT, refresh token, guest token for another session
    assert not _auth(sid, create_access_token({"sub": str(ids["b"])}))
    assert not _auth(sid, create_refresh_token({"sub": str(ids["a"])}))
    assert not _auth(sid, create_guest_token(ids["gid"], gsid))
    assert not _auth(gsid, create_guest_token("guest_other", gsid))
    # rejected: expired access token
    assert not _auth(sid, create_access_token({"sub": str(ids["a"])}, expires_delta=timedelta(seconds=-5)))
    # a session token is not valid for a different session
    assert not _auth(gsid, ids["sess_token"])


@pytest.mark.parametrize("path", ["live", "orchestrate", "stream"])
def test_ws_endpoints_reject_demo_token(two_users_and_session, path):
    sid = two_users_and_session["sess"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/session/{sid}/{path}?token=demo") as ws:
            ws.receive_json()


def test_guest_link_requires_guest_token(two_users_and_session):
    ids = two_users_and_session
    token_b = create_access_token({"sub": str(ids["b"])})
    r = client.post("/guest/link", json={"guest_session_id": ids["gsess"]},
                    headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 403
    r = client.post("/guest/link",
                    json={"guest_session_id": ids["gsess"], "guest_token": create_guest_token(ids["gid"], ids["gsess"])},
                    headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 200


def test_maintenance_endpoint_requires_token():
    assert client.post("/session/maintenance/cleanup-retention").status_code == 403


def _prod(**kw):
    base = dict(ENV="production", DEBUG=False, DEV_MODE=False, JWT_SECRET_KEY=secrets.token_urlsafe(48),
                LLM_PROVIDER="openai", LLM_API_KEY="k", STT_PROVIDER="groq", TURNSTILE_SECRET_KEY="t")
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_production_config_fails_closed():
    validate_settings(_prod())  # a complete config is accepted
    for bad in (
        dict(JWT_SECRET_KEY=""),
        dict(JWT_SECRET_KEY="intervai-super-secret-jwt-key-2026-production-ready"),
        dict(JWT_SECRET_KEY="short"),
        dict(DEBUG=True),
        dict(DEV_MODE=True),
        dict(LLM_PROVIDER="mock"),
        dict(STT_PROVIDER="mock"),
        dict(TURNSTILE_SECRET_KEY=""),
    ):
        with pytest.raises(ConfigError):
            validate_settings(_prod(**bad))


def test_dev_defaults_are_safe(monkeypatch):
    for key in ("DEBUG", "DEV_MODE", "JWT_SECRET_KEY", "ENV"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.DEBUG is False and s.DEV_MODE is False
    validate_settings(s)
    assert len(s.JWT_SECRET_KEY) >= 32
