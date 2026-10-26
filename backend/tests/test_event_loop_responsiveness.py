"""
Proves the live-session hot paths do not block the asyncio event loop.

A ticker task counts 20ms ticks while a deliberately slow (blocking) evaluator,
LLM call, or TTS provider runs. If the slow call ran on the loop thread the
ticker would be starved and record ~0 ticks.
"""
import asyncio
import json
import time

import pytest

from app.services.session_orchestrator import SessionOrchestrator
from app.services.evaluator_service import LLMAnswerEvaluator
from app.services.session_state import SessionStateData, SessionState

SLOW = 0.6
TICK = 0.02


async def _count_ticks_during(coro):
    ticks = 0
    done = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not done.is_set():
            await asyncio.sleep(TICK)
            ticks += 1

    t = asyncio.create_task(ticker())
    try:
        result = await coro
    finally:
        done.set()
        await t
    return result, ticks


def _orchestrator(**kw):
    orch = SessionOrchestrator(session_id=987654, user_id=1, **kw)
    orch.state = SessionStateData(
        session_id=987654, user_id=1, state=SessionState.EVALUATING,
        created_at=time.time(), updated_at=time.time(), last_heartbeat=time.time(),
    )
    return orch


class BlockingEvaluator:
    """Sync-only evaluator that blocks like the old sync openai client did."""

    def evaluate(self, question, answer, ctx, session_id=None):
        time.sleep(SLOW)
        return {"overall_score": 5.0, "classification": "OK"}


@pytest.mark.asyncio
async def test_sync_evaluator_runs_off_loop():
    orch = _orchestrator(evaluator_module=BlockingEvaluator())
    start = time.perf_counter()
    res, ticks = await _count_ticks_during(orch._evaluate_answer({"id": 1, "text": "q"}, "an answer"))
    assert res["overall_score"] == 5.0
    assert time.perf_counter() - start >= SLOW
    # ~SLOW/TICK = 30 ticks expected; blocked loop would give 0-1.
    assert ticks >= 10, f"event loop starved during evaluation (ticks={ticks})"


@pytest.mark.asyncio
async def test_llm_evaluator_is_async(monkeypatch):
    from app.services import llm as llm_mod

    async def slow_provider(system_prompt, user_prompt, session_id=None):
        await asyncio.sleep(SLOW)
        return json.dumps({"relevance": 8, "correctness": 7, "depth": 6, "overall_score": 7, "classification": "OK"})

    monkeypatch.setattr(llm_mod.llm_service, "is_active", lambda: True)
    monkeypatch.setattr(llm_mod.llm_service, "_call_provider_once", slow_provider)

    orch = _orchestrator(evaluator_module=LLMAnswerEvaluator())
    res, ticks = await _count_ticks_during(
        orch._evaluate_answer({"id": 1, "text": "q", "expected_keywords": []}, "a real answer")
    )
    assert res["evaluation_source"] == "llm"
    assert res["overall_score"] == 7.0
    assert ticks >= 10, f"event loop starved during LLM evaluation (ticks={ticks})"


@pytest.mark.asyncio
async def test_tts_runs_off_loop(monkeypatch):
    from app.services import session_orchestrator as so

    class SlowTTS:
        def synthesize_speech(self, text, language="English", voice_style="neutral"):
            time.sleep(SLOW)
            return {"audio_url": "/x", "cache_key": "ab", "language": "en"}

    monkeypatch.setattr(so, "default_tts_service", SlowTTS())
    orch = _orchestrator()
    _, ticks = await _count_ticks_during(orch.emit_avatar_speak("hello"))
    assert ticks >= 10, f"event loop starved during TTS (ticks={ticks})"


@pytest.mark.asyncio
async def test_audio_chunks_persist_is_throttled():
    saves = []

    class CountingStore:
        def save_state(self, state):
            saves.append(time.time())

        def load_state(self, sid):
            return None

    orch = _orchestrator(state_store=CountingStore())
    orch.state.state = SessionState.LISTENING
    orch.state.current_question = {"id": 1, "text": "q"}
    for i in range(50):
        await orch.handle_client_event({"type": "heartbeat", "timestamp": time.time()})
    # 50 events in well under 2s -> at most one or two persists, not 50.
    assert len(saves) <= 2, f"state persisted {len(saves)} times for 50 events"
