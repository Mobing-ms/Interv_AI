"""
Test isolation: every pytest run gets its own DATA_DIR (sqlite db, recordings,
uploads, TTS cache), so runs never see each other's leftovers.
Must run before `app` is imported, which conftest guarantees.
"""
import os
import sys
import tempfile

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

_tmp = tempfile.mkdtemp(prefix="intervai-tests-")
os.environ["DATA_DIR"] = _tmp
os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("STT_PROVIDER", "mock")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-not-for-production-use-0123456789")
os.environ["AUTO_MIGRATE"] = "false"
# Never touch a developer's real Redis: force the in-memory fallback.
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"

import shutil  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_process_state():
    """
    SQLite reuses row ids after deletes, so different tests can get the same
    session id. Clear every per-session in-process cache and on-disk session
    artifacts between tests so state never leaks across tests.
    """
    _reset()
    yield


def _reset():
    from app.config import settings
    from app.services.session_state import default_state_store
    from app.services import signal_workers, analysis_pipeline, answer_capture_service

    client = default_state_store._get_client()
    if hasattr(client, "flushall"):
        client.flushall()
    elif hasattr(client, "_store"):
        client._store.clear()

    store = signal_workers.default_signal_store
    store._buffer.clear()
    store._session_cache.clear()
    proc = signal_workers.default_signal_processor
    for worker_attr in ("video_worker", "audio_worker"):
        w = getattr(proc, worker_attr, None)
        for cache in ("_prev_landmarks", "_session_metrics"):
            if w is not None and hasattr(w, cache):
                getattr(w, cache).clear()
    analysis_pipeline.default_analysis_manager._memory_jobs.clear()
    stt = answer_capture_service.default_stt_service
    if hasattr(stt, "_transcripts"):
        stt._transcripts.clear()

    sessions_dir = os.path.join(settings.DATA_DIR, "storage", "sessions")
    shutil.rmtree(sessions_dir, ignore_errors=True)
    os.makedirs(sessions_dir, exist_ok=True)


@pytest.fixture(autouse=True)
def _no_random_follow_ups(monkeypatch):
    """Optional follow-ups on OK/STRONG answers are random; keep routing deterministic in tests."""
    from app.services import router_service
    monkeypatch.setattr(router_service, "OK_FOLLOW_UP_RATE", 0.0)
    monkeypatch.setattr(router_service, "STRONG_FOLLOW_UP_RATE", 0.0)
