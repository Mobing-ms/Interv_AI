"""
Question flow quality: occasional follow-ups that build on the answer,
CV/topic alternation, and the closing reply handling.
"""

import asyncio
import json
import unittest
from unittest.mock import patch

from app.services import router_service
from app.services.router_service import decide_route, generate_follow_up_async, handle_closing_inquiry
from app.services.question_selector import select_next_question
from app.services.session_state import SessionStateData
from app.services.llm import llm_service


def _state(**kw):
    base = dict(session_id=1, user_id=1, topic="System Design",
                current_question={"id": 20, "text": "Design a rate limiter.", "topic": "System Design"},
                total_questions_target=5)
    base.update(kw)
    return SessionStateData(**base)


class TestOptionalFollowUps(unittest.TestCase):
    def test_strong_answer_can_go_deeper(self):
        with patch.object(router_service, "STRONG_FOLLOW_UP_RATE", 1.0):
            route = decide_route(_state(), {"classification": "STRONG"})
        self.assertEqual(route["action"], "follow_up")
        self.assertEqual(route["follow_up_reason"], "go_deeper")

    def test_ok_answer_can_be_probed(self):
        with patch.object(router_service, "OK_FOLLOW_UP_RATE", 1.0):
            route = decide_route(_state(), {"classification": "OK", "follow_up_gap": "no metrics"})
        self.assertEqual(route["action"], "follow_up")
        self.assertEqual(route["follow_up_reason"], "probe_gap")

    def test_no_optional_follow_up_on_a_follow_up_or_after_one(self):
        with patch.object(router_service, "STRONG_FOLLOW_UP_RATE", 1.0):
            fu_q = {"id": 21, "text": "Why Redis?", "topic": "System Design", "is_follow_up": True}
            self.assertNotEqual(decide_route(_state(current_question=fu_q), {"classification": "STRONG"})["action"], "follow_up")
            probed = _state(follow_up_count_per_topic={"System Design": 1})
            self.assertNotEqual(decide_route(probed, {"classification": "STRONG"})["action"], "follow_up")

    def test_vague_answer_always_probed(self):
        route = decide_route(_state(), {"classification": "WEAK_VAGUE", "follow_up_gap": "no specifics"})
        self.assertEqual(route["action"], "follow_up")
        self.assertEqual(route["follow_up_reason"], "probe_gap")


class TestNonAnswersAndRepeats(unittest.TestCase):
    def test_short_non_answer_is_probed_not_redirected(self):
        route = decide_route(_state(), {"classification": "OFF_TOPIC", "answer": "Someone else on my team handled it.", "word_count": 7})
        self.assertEqual(route["action"], "follow_up")

    def test_vague_answer_to_a_follow_up_moves_on(self):
        fu_q = {"id": 21, "text": "Walk me through one step.", "topic": "System Design", "is_follow_up": True}
        route = decide_route(_state(current_question=fu_q), {"classification": "WEAK_VAGUE"})
        self.assertNotEqual(route["action"], "follow_up")

    def test_long_off_topic_answer_is_redirected(self):
        route = decide_route(_state(), {"classification": "OFF_TOPIC", "word_count": 60})
        self.assertEqual(route["action"], "redirect")

    def test_repeated_question_counts_once_toward_round_target(self):
        ctx = [
            {"question_id": 1, "topic": "Warmup"},
            {"question_id": 7, "topic": "System Design"},
            {"question_id": 7, "topic": "System Design"},  # same question after a redirect
        ]
        self.assertEqual(router_service.count_all_main_questions(ctx), 1)
        state = _state(session_context=ctx)
        route = decide_route(state, {"classification": "OK"}, blueprint={"total_questions": 2})
        self.assertNotEqual(route["action"], "close")


class TestFollowUpWriter(unittest.TestCase):
    q = {"id": 5, "text": "How did you build the rate limiter at PayFlow?", "topic": "System Design", "subtopic": "Rate limiting"}

    def test_uses_llm_text_that_builds_on_the_answer(self):
        seen = {}

        def handler(system_prompt, user_prompt):
            seen["prompt"] = user_prompt
            return {"text": "You said you used a Lua script; what happens if Redis fails over mid-script?",
                    "expected_keywords": ["failover", "atomicity"]}

        ev = {"answer": "I used a Lua script in Redis for atomic token-bucket updates, keyed per API key, "
                        "with a sliding window as a fallback and alerts on rejection rates.", "follow_up_gap": "failure modes"}
        with patch.object(llm_service, "is_active", return_value=True), patch.object(llm_service, "_mock_handler", handler):
            fu = asyncio.run(generate_follow_up_async(self.q, ev, "System Design", reason="go_deeper"))
        self.assertIn("Lua script", fu["text"])
        self.assertTrue(fu["is_follow_up"])
        self.assertEqual(fu["parent_question_id"], 5)
        self.assertEqual(fu["expected_keywords"], ["failover", "atomicity"])
        self.assertIn("Lua script in Redis", seen["prompt"])  # the answer reaches the prompt

    def test_short_answer_gets_neutral_probe_without_llm(self):
        def handler(system_prompt, user_prompt):
            raise AssertionError("LLM should not be called for a non-answer")

        with patch.object(llm_service, "is_active", return_value=True), patch.object(llm_service, "_mock_handler", handler):
            fu = asyncio.run(generate_follow_up_async(self.q, {"answer": "I'm not really sure.", "follow_up_gap": "x"}, "System Design"))
        self.assertIn(fu["text"], router_service.SHORT_ANSWER_PROBES)

    def test_falls_back_when_llm_returns_junk(self):
        with patch.object(llm_service, "is_active", return_value=True), \
                patch.object(llm_service, "_mock_handler", lambda s, u: json.dumps({"text": "ok"})):
            long_answer = "We measured it in several ways across the rollout and compared the dashboards before and after the change went live."
            fu = asyncio.run(generate_follow_up_async(self.q, {"answer": long_answer, "follow_up_gap": "no metrics"}, "System Design"))
        self.assertIn("measurable outcome", fu["text"])

    def test_fallback_never_uses_the_old_traffic_template(self):
        for gap in ("edge cases and bottlenecks", "trade-offs", "metrics", "vague", "caching"):
            fu = router_service.generate_probing_follow_up(self.q, {"follow_up_gap": gap}, "System Design")
            self.assertNotIn("10x", fu["text"])
        leaked = router_service.generate_probing_follow_up(self.q, {"follow_up_gap": "Ask about Redis failover"}, "System Design")
        self.assertNotIn("Ask about", leaked["text"])


class TestCvTopicAlternation(unittest.TestCase):
    pool = [
        {"id": 1, "text": "Project question A", "topic": "System Design", "is_cv_based": True},
        {"id": 2, "text": "Project question B", "topic": "System Design", "is_cv_based": True},
        {"id": 3, "text": "Topic question C", "topic": "System Design", "is_cv_based": False},
    ]
    bp = {"topics": [{"name": "System Design", "weight": 1}]}

    def test_opens_with_cv_question_then_alternates(self):
        first = select_next_question(self.pool, self.bp, [], current_difficulty="Medium")
        self.assertTrue(first["is_cv_based"])
        ctx = [{"question_id": first["id"], "question": first["text"], "topic": "System Design", "is_cv_based": True}]
        second = select_next_question(self.pool, self.bp, ctx, current_difficulty="Medium")
        self.assertFalse(second["is_cv_based"])


class TestClosingReply(unittest.TestCase):
    def test_no_questions_variants(self):
        for reply in ("", "No, that's all. Thank you!", "nope", "Nothing from my side"):
            self.assertNotIn("good question", handle_closing_inquiry(reply)["text"].lower(), reply)

    def test_real_question_is_acknowledged(self):
        self.assertIn("good question", handle_closing_inquiry("What does the team work on?")["text"].lower())
        self.assertIn("good question", handle_closing_inquiry("Is there no on-call rotation?")["text"].lower())


if __name__ == "__main__":
    unittest.main()
