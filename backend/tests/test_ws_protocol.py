"""Consolidated /live endpoint: pre-check mode, aliases and server keepalive."""
from app.config import settings
from tests.test_security import client, two_users_and_session  # noqa: F401  (fixture reuse)


def _frames_until(ws, wanted, limit=40):
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg["type"])
        if msg["type"] == wanted:
            return msg, seen
    raise AssertionError(f"{wanted} not received; got {seen}")


def test_precheck_mode_then_start(two_users_and_session):
    ids = two_users_and_session
    with client.websocket_connect(f"/session/{ids['sess']}/live?token={ids['sess_token']}&autostart=false") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "connected" and hello["state"] == "PRECHECK"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        ws.send_json({"type": "media_chunk", "data": "abc"})
        assert ws.receive_json()["type"] == "chunk_ack"
        ws.send_json({"type": "heartbeat"})  # any other message starts the interview
        connected, _ = _frames_until(ws, "connected")
        assert connected["state"] in ("GREETING", "WARMUP")


def test_server_keepalive_during_greeting(two_users_and_session):
    ids = two_users_and_session
    old = settings.WS_SERVER_PING_SECONDS
    settings.WS_SERVER_PING_SECONDS = 1.0
    try:
        with client.websocket_connect(f"/session/{ids['sess']}/live?token={ids['sess_token']}") as ws:
            msg, seen = _frames_until(ws, "keepalive")
            assert "server_time" in msg
    finally:
        settings.WS_SERVER_PING_SECONDS = old
