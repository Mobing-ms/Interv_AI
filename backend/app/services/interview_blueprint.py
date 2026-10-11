import math
from typing import Dict, Any, List, Optional, Union
from app.models import InterviewConfig
from app.schemas import (
    StructuredCV,
    TargetProfileOut,
    InterviewConfigCreate,
    UserContextOut,
    BlueprintTopic,
    TimeBreakdown,
    InterviewBlueprint,
)


CORE_TECHNICAL_FOUNDATIONS = [
    "Data Structures & Algorithms",
    "System Design & Scalability",
    "Database Management Systems (DBMS)",
    "Operating Systems & Concurrency",
    "Computer Networks & Protocols",
]

STANDARD_HR_TOPICS = [
    {
        "name": "Self-Introduction & Career Trajectory",
        "description": "Background overview, key milestones, and transition drivers.",
    },
    {
        "name": "Core Strengths & Self-Awareness",
        "description": "Evaluation of greatest strengths and intentional growth areas.",
    },
    {
        "name": "Teamwork & Cross-Functional Collaboration",
        "description": "Navigating multi-disciplinary projects and team dynamics.",
    },
    {
        "name": "Conflict Resolution & Handling Pushback",
        "description": "Resolving technical disagreements and alignment challenges.",
    },
    {
        "name": "Motivation & Cultural Alignment",
        "description": "Why this role, company mission fit, and intrinsic drivers.",
    },
    {
        "name": "Situational Judgment & Adaptability",
        "description": "Navigating ambiguity, shifting deadlines, and resilience.",
    },
]

STANDARD_MANAGERIAL_TOPICS = [
    {
        "name": "Leadership & Mentorship",
        "description": "Coaching peers, delegating effectively, and team empowerment.",
    },
    {
        "name": "Decision-Making Under Ambiguity",
        "description": "Making high-stakes decisions with incomplete data.",
    },
    {
        "name": "Ownership & Accountability",
        "description": "Taking end-to-end responsibility and navigating failures.",
    },
    {
        "name": "Prioritization & Resource Allocation",
        "description": "Managing technical debt vs product roadmap trade-offs.",
    },
    {
        "name": "Stakeholder Management & Alignment",
        "description": "Managing expectations upward and across departments.",
    },
]

DEFAULT_MIXED_RATIO = {
    "Technical": 0.50,
    "HR": 0.30,
    "Managerial": 0.20,
}


def _extract_dict_or_attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _generate_difficulty_curve(difficulty: str, count: int) -> List[str]:
    """
    Builds a realistic difficulty trajectory matching the chosen difficulty.
    """
    diff_lower = difficulty.lower()
    if count <= 0:
        return []

    if diff_lower == "easy":
        # Mostly Easy, 1-2 Medium checkpoints mid-interview
        curve = []
        for i in range(count):
            if count >= 5 and i in (count // 2, count // 2 + 1):
                curve.append("Medium")
            else:
                curve.append("Easy")
        return curve

    elif diff_lower == "hard":
        # Starts Medium (warm entry), then mostly Hard
        curve = ["Medium"] if count > 1 else ["Hard"]
        while len(curve) < count:
            curve.append("Hard")
        return curve

    elif diff_lower == "adaptive":
        # Adaptive difficulty curve tagged with dynamic tiers
        curve = []
        for i in range(count):
            ratio = i / max(1, count - 1)
            if ratio < 0.2:
                curve.append("Medium (Baseline Calibration)")
            elif ratio < 0.6:
                curve.append("Adaptive Tier 1 (Probing)")
            elif ratio < 0.85:
                curve.append("Adaptive Tier 2 (Stress Challenge)")
            else:
                curve.append("Adaptive High-Signal (Peak Evaluation)")
        return curve

    else:
        # Default: Medium bell curve (starts Easy, moves to Medium/Hard, finishes Medium)
        curve = []
        for i in range(count):
            ratio = i / max(1, count - 1)
            if ratio < 0.15:
                curve.append("Easy")
            elif 0.45 <= ratio <= 0.75:
                curve.append("Hard")
            else:
                curve.append("Medium")
        return curve


def _distribute_questions(weights: List[float], total_questions: int) -> List[int]:
    """
    Distributes integer question counts across topics according to their weights
    using the Largest Remainder Method (Hare-Niemeyer), ensuring the sum strictly equals total_questions.
    """
    if not weights or total_questions <= 0:
        return [0] * len(weights)

    # Calculate raw allocations
    exact = [w * total_questions for w in weights]
    floored = [int(math.floor(x)) for x in exact]
    remainder = [exact[i] - floored[i] for i in range(len(weights))]

    shortage = total_questions - sum(floored)

    # Sort indices by descending remainder
    sorted_indices = sorted(range(len(weights)), key=lambda i: remainder[i], reverse=True)
    for i in range(shortage):
        floored[sorted_indices[i % len(sorted_indices)]] += 1

    return floored


def build_interview_blueprint(
    profile: Optional[Union[StructuredCV, Dict[str, Any]]],
    target_profile: Optional[Union[TargetProfileOut, Dict[str, Any]]],
    config: Union[InterviewConfig, InterviewConfigCreate, Dict[str, Any]],
    user_context: Optional[Union[UserContextOut, Dict[str, Any]]] = None,
    mixed_ratio: Optional[Dict[str, float]] = None,
) -> InterviewBlueprint:
    """
    Pure, deterministic function that constructs a tailored interview blueprint.
    Inputs:
        profile: Parsed CV containing skills, projects, and domain details.
        target_profile: User's chosen target role and preferences.
        config: Chosen interview parameters (round_type, difficulty, duration_minutes, mode).
        user_context: Historical candidate memory (weak areas, past scores, asked question history).
        mixed_ratio: Optional custom weight distribution for Mixed rounds.
    """
    round_type = _extract_dict_or_attr(config, "round_type", "Technical")
    difficulty = _extract_dict_or_attr(config, "difficulty", "Medium")
    duration_minutes = _extract_dict_or_attr(config, "duration_minutes", 30)
    mode = (_extract_dict_or_attr(config, "mode", "normal") or "normal").lower()
    focus_topics_override = _extract_dict_or_attr(config, "focus_topics", []) or []

    # 1. Timing & Question Count Fitting
    total_duration_seconds = duration_minutes * 60

    # In pressure mode, answer timer is halved (60s vs 120s)
    if mode == "pressure":
        time_per_question_seconds = 60
    else:
        time_per_question_seconds = 120

    # Reserve 2 minutes (120s) total for warm-up and closing
    base_warm_up_seconds = 60
    base_closing_seconds = 60
    base_buffer_seconds = base_warm_up_seconds + base_closing_seconds

    net_time_seconds = max(0, total_duration_seconds - base_buffer_seconds)
    total_question_count = max(3, net_time_seconds // time_per_question_seconds)

    questions_total_seconds = total_question_count * time_per_question_seconds
    slack_seconds = total_duration_seconds - questions_total_seconds

    # Distribute slack evenly between warm-up and closing so numbers add up exactly
    warm_up_seconds = base_warm_up_seconds + (slack_seconds - base_buffer_seconds) // 2
    closing_seconds = total_duration_seconds - questions_total_seconds - warm_up_seconds

    time_breakdown = TimeBreakdown(
        warm_up_seconds=warm_up_seconds,
        questions_total_seconds=questions_total_seconds,
        closing_seconds=closing_seconds,
        total_allocated_seconds=warm_up_seconds + questions_total_seconds + closing_seconds,
        total_duration_seconds=total_duration_seconds,
        time_per_question_seconds=time_per_question_seconds,
    )

    # 2. Extract Weak Areas from Memory Context
    weak_areas = []
    if user_context:
        weak_areas = _extract_dict_or_attr(user_context, "weak_areas", []) or []
    weak_areas_set = {w.lower().strip() for w in weak_areas}

    # 3. Assemble Topic Candidates based on Round Type
    raw_topics: List[Dict[str, Any]] = []

    # Helper: Technical Topic Extraction
    def get_technical_topics() -> List[Dict[str, Any]]:
        tech_list = []
        skills_dict = _extract_dict_or_attr(profile, "skills", {}) or {}
        projects_list = _extract_dict_or_attr(profile, "projects", []) or []
        target_role = _extract_dict_or_attr(target_profile, "target_role", "")

        # Target Role Core competency
        if target_role:
            tech_list.append({
                "name": f"{target_role} Architecture & Principles",
                "category": "Technical",
                "description": f"Domain architecture and best practices for {target_role}.",
                "base_weight": 1.2,
            })

        # CV Projects Deep-Dive
        for proj in projects_list[:2]:
            p_title = _extract_dict_or_attr(proj, "title", "")
            if p_title:
                tech_list.append({
                    "name": f"Project Deep-Dive: {p_title}",
                    "category": "Project",
                    "description": f"Technical decisions, trade-offs, and outcomes from '{p_title}'.",
                    "base_weight": 1.1,
                })

        # Top frameworks / languages from CV
        languages = _extract_dict_or_attr(skills_dict, "languages", []) or []
        frameworks = _extract_dict_or_attr(skills_dict, "frameworks", []) or []
        tools = _extract_dict_or_attr(skills_dict, "tools", []) or []

        if languages:
            top_langs = ", ".join(languages[:3])
            tech_list.append({
                "name": f"Language Mastery ({top_langs})",
                "category": "Technical",
                "description": f"Idiomatic patterns, memory model, and typing in {top_langs}.",
                "base_weight": 1.0,
            })

        if frameworks:
            top_frameworks = ", ".join(frameworks[:3])
            tech_list.append({
                "name": f"Framework Internals ({top_frameworks})",
                "category": "Technical",
                "description": f"Lifecycle, state mechanisms, and optimization in {top_frameworks}.",
                "base_weight": 1.0,
            })

        # Core Computer Science Fundamentals
        tech_list.append({
            "name": "Data Structures & Algorithms",
            "category": "Technical",
            "description": "Algorithmic efficiency, time/space complexity, and data structures.",
            "base_weight": 1.0,
        })
        tech_list.append({
            "name": "System Design & Scalability",
            "category": "Technical",
            "description": "High-level component design, microservices, and distributed state.",
            "base_weight": 1.0,
        })
        tech_list.append({
            "name": "DBMS, OS & Network Protocols",
            "category": "Technical",
            "description": "Concurrency, transactions, indexing, and transport protocols.",
            "base_weight": 0.9,
        })

        return tech_list

    # Helper: HR Topic Extraction
    def get_hr_topics() -> List[Dict[str, Any]]:
        return [
            {
                "name": item["name"],
                "category": "HR",
                "description": item["description"],
                "base_weight": 1.0,
            }
            for item in STANDARD_HR_TOPICS
        ]

    # Helper: Managerial Topic Extraction
    def get_managerial_topics() -> List[Dict[str, Any]]:
        return [
            {
                "name": item["name"],
                "category": "Managerial",
                "description": item["description"],
                "base_weight": 1.0,
            }
            for item in STANDARD_MANAGERIAL_TOPICS
        ]

    round_norm = round_type.lower().strip()
    effective_mixed_ratio = None

    if round_norm == "technical":
        raw_topics = get_technical_topics()

    elif round_norm == "hr":
        raw_topics = get_hr_topics()

    elif round_norm == "managerial":
        raw_topics = get_managerial_topics()

    elif round_norm == "mixed":
        # Mixed round: blend across categories with configurable ratio
        ratio = dict(mixed_ratio) if mixed_ratio else dict(DEFAULT_MIXED_RATIO)
        # Normalize ratio
        total_r = sum(ratio.values()) or 1.0
        normalized_ratio = {k: v / total_r for k, v in ratio.items()}
        effective_mixed_ratio = normalized_ratio

        tech_pool = get_technical_topics()
        hr_pool = get_hr_topics()
        mgr_pool = get_managerial_topics()

        # Select top representatives from each pool and scale by ratio
        for t in tech_pool[:3]:
            t_copy = dict(t)
            t_copy["base_weight"] = t["base_weight"] * normalized_ratio.get("Technical", 0.5)
            raw_topics.append(t_copy)

        for h in hr_pool[:3]:
            h_copy = dict(h)
            h_copy["base_weight"] = h["base_weight"] * normalized_ratio.get("HR", 0.3)
            raw_topics.append(h_copy)

        for m in mgr_pool[:2]:
            m_copy = dict(m)
            m_copy["base_weight"] = m["base_weight"] * normalized_ratio.get("Managerial", 0.2)
            raw_topics.append(m_copy)

    else:
        # Fallback to technical
        raw_topics = get_technical_topics()

    # 4. Integrate User Focus Overrides & Candidate Weak Areas
    # If the user specified focus topics in config, ensure they are in the list
    existing_topic_names = {t["name"].lower().strip() for t in raw_topics}
    for custom_focus in focus_topics_override:
        if custom_focus.lower().strip() not in existing_topic_names:
            raw_topics.append({
                "name": custom_focus,
                "category": round_type,
                "description": f"Custom focus topic requested by candidate: {custom_focus}",
                "base_weight": 1.2,
            })
            existing_topic_names.add(custom_focus.lower().strip())

    # Ensure weak areas from memory exist in topic list
    for w in weak_areas:
        w_clean = w.lower().strip()
        matched = False
        for t in raw_topics:
            if w_clean in t["name"].lower() or t["name"].lower() in w_clean:
                matched = True
                break
        if not matched:
            raw_topics.append({
                "name": f"Weak Area Focus: {w}",
                "category": round_type if round_type != "Mixed" else "Technical",
                "description": f"Targeted drill-down to strengthen identified growth area: {w}",
                "base_weight": 1.5,
            })

    # 5. Calculate Final Weights with Weak Area Boosting
    # Weak areas receive a substantial multiplier (1.8x)
    boosted_topics = []
    for t in raw_topics:
        t_name_lower = t["name"].lower()
        is_weak = any(w in t_name_lower or t_name_lower in w for w in weak_areas_set)

        weight = t.get("base_weight", 1.0)
        if is_weak:
            weight *= 1.85  # Boost weak area focus

        boosted_topics.append({
            "name": t["name"],
            "category": t["category"],
            "raw_weight": weight,
            "is_weak_area": is_weak,
            "description": t.get("description", ""),
        })

    # Normalize weights so sum equals 1.0
    total_raw_weight = sum(t["raw_weight"] for t in boosted_topics) or 1.0
    weights = [t["raw_weight"] / total_raw_weight for t in boosted_topics]

    # Distribute integer question count across topics
    allocated_counts = _distribute_questions(weights, total_question_count)

    blueprint_topics: List[BlueprintTopic] = []
    for i, t in enumerate(boosted_topics):
        norm_w = round(weights[i], 3)
        blueprint_topics.append(
            BlueprintTopic(
                name=t["name"],
                category=t["category"],
                weight=norm_w,
                allocated_questions=allocated_counts[i],
                is_weak_area=t["is_weak_area"],
                description=t["description"],
            )
        )

    # 6. Difficulty Curve
    difficulty_curve = _generate_difficulty_curve(difficulty, total_question_count)

    # 7. Warm-up & Closing Questions
    target_role = _extract_dict_or_attr(target_profile, "target_role", "Software Engineer")
    candidate_name = ""
    personal = _extract_dict_or_attr(profile, "personal", {}) or {}
    if personal:
        candidate_name = _extract_dict_or_attr(personal, "name", "")

    warm_up_questions = [
        f"Welcome{f' {candidate_name}' if candidate_name else ''}! To kick things off, could you give a 60-second walkthrough of your journey and what drew you to this {round_type} interview today?",
        f"What is one technical or professional challenge you've tackled recently that you're particularly proud of?",
    ]

    closing_questions = [
        "Looking back across our topics today, which area felt most natural, and where did you feel pushed the most?",
        f"Do you have any questions for me regarding expectations, architecture, or life on a {target_role} team?",
    ]

    return InterviewBlueprint(
        round_type=round_type,
        difficulty=difficulty,
        duration_minutes=duration_minutes,
        mode=mode,
        total_question_count=total_question_count,
        time_per_question_seconds=time_per_question_seconds,
        follow_up_limit_per_topic=2,  # Strict max 2 per topic
        difficulty_curve=difficulty_curve,
        topics=blueprint_topics,
        warm_up_questions=warm_up_questions,
        closing_questions=closing_questions,
        time_breakdown=time_breakdown,
        mixed_ratio=effective_mixed_ratio,
    )
