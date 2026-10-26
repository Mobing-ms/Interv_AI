"""
Unit & Integration Test Suite for Phase 4.4:
Evaluator (LLM/Deterministic, Rubric, Code-Level Keyword Coverage, STAR Completeness)
Router Decision Logic (Pure Function, Probing Follow-ups, Strictly Max 2, Difficulty Scaling, Redirects, Closing)
"""

import os
import time
import json
import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.services.session_state import SessionStateData, SessionState, default_state_store
from app.services.evaluator_service import (
    compute_keyword_coverage,
    evaluate_star_completeness,
    deterministic_evaluate,
    LLMAnswerEvaluator,
)
from app.services.router_service import (
    decide_route,
    generate_probing_follow_up,
    handle_closing_inquiry,
    RouterService,
    MAX_FOLLOWUPS_PER_TOPIC,
)
from app.services.session_orchestrator import SessionOrchestrator
from app.database import SessionLocal
from app.models import User, UserConsent, InterviewConfig, InterviewSession
from app.auth import create_access_token, hash_password

client = TestClient(app)


class TestEvaluatorAndRouterPhase4(unittest.TestCase):
    def setUp(self):
        db = SessionLocal()
        try:
            email = f"candidate_router_{int(time.time() * 1000)}@test.com"
            self.candidate = User(
                email=email,
                name="Alex Router",
                password_hash=hash_password("Secret123!"),
                auth_provider="email",
                is_verified=True,
                onboarding_status="completed",
            )
            db.add(self.candidate)
            db.commit()
            db.refresh(self.candidate)
            self.candidate_id = self.candidate.id
            self.token = create_access_token(data={"sub": str(self.candidate.id), "email": self.candidate.email})
        finally:
            db.close()

        # Consent record
        client.post(
            "/session/consent",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"version": "v1.0", "accepted": True},
        )

    def _create_session(self, mode: str = "normal", duration_minutes: int = 15) -> dict:
        cfg_resp = client.post(
            "/interview/config",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "round_type": "Technical",
                "difficulty": "Medium",
                "duration_minutes": duration_minutes,
                "mode": mode,
            },
        )
        self.assertEqual(cfg_resp.status_code, 201)
        cfg_id = cfg_resp.json()["id"]

        sess_resp = client.post(
            "/session",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"interview_id": cfg_id},
        )
        self.assertEqual(sess_resp.status_code, 201)
        return sess_resp.json()

    # =========================================================================
    # 1. EVALUATOR: KEYWORD COVERAGE IN CODE
    # =========================================================================

    def test_compute_keyword_coverage_in_code(self):
        """Keyword coverage is strictly computed in code with case/punctuation normalization."""
        expected = ["hash table", "sliding window", "two pointers", "O(N)"]
        transcript = (
            "I would maintain a Sliding Window using Two Pointers. "
            "To detect duplicates in O(N) time complexity, I use a Hash Table to record indices."
        )

        res = compute_keyword_coverage(transcript, expected)
        self.assertEqual(len(res["matched"]), 4)
        self.assertEqual(len(res["missing"]), 0)
        self.assertEqual(res["coverage_ratio"], 1.0)

        # Partial coverage test
        partial_transcript = "I used two pointers for moving across the array."
        res_partial = compute_keyword_coverage(partial_transcript, expected)
        self.assertIn("two pointers", res_partial["matched"])
        self.assertIn("sliding window", res_partial["missing"])
        self.assertIn("hash table", res_partial["missing"])
        self.assertEqual(res_partial["coverage_ratio"], 0.25)

    # =========================================================================
    # 2. EVALUATOR: STAR COMPLETENESS FOR BEHAVIORAL QUESTIONS
    # =========================================================================

    def test_star_completeness_for_behavioral_answers(self):
        """Behavioral answers are validated for Situation, Task, Action, and Result components."""
        behavioral_q = {
            "id": 101,
            "text": "Tell me about a time you resolved a major production incident under pressure.",
            "topic": "HR",
            "type": "behavioral",
            "expected_keywords": ["incident", "root cause", "postmortem"],
        }

        # Complete STAR answer
        complete_transcript = (
            "During my previous project at Acme Corp, a critical database bottleneck caused severe outage. "
            "I was tasked with restoring customer API availability within 15 minutes. "
            "I analyzed server logs, identified the lock contention, and implemented an emergency failover script. "
            "As a result, we restored 99.9% uptime and reduced recovery time by 40%."
        )
        star_full = evaluate_star_completeness(complete_transcript, behavioral_q)
        self.assertTrue(star_full["is_behavioral"])
        self.assertTrue(star_full["situation"])
        self.assertTrue(star_full["task"])
        self.assertTrue(star_full["action"])
        self.assertTrue(star_full["result"])
        self.assertEqual(star_full["star_score"], 10.0)
        self.assertEqual(len(star_full["missing_elements"]), 0)

        # Incomplete answer (Missing Result)
        incomplete_transcript = (
            "At my last company, there was a broken deploy. I had to look into the logs and I decided to restart it."
        )
        star_partial = evaluate_star_completeness(incomplete_transcript, behavioral_q)
        self.assertTrue(star_partial["is_behavioral"])
        self.assertFalse(star_partial["result"])
        self.assertIn("Result", star_partial["missing_elements"])
        self.assertLess(star_partial["star_score"], 10.0)

    # =========================================================================
    # 3. EVALUATOR CLASSIFICATIONS (STRONG, WEAK_VAGUE, OFF_TOPIC)
    # =========================================================================

    def test_evaluator_classifications_strong_weak_offtopic(self):
        """Deterministic evaluator correctly classifies answers and includes transcript quotes."""
        evaluator = LLMAnswerEvaluator(use_deterministic_only=True)
        tech_q = {
            "id": 1,
            "text": "How do you implement a distributed rate limiter?",
            "topic": "System Design",
            "type": "technical",
            "expected_keywords": ["redis", "token bucket", "concurrency", "low latency"],
        }

        # 1. STRONG Answer
        strong_ans = (
            "I architect the rate limiter using Redis and the token bucket algorithm. "
            "We handle concurrency with atomic Lua scripts to prevent race conditions, "
            "ensuring low latency and high availability across distributed nodes."
        )
        res_strong = evaluator.evaluate(tech_q, strong_ans, [])
        self.assertEqual(res_strong["classification"], "STRONG")
        self.assertGreaterEqual(res_strong["relevance"], 7.5)
        self.assertGreaterEqual(res_strong["correctness"], 7.5)
        self.assertGreaterEqual(res_strong["depth"], 7.0)
        self.assertIn("redis", res_strong["justification"].lower())

        # 2. WEAK_VAGUE Answer
        vague_ans = "I think we can use a server and check if there are too many calls, then block them."
        res_vague = evaluator.evaluate(tech_q, vague_ans, [])
        self.assertEqual(res_vague["classification"], "WEAK_VAGUE")
        self.assertLess(res_vague["depth"], 5.0)
        self.assertTrue(res_vague["follow_up_needed"])
        self.assertTrue(len(res_vague["follow_up_gap"]) > 0)
        self.assertIn("too many calls", res_vague["justification"].lower())

        # 3. OFF_TOPIC Answer
        offtopic_ans = "My favorite food is Italian pizza with cheese and mushrooms."
        res_offtopic = evaluator.evaluate(tech_q, offtopic_ans, [])
        self.assertEqual(res_offtopic["classification"], "OFF_TOPIC")
        self.assertLess(res_offtopic["relevance"], 3.5)
        self.assertIn("pizza", res_offtopic["justification"].lower())

    # =========================================================================
    # 4. ROUTER PURE FUNCTION: WEAK_VAGUE PROBING FOLLOW-UP
    # =========================================================================

    def test_router_pure_function_weak_vague_probes_same_topic(self):
        """WEAK_VAGUE triggers a probing follow-up on the same topic."""
        state = SessionStateData(
            session_id=10,
            user_id=1,
            topic="DSA",
            current_question={"id": 5, "text": "Explain sliding window.", "topic": "DSA"},
            follow_up_count_per_topic={"DSA": 0},
            total_questions_target=3,
        )
        eval_res = {
            "classification": "WEAK_VAGUE",
            "follow_up_gap": "Explain window shrinkage when duplicate keys are found.",
        }

        route = decide_route(state, eval_res)
        self.assertEqual(route["action"], "follow_up")
        self.assertEqual(route["topic"], "DSA")
        self.assertEqual(route["reason"], "probing_follow_up_1")
        self.assertFalse(route["round_done"])

        # Follow-up question generation targets the gap
        fu_q = generate_probing_follow_up(state.current_question, eval_res, "DSA")
        self.assertTrue(fu_q["is_follow_up"])
        self.assertEqual(fu_q["topic"], "DSA")
        self.assertEqual(fu_q["parent_question_id"], 5)
        self.assertTrue("shrinkage" in fu_q["text"].lower() or "mechanism" in fu_q["text"].lower())

    # =========================================================================
    # 5. ROUTER PURE FUNCTION: STRICTLY MAX 2 FOLLOW-UPS PER TOPIC
    # =========================================================================

    def test_router_pure_function_strictly_caps_followups_at_2(self):
        """Follow-ups never exceed 2 per topic even if candidate remains vague."""
        # 1st follow-up
        state = SessionStateData(
            session_id=10,
            user_id=1,
            topic="DSA",
            current_question={"id": 5, "text": "Explain sliding window.", "topic": "DSA"},
            follow_up_count_per_topic={"DSA": 0},
            total_questions_target=3,
        )
        route1 = decide_route(state, {"classification": "WEAK_VAGUE"})
        self.assertEqual(route1["action"], "follow_up")

        # 2nd follow-up
        state.follow_up_count_per_topic["DSA"] = 1
        route2 = decide_route(state, {"classification": "WEAK_VAGUE"})
        self.assertEqual(route2["action"], "follow_up")

        # 3rd attempt: MUST NOT follow-up, MUST advance topic
        state.follow_up_count_per_topic["DSA"] = 2
        route3 = decide_route(state, {"classification": "WEAK_VAGUE"})
        self.assertEqual(route3["action"], "next_question")
        self.assertNotEqual(route3["action"], "follow_up")

    # =========================================================================
    # 6. ROUTER PURE FUNCTION: STRONG RAISES DIFFICULTY & DEEPENS
    # =========================================================================

    def test_router_pure_function_strong_raises_difficulty(self):
        """STRONG answers prompt the router to raise difficulty."""
        state = SessionStateData(
            session_id=10,
            user_id=1,
            topic="System Design",
            difficulty="Medium",
            current_question={"id": 20, "text": "Design rate limiter.", "topic": "System Design"},
            total_questions_target=3,
        )
        eval_res = {"classification": "STRONG"}

        route = decide_route(state, eval_res)
        self.assertEqual(route["action"], "next_question")
        self.assertEqual(route["difficulty_adjustment"], "raise")

    # =========================================================================
    # 7. ROUTER PURE FUNCTION: OFF_TOPIC REDIRECTS AND REPEATS ONCE
    # =========================================================================

    def test_router_pure_function_off_topic_redirects_and_repeats_once(self):
        """OFF_TOPIC redirects politely and repeats question once, avoiding infinite loops."""
        state = SessionStateData(
            session_id=10,
            user_id=1,
            topic="DSA",
            current_question={"id": 30, "text": "Invert binary tree.", "topic": "DSA"},
            question_repeat_count={},
            total_questions_target=3,
        )
        eval_res = {"classification": "OFF_TOPIC", "relevance": 1.5}

        # 1st time off-topic -> Redirect and repeat
        route1 = decide_route(state, eval_res)
        self.assertEqual(route1["action"], "redirect")
        self.assertTrue(route1["repeat_question"])
        self.assertIn("refocus", route1["redirect_message"].lower())

        # 2nd time off-topic on same question -> Advances to next question (no loop)
        state.question_repeat_count["30"] = 1
        route2 = decide_route(state, eval_res)
        self.assertNotEqual(route2["action"], "redirect")

    # =========================================================================
    # 8. CLOSING FLOW & "ANY QUESTIONS FOR US?"
    # =========================================================================

    def test_closing_inquiry_handling(self):
        """Closing handles candidate questions about tech stack, culture, or wrap-up."""
        # Candidate asks about tech stack
        ans_stack = handle_closing_inquiry("What tech stack do you use?")
        self.assertIn("FastAPI", ans_stack["text"])
        self.assertIn("TypeScript", ans_stack["text"])
        self.assertTrue(ans_stack["is_closing_complete"])

        # Candidate asks about culture
        ans_culture = handle_closing_inquiry("Can you tell me about the engineering culture?")
        self.assertIn("collaborative", ans_culture["text"].lower())

        # Candidate has no questions
        ans_none = handle_closing_inquiry("No, that's all. Thank you!")
        self.assertIn("thank you", ans_none["text"].lower())

    # =========================================================================
    # 9. INTEGRATION: FULL WEBSOCKET EVALUATION & ROUTING LOOP
    # =========================================================================

    def test_websocket_orchestrator_full_evaluation_routing_loop(self):
        """
        Full WebSocket integration:
        - Candidate answers Warmup
        - Candidate gives WEAK_VAGUE answer -> receives follow-up probing question on same topic
        - Candidate gives STRONG answer -> advances and raises difficulty
        - Questions append validated evaluation metrics (relevance, correctness, depth, classification, STAR)
        - Session cleanly reaches CLOSING ('Any questions for us?') and ends.
        """
        s_data = self._create_session(mode="normal")
        sess_id = s_data["id"]
        sess_token = s_data["session_token"]

        with client.websocket_connect(f"/session/{sess_id}/live?token={sess_token}") as ws:
            ws.receive_json()  # connected
            ws.receive_json()  # greeting avatar_speak
            ws.receive_json()  # warmup question
            ws.receive_json()  # warmup avatar_speak

            # 1. Answer warmup
            ws.send_json({
                "type": "answer_ended",
                "text": "Hello, I am Alex, backend engineer with experience building distributed microservices.",
            })

            # 2. Server evaluates Warmup and emits Main Question #1
            q1 = ws.receive_json()
            self.assertEqual(q1["type"], "question")
            self.assertFalse(q1.get("is_follow_up", False))
            q1_topic = q1.get("topic", "DSA")
            _ = ws.receive_json()  # q1 avatar_speak

            # 3. Candidate sends a WEAK_VAGUE answer to Q1
            ws.send_json({
                "type": "answer_ended",
                "text": "I think we just loop through the items and check them one by one.",
            })

            # 4. Server evaluates -> WEAK_VAGUE -> Routes to probing follow-up on SAME topic
            fu_q = ws.receive_json()
            self.assertEqual(fu_q["type"], "question")
            self.assertTrue(fu_q.get("is_follow_up", True))
            self.assertEqual(fu_q.get("topic"), q1_topic)
            _ = ws.receive_json()  # follow-up avatar_speak

            # 5. Candidate sends a STRONG answer to the follow-up
            ws.send_json({
                "type": "answer_ended",
                "text": (
                    f"To optimize {q1_topic}, I maintain a sliding window with two pointers and a hash set. "
                    "This achieves strictly O(N) time complexity and O(K) space complexity, handling edge cases "
                    "such as duplicate keys by shrinking the window from the left."
                ),
            })

            # 6. Server receives strong answer -> evaluates -> advances to next main question or closing
            next_msg = ws.receive_json()
            if next_msg["type"] == "question":
                # Answer next question strongly to finish interview
                _ = ws.receive_json()  # avatar_speak
                ws.send_json({
                    "type": "answer_ended",
                    "text": (
                        "I use Redis cluster with token bucket rate limiting and Lua scripts "
                        "to ensure low latency concurrency and fault tolerance."
                    ),
                })
                next_msg = ws.receive_json()

            # Ensure session reaches round_end / closing
            while next_msg.get("type") != "round_end":
                if next_msg.get("type") == "question":
                    _ = ws.receive_json()
                    ws.send_json({
                        "type": "answer_ended",
                        "text": "Scalable distributed architecture with low latency and fault tolerance.",
                    })
                next_msg = ws.receive_json()

            self.assertEqual(next_msg["type"], "round_end")
            summary = next_msg["summary"]
            self.assertGreaterEqual(summary["total_questions"], 2)
            self.assertGreater(summary["average_score"], 0)

        # 7. Verify session state in Redis has rich evaluated context
        saved_state = default_state_store.load_state(sess_id)
        self.assertIsNotNone(saved_state)
        self.assertGreaterEqual(len(saved_state.session_context), 2)
        q1_eval = saved_state.session_context[1]  # Q1 answer
        self.assertIn("relevance", q1_eval)
        self.assertIn("correctness", q1_eval)
        self.assertIn("depth", q1_eval)
        self.assertIn("classification", q1_eval)
        self.assertIn("justification", q1_eval)
        self.assertIn("keyword_coverage", q1_eval)


if __name__ == "__main__":
    unittest.main()
