"""
Answer Evaluator Service (Phase 4.4).
Computes deterministic keyword coverage in code, analyzes STAR completeness for behavioral questions,
scores candidate responses using the tunable evaluation rubric, and outputs validated evaluation results.
"""

import re
import json
import time
import logging
from typing import Dict, Any, List, Optional
from app.prompts.evaluation_rubric import EVALUATION_SYSTEM_PROMPT, PROBING_FOLLOW_UP_PROMPT_TEMPLATE
from app.services.orchestrator_modules import EvaluatorModuleProtocol

logger = logging.getLogger("intervai.evaluator")


# =============================================================================
# 1. KEYWORD COVERAGE COMPUTATION (IN CODE)
# =============================================================================

def normalize_text_for_matching(text: str) -> str:
    """Lowercases, normalizes whitespace, and cleans punctuation for robust matching."""
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s\(\)\.\+\-\*\/]", " ", text.lower())
    return " ".join(cleaned.split())


def compute_keyword_coverage(
    transcript: str,
    expected_keywords: List[str],
    ideal_answer_points: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Computes keyword and key-point coverage purely in code using normalized phrase
    and token boundary matching.

    Returns:
        {
            "matched": List[str],
            "missing": List[str],
            "coverage_ratio": float, # 0.0 - 1.0
            "ideal_points_covered": List[str],
        }
    """
    if not expected_keywords:
        return {
            "matched": [],
            "missing": [],
            "coverage_ratio": 1.0,
            "ideal_points_covered": [],
        }

    norm_transcript = normalize_text_for_matching(transcript)
    matched_keywords: List[str] = []
    missing_keywords: List[str] = []

    for kw in expected_keywords:
        kw_clean = normalize_text_for_matching(kw)
        if not kw_clean:
            continue

        # Check for phrase substring or word boundary match
        pattern = r"\b" + re.escape(kw_clean) + r"\b"
        if re.search(pattern, norm_transcript) or (kw_clean in norm_transcript):
            matched_keywords.append(kw)
        else:
            missing_keywords.append(kw)

    ratio = len(matched_keywords) / max(1, len(expected_keywords))

    # Match against ideal answer points if provided
    ideal_points_covered: List[str] = []
    if ideal_answer_points:
        for point in ideal_answer_points:
            pt_tokens = [w for w in normalize_text_for_matching(point).split() if len(w) > 3]
            if pt_tokens:
                matches_in_point = sum(1 for tok in pt_tokens if tok in norm_transcript)
                if matches_in_point / len(pt_tokens) >= 0.4:
                    ideal_points_covered.append(point)

    return {
        "matched": matched_keywords,
        "missing": missing_keywords,
        "coverage_ratio": round(ratio, 3),
        "ideal_points_covered": ideal_points_covered,
    }


# =============================================================================
# 2. STAR COMPLETENESS ANALYSIS (BEHAVIORAL ANSWERS)
# =============================================================================

def is_behavioral_question(question: Dict[str, Any]) -> bool:
    """Determines whether a question is behavioral/situational."""
    q_type = str(question.get("type", "")).lower()
    topic = str(question.get("topic", "")).lower()
    text = str(question.get("text", "")).lower()

    if q_type in ("behavioral", "situational", "leadership", "hr", "managerial"):
        return True
    if topic in ("hr", "managerial", "behavioral", "leadership", "teamwork", "conflict"):
        return True
    behavioral_triggers = [
        "tell me about a time",
        "describe a situation",
        "give an example of",
        "how did you handle",
        "conflict with",
        "leadership",
        "failure",
    ]
    return any(trigger in text for trigger in behavioral_triggers)


def evaluate_star_completeness(transcript: str, question: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates Situation, Task, Action, and Result components for behavioral questions.
    """
    if not is_behavioral_question(question):
        return {
            "is_behavioral": False,
            "situation": True,
            "task": True,
            "action": True,
            "result": True,
            "star_score": 10.0,
            "missing_elements": [],
        }

    norm = normalize_text_for_matching(transcript)

    # Heuristic pattern checks
    sit_patterns = [r"\b(at|when|while working|during|in my previous|at my last|project|team|company|situation|context)\b"]
    task_patterns = [r"\b(needed to|had to|goal was|tasked with|challenge was|objective|responsible for|responsibility|problem|target)\b"]
    act_patterns = [
        r"\b(i (analyzed|analysed|investigated|identified|decided|built|designed|implemented|organized|organised|communicated|led|wrote|resolved|created|configured|fixed|took|managed))\b",
        r"\b(implemented|designed|built|analyzed|investigated|resolved|configured|fixed|refactored|automated)\b",
        r"\b(my approach|my role|my action|steps i took)\b",
    ]
    res_patterns = [r"\b(result|resulting in|improved|reduced|increased|achieved|delivered|outcome|percent|%|uptime|metrics|saving|saved)\b"]

    sit_found = any(re.search(p, norm) for p in sit_patterns)
    task_found = any(re.search(p, norm) for p in task_patterns)
    act_found = any(re.search(p, norm) for p in act_patterns)
    res_found = any(re.search(p, norm) for p in res_patterns)

    # Word count heuristic
    word_count = len(norm.split())
    if word_count < 20:
        res_found = False

    missing = []
    if not sit_found:
        missing.append("Situation")
    if not task_found:
        missing.append("Task")
    if not act_found:
        missing.append("Action")
    if not res_found:
        missing.append("Result")

    # STAR score: 2.5 points per element
    points = (1 if sit_found else 0) + (1 if task_found else 0) + (1 if act_found else 0) + (1 if res_found else 0)
    star_score = round(points * 2.5, 1)

    return {
        "is_behavioral": True,
        "situation": sit_found,
        "task": task_found,
        "action": act_found,
        "result": res_found,
        "star_score": star_score,
        "missing_elements": missing,
    }


# =============================================================================
# 3. DETERMINISTIC RULE-BASED EVALUATOR (FALLBACK & OFFLINE)
# =============================================================================

def extract_quote_from_transcript(transcript: str, max_chars: int = 80) -> str:
    """Extracts a concise, clean excerpt from the transcript for quotation."""
    clean = transcript.strip().replace('"', "'")
    if len(clean) <= max_chars:
        return clean
    # Try finding sentence boundary
    period_idx = clean.find(".")
    if 10 < period_idx <= max_chars:
        return clean[:period_idx + 1]
    return clean[:max_chars] + "..."


def deterministic_evaluate(
    question: Dict[str, Any],
    transcript: str,
    session_context: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Pure Python rule-based evaluator providing deterministic scoring, classification,
    and transcript-quoted justification.
    """
    expected_kw = question.get("expected_keywords", [])
    ideal_pts = question.get("ideal_answer_points", [])
    topic = question.get("topic", "General")
    q_text = question.get("text", "")

    # 1. Compute keyword coverage in code
    kw_res = compute_keyword_coverage(transcript, expected_kw, ideal_pts)
    star_res = evaluate_star_completeness(transcript, question)

    norm_ans = normalize_text_for_matching(transcript)
    words = norm_ans.split()
    word_count = len(words)
    cov_ratio = kw_res["coverage_ratio"]

    # 2. Check for OFF_TOPIC
    dodge_phrases = ["i don't know", "no idea", "pass", "i have no clue", "skip this"]
    is_dodge = any(p in norm_ans for p in dodge_phrases) and word_count < 15

    q_tokens = [w for w in normalize_text_for_matching(q_text).split() if len(w) > 3]
    topic_tokens = [w for w in normalize_text_for_matching(topic).split() if len(w) > 2]
    overlap_count = sum(1 for tok in (q_tokens + topic_tokens) if tok in norm_ans)

    # Detect blatant off-topic tangents
    off_topic_markers = ["pizza", "recipe", "football", "cricket", "weather outside", "bought a car", "movie last night", "dinner", "burger", "vacation"]
    has_off_topic_marker = any(m in norm_ans for m in off_topic_markers)

    # Check for technical or domain keywords indicating an attempt to answer
    tech_context_tokens = [
        "server", "client", "loop", "check", "block", "call", "calls", "function", "data", "array",
        "code", "user", "request", "requests", "table", "memory", "cache", "database", "api",
        "process", "method", "items", "item", "algorithm", "logic", "time", "space", "tree", "node",
        "queue", "stack", "pointer", "index", "string", "hash", "key", "value", "network", "system",
        "scale", "cluster", "concurrency", "thread", "async", "sync", "test", "variable", "class",
        "object", "service", "load", "traffic", "limit", "rate", "performance", "latency", "storage",
        "team", "project", "work", "colleague", "incident", "production", "fix", "deploy", "failover"
    ]
    has_tech_context = any(t in norm_ans for t in tech_context_tokens)

    # Off-topic if explicit dodge, off-topic marker, or completely disconnected without tech/domain context
    is_off_topic = is_dodge or has_off_topic_marker or (word_count > 10 and overlap_count == 0 and len(kw_res["matched"]) == 0 and not has_tech_context)

    if is_off_topic:
        relevance = 2.0
        correctness = 2.5
        depth = 2.0
        overall_score = 2.2
        classification = "OFF_TOPIC"
        quote = extract_quote_from_transcript(transcript)
        justification = f"The candidate's response ('{quote}') did not address the core question regarding {topic} and appeared unrelated."
        gap = f"Explain the fundamental concepts of {topic} directly requested in the prompt."

        return {
            "relevance": relevance,
            "correctness": correctness,
            "depth": depth,
            "overall_score": overall_score,
            "keyword_coverage": kw_res,
            "star_completeness": star_res,
            "justification": justification,
            "classification": classification,
            "follow_up_gap": gap,
            "word_count": word_count,
            "follow_up_needed": False,  # Off-topic triggers redirect, not follow-up probe
        }

    # 3. Check for WEAK_VAGUE
    # - Short answers (< 25 words)
    # - Low keyword coverage (< 0.40)
    # - Behavioral answer missing Result / Action
    # - Generic hand-wavy explanations
    is_weak_behavioral = star_res["is_behavioral"] and (not star_res["result"] or not star_res["action"])
    is_brief_technical = not star_res["is_behavioral"] and (word_count < 25 or cov_ratio < 0.40)

    if is_brief_technical or is_weak_behavioral or word_count < 15:
        relevance = 6.0 if word_count >= 15 else 4.5
        correctness = round(min(6.5, max(4.0, 4.0 + (cov_ratio * 3.0))), 1)
        depth = round(min(4.8, max(2.5, (word_count / 30.0) * 4.5)), 1)
        overall_score = round((relevance * 0.3) + (correctness * 0.4) + (depth * 0.3), 1)
        classification = "WEAK_VAGUE"
        quote = extract_quote_from_transcript(transcript)

        missing_kw_str = ", ".join(kw_res["missing"][:2]) if kw_res["missing"] else "concrete implementation trade-offs"
        justification = (
            f"The candidate attempted the question stating '{quote}', but provided a surface-level response "
            f"without detailing {missing_kw_str}."
        )
        gap = (
            f"Missing specific metrics and impact"
            if star_res["is_behavioral"]
            else f"Elaborate on {missing_kw_str} and specific trade-offs"
        )

        return {
            "relevance": relevance,
            "correctness": correctness,
            "depth": depth,
            "overall_score": overall_score,
            "keyword_coverage": kw_res,
            "star_completeness": star_res,
            "justification": justification,
            "classification": classification,
            "follow_up_gap": gap,
            "word_count": word_count,
            "follow_up_needed": True,
        }

    # 4. Check for STRONG vs OK
    # STRONG requires high keyword coverage (>= 0.7), good length (>= 30 words), complete STAR if behavioral
    if cov_ratio >= 0.70 and word_count >= 30 and (not star_res["is_behavioral"] or star_res["star_score"] >= 7.5):
        relevance = round(min(9.8, 8.5 + (cov_ratio * 1.3)), 1)
        correctness = round(min(9.7, 8.2 + (cov_ratio * 1.5)), 1)
        depth = round(min(9.5, 7.5 + min(2.0, (word_count / 60.0) * 2.0)), 1)
        overall_score = round((relevance * 0.35) + (correctness * 0.35) + (depth * 0.30), 1)
        classification = "STRONG"
        quote = extract_quote_from_transcript(transcript)
        matched_str = ", ".join(kw_res["matched"][:3])
        justification = (
            f"Comprehensive and accurate response quoting '{quote}', demonstrating deep technical understanding "
            f"covering key points like {matched_str}."
        )
        gap = "Explore advanced edge cases and 10x scale bottlenecks."

        return {
            "relevance": relevance,
            "correctness": correctness,
            "depth": depth,
            "overall_score": overall_score,
            "keyword_coverage": kw_res,
            "star_completeness": star_res,
            "justification": justification,
            "classification": classification,
            "follow_up_gap": gap,
            "word_count": word_count,
            "follow_up_needed": False,
        }

    # 5. OK (Satisfactory, solid response)
    relevance = 7.5
    correctness = round(min(8.0, 6.5 + (cov_ratio * 2.0)), 1)
    depth = round(min(7.0, 5.5 + min(1.5, (word_count / 50.0) * 1.5)), 1)
    overall_score = round((relevance * 0.35) + (correctness * 0.35) + (depth * 0.30), 1)
    classification = "OK"
    quote = extract_quote_from_transcript(transcript)
    justification = (
        f"Solid foundational answer stating '{quote}', addressing the core requirements with reasonable clarity."
    )
    gap = f"Elaborate on edge cases or operational telemetry."

    return {
        "relevance": relevance,
        "correctness": correctness,
        "depth": depth,
        "overall_score": overall_score,
        "keyword_coverage": kw_res,
        "star_completeness": star_res,
        "justification": justification,
        "classification": classification,
        "follow_up_gap": gap,
        "word_count": word_count,
        "follow_up_needed": False,
    }


# =============================================================================
# 4. LLM ANSWER EVALUATOR (HYBRID DETERMINISTIC + LLM)
# =============================================================================

class LLMAnswerEvaluator(EvaluatorModuleProtocol):
    """
    Evaluates candidate responses:
    - Computes keyword coverage in code.
    - Evaluates STAR completeness for behavioral answers.
    - Employs low-temperature LLM scoring with the tunable rubric file.
    - Falls back to deterministic rule engine if LLM is unavailable or offline.
    """

    def __init__(self, temperature: float = 0.0, use_deterministic_only: bool = False):
        self.temperature = temperature
        self.use_deterministic_only = use_deterministic_only

    def evaluate(
        self,
        question: Dict[str, Any],
        answer: str,
        session_context: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Evaluates a candidate's answer and returns validated JSON output.
        """
        # Always compute code-level keyword coverage first
        expected_kw = question.get("expected_keywords", [])
        ideal_pts = question.get("ideal_answer_points", [])
        code_kw_res = compute_keyword_coverage(answer, expected_kw, ideal_pts)
        code_star_res = evaluate_star_completeness(answer, question)

        # If deterministic mode requested or offline, run deterministic evaluator
        if self.use_deterministic_only:
            return deterministic_evaluate(question, answer, session_context)

        # Attempt LLM call if OpenAI/Gemini/other provider configured
        try:
            from app.config import settings
            api_key = getattr(settings, "OPENAI_API_KEY", None)
            if not api_key:
                # Default to deterministic evaluator when no key is set
                return deterministic_evaluate(question, answer, session_context)

            # Low temperature LLM prompt call
            import openai
            client = openai.OpenAI(api_key=api_key)
            user_prompt = (
                f"Question: {question.get('text')}\n"
                f"Topic: {question.get('topic')}\n"
                f"Question Type: {question.get('type', 'technical')}\n"
                f"Expected Keywords: {expected_kw}\n"
                f"Ideal Answer Points: {ideal_pts}\n"
                f"Code-Matched Keywords: {code_kw_res['matched']}\n"
                f"Code-Missing Keywords: {code_kw_res['missing']}\n"
                f"Candidate Transcript: {answer}\n"
            )

            resp = client.chat.completions.create(
                model=getattr(settings, "EVALUATION_MODEL", "gpt-4o-mini"),
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
            raw_content = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw_content)

            # Validate and merge with code-level keyword coverage
            classification = parsed.get("classification", "OK").upper()
            if classification not in ("STRONG", "OK", "WEAK_VAGUE", "OFF_TOPIC"):
                classification = "OK"

            result = {
                "relevance": float(parsed.get("relevance", 7.0)),
                "correctness": float(parsed.get("correctness", 7.0)),
                "depth": float(parsed.get("depth", 7.0)),
                "overall_score": float(parsed.get("overall_score", 7.0)),
                "keyword_coverage": code_kw_res,  # Code-computed keyword coverage
                "star_completeness": parsed.get("star_completeness", code_star_res),
                "justification": str(parsed.get("justification", extract_quote_from_transcript(answer))),
                "classification": classification,
                "follow_up_gap": str(parsed.get("follow_up_gap", "elaborate further")),
                "word_count": len(answer.split()),
                "follow_up_needed": classification == "WEAK_VAGUE",
                "evaluated_at": time.time(),
            }
            return result

        except Exception as e:
            logger.warning("LLM evaluation call failed or not configured (%s); using deterministic evaluator", e)
            return deterministic_evaluate(question, answer, session_context)
