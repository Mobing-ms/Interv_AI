"""Server-side Whisper transcription of a finished answer, with the browser/typed text as fallback."""

import time

import pytest

from app.services.session_orchestrator import SessionOrchestrator
from app.services.session_state import SessionState, SessionStateData


class FakeHostedSTT:
    def __init__(self, result=None, hosted=True):
        self.result = result
        self.is_hosted = hosted
        self.calls = []

    async def transcribe_audio_bytes(self, audio, filename="answer.wav", language="en", prompt=None):
        self.calls.append((len(audio), filename, prompt))
        return self.result


def _listening(stt, sid):
    orch = SessionOrchestrator(session_id=sid, user_id=1, hosted_stt=stt)
    orch.state = SessionStateData(
        session_id=sid, user_id=1, state=SessionState.LISTENING,
        created_at=time.time(), updated_at=time.time(), last_heartbeat=time.time(),
    )
    orch.state.current_question = {"id": 3, "text": "How do you cache a feed?"}

    async def noop():
        return None

    orch.run_state_action = noop
    return orch


WHISPER = {"text": "I precompute it on write.", "words": [{"word": "I", "start": 0.0, "end": 0.2, "probability": 0.9}], "provider": "groq"}


@pytest.mark.asyncio
async def test_whisper_text_replaces_browser_text():
    stt = FakeHostedSTT(WHISPER)
    orch = _listening(stt, 990001)
    orch._answer_audio.extend(b"x" * 2000)
    await orch._finish_answer(answer_text="I pre compute it on right")
    assert orch.state.current_answer_text == "I precompute it on write."
    assert stt.calls and stt.calls[0][1] == "answer.webm"
    assert orch.state.question_transcripts[3]["words"] == WHISPER["words"]


@pytest.mark.asyncio
async def test_mock_fallback_is_never_used_as_the_answer():
    stt = FakeHostedSTT({"text": "I have built distributed systems", "words": [], "provider": "mock"})
    orch = _listening(stt, 990002)
    orch._answer_audio.extend(b"x" * 2000)
    await orch._finish_answer(answer_text="my real words")
    assert orch.state.current_answer_text == "my real words"


@pytest.mark.asyncio
async def test_typed_answer_is_not_overwritten():
    stt = FakeHostedSTT(WHISPER)
    orch = _listening(stt, 990003)
    orch._answer_audio.extend(b"x" * 2000)
    await orch._finish_answer(answer_text="typed answer", typed=True)
    assert orch.state.current_answer_text == "typed answer"
    assert stt.calls == []


@pytest.mark.asyncio
async def test_no_audio_keeps_browser_text():
    stt = FakeHostedSTT(WHISPER)
    orch = _listening(stt, 990004)
    await orch._finish_answer(answer_text="browser text")
    assert orch.state.current_answer_text == "browser text"
    assert stt.calls == []


@pytest.mark.asyncio
async def test_whisper_text_on_silence_is_ignored():
    stt = FakeHostedSTT({"text": "Thank you.", "words": [], "provider": "groq"})
    orch = _listening(stt, 990005)
    orch.state.current_question_speech_detected = False
    orch._answer_audio.extend(b"x" * 2000)
    await orch._finish_answer(answer_text="")
    assert orch.state.current_answer_text == ""


@pytest.mark.asyncio
async def test_new_question_clears_previous_answer_start():
    """A stale start time made the 8 s silence nudge fire while Ava was still asking."""
    orch = _listening(FakeHostedSTT(), 990006)
    orch.state.current_answer_start = time.time() - 60
    orch.state.current_question = {"id": 4, "text": "Next?"}
    orch.state.state = SessionState.ASKING
    emitted = []

    async def emit(t, payload=None):
        emitted.append(t)

    orch.emit = emit
    orch.emit_question = lambda q: emit("question")
    orch.emit_avatar_speak = lambda text, **kw: emit("avatar_speak")
    del orch.run_state_action
    await orch.run_state_action()
    assert orch.state.current_answer_start is None
    assert await orch._check_silence_nudge(time.time()) is None


@pytest.mark.parametrize("text,expected", [
    ("idk", True),
    ("I don't know actually", True),
    ("no idea, sorry", True),
    ("pass", True),
    ("Not sure, but I would start by checking the logs and the latest deploy for errors", False),
    ("I would put a token bucket per API key in Redis", False),
])
def test_non_answer_detection(text, expected):
    from app.services.evaluator_service import is_non_answer
    assert is_non_answer(text) is expected


@pytest.mark.asyncio
async def test_non_answer_is_evaluated_instantly_without_follow_up():
    from app.services.evaluator_service import LLMAnswerEvaluator
    res = await LLMAnswerEvaluator().evaluate_async({"id": 2, "text": "q"}, "I don't know actually", [])
    assert res["non_answer"] and res["overall_score"] == 0.0 and res["follow_up_needed"] is False
