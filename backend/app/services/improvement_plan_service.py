"""
Improvement Plan Service (Phase 6.2).
Generates 3-5 concrete actionable recommendations based on ranked weak areas from SessionResult.
Includes:
1. Concrete actionable steps addressing specific deduction evidence.
2. 2-3 tailored practice questions per action.
3. Curated learning resources from authoritative, verified documentation platforms (no hallucinated URLs).
"""

from typing import List, Dict, Any, Optional
import re


# =============================================================================
# 1. CURATED LEARNING RESOURCES CATALOG (STRICT VERIFIED SITES)
# =============================================================================

CURATED_RESOURCES: Dict[str, List[Dict[str, str]]] = {
    "system design": [
        {
            "title": "The System Design Primer",
            "url": "https://github.com/donnemartin/system-design-primer",
            "platform": "GitHub Open Source",
            "description": "Comprehensive guide for scalable distributed system architecture, caching, and database sharding.",
        },
        {
            "title": "High Scalability Architecture Case Studies",
            "url": "http://highscalability.com/",
            "platform": "High Scalability",
            "description": "Real-world engineering case studies analyzing throughput, fault tolerance, and load balancing.",
        },
        {
            "title": "Martin Fowler - Microservices Architecture Guide",
            "url": "https://martinfowler.com/articles/microservices.html",
            "platform": "Martin Fowler Architecture",
            "description": "Industry reference on service decomposition, event-driven communication, and distributed transactions.",
        },
    ],
    "database": [
        {
            "title": "PostgreSQL Official Documentation",
            "url": "https://www.postgresql.org/docs/",
            "platform": "PostgreSQL",
            "description": "In-depth reference on query execution plans, MVCC concurrency, transactions, and indexing.",
        },
        {
            "title": "Use The Index, Luke! - Database Indexing",
            "url": "https://use-the-index-luke.com/",
            "platform": "Use The Index, Luke",
            "description": "Definitive developer guide to B-tree indexing, query planner optimization, and slow query elimination.",
        },
        {
            "title": "Designing Data-Intensive Applications Resources",
            "url": "https://dataintensive.net/",
            "platform": "O'Reilly Book Resources",
            "description": "Foundational principles of storage engines, partitioning, replication, and consistency guarantees.",
        },
    ],
    "redis": [
        {
            "title": "Redis Official Documentation & Data Structures",
            "url": "https://redis.io/docs/",
            "platform": "Redis",
            "description": "Detailed guide on in-memory caching patterns, TTL strategies, replication, and pub/sub messaging.",
        },
        {
            "title": "Redis University Developer Courses",
            "url": "https://university.redis.com/",
            "platform": "Redis University",
            "description": "Hands-on tutorials for cache-aside patterns, invalidation semantics, and high availability with Sentinel/Cluster.",
        },
    ],
    "python": [
        {
            "title": "Python Official Language Reference & Standard Library",
            "url": "https://docs.python.org/3/",
            "platform": "Python Software Foundation",
            "description": "Official documentation covering GIL semantics, memory management, asyncio, and data structures.",
        },
        {
            "title": "Real Python Advanced Engineering Tutorials",
            "url": "https://realpython.com/",
            "platform": "Real Python",
            "description": "Practical guides to Python concurrency, typing, decorators, generators, and clean architecture.",
        },
        {
            "title": "FastAPI Official Documentation & Tutorial",
            "url": "https://fastapi.tiangolo.com/",
            "platform": "FastAPI",
            "description": "Modern asynchronous API design, Pydantic data validation, and dependency injection patterns.",
        },
    ],
    "algorithms": [
        {
            "title": "NeetCode DSA Roadmap & Explanations",
            "url": "https://neetcode.io/roadmap",
            "platform": "NeetCode",
            "description": "Structured algorithmic problem roadmap covering dynamic programming, graphs, trees, and complexity.",
        },
        {
            "title": "GeeksforGeeks Data Structures & Algorithms",
            "url": "https://www.geeksforgeeks.org/fundamentals-of-algorithms/",
            "platform": "GeeksforGeeks",
            "description": "Comprehensive reference for fundamental algorithmic paradigms, sorting, and asymptotic analysis.",
        },
    ],
    "behavioral": [
        {
            "title": "Harvard Business Review - Mastering Behavioral Interviews",
            "url": "https://hbr.org/2021/11/how-to-answer-behavioral-interview-questions",
            "platform": "Harvard Business Review",
            "description": "Executive strategies for structuring leadership narratives, conflict resolution, and impact communication.",
        },
        {
            "title": "The STAR Method Complete Interview Guide",
            "url": "https://www.thebalancecareers.com/what-is-the-star-interview-response-technique-2061629",
            "platform": "The Balance Careers",
            "description": "Step-by-step breakdown of Situation, Task, Action, and Result framing with measurable outcomes.",
        },
    ],
    "speech": [
        {
            "title": "Toastmasters International Public Speaking Resources",
            "url": "https://www.toastmasters.org/resources/public-speaking-tips",
            "platform": "Toastmasters International",
            "description": "Techniques for controlling filler words ('um', 'like'), managing vocal pacing, and deliberate pauses.",
        },
        {
            "title": "TED Talks Presentation Mastery",
            "url": "https://www.ted.com/talks",
            "platform": "TED",
            "description": "Mastery of conversational cadence, vocal inflection, pitch variability, and technical storytelling.",
        },
    ],
    "composure": [
        {
            "title": "Harvard DCE: Body Language in Remote Video Interviews",
            "url": "https://extension.harvard.edu/blog/body-language-in-remote-interviews/",
            "platform": "Harvard Division of Continuing Education",
            "description": "Proven practices for eye contact with the camera lens, upright posture, and minimizing fidgeting.",
        },
    ],
    "general": [
        {
            "title": "The Tech Interview Handbook",
            "url": "https://www.techinterviewhandbook.org/",
            "platform": "Tech Interview Handbook",
            "description": "Curated guide for software engineering interview rounds, communication tips, and offer evaluation.",
        },
    ],
}


# =============================================================================
# 2. TOPIC PRACTICE QUESTION CATALOG
# =============================================================================

PRACTICE_QUESTIONS: Dict[str, List[str]] = {
    "system design": [
        "Design a distributed cache system with TTL eviction and cache stampede protection under high read load.",
        "How would you architect a real-time notification service handling 100,000 WebSocket connections with fanout?",
        "Walk through designing an idempotency key layer for an asynchronous payment processing pipeline.",
    ],
    "database": [
        "Explain how B-Tree indexes work in PostgreSQL and why index scans might degrade into sequential scans.",
        "Walk through mitigating a database connection pool exhaustion incident during a production traffic spike.",
        "Compare optimistic vs pessimistic concurrency locking with concrete transaction isolation scenarios.",
    ],
    "redis": [
        "Compare write-through vs write-behind vs cache-aside caching strategies with failure and failover scenarios.",
        "How do you handle Redis cache penetration, cache breakdown, and cache avalanches in production?",
        "Explain Redis persistence options (RDB snapshotting vs AOF append log) and their recovery trade-offs.",
    ],
    "python": [
        "Explain how Python's GIL impacts multithreading vs multiprocessing and when to choose asyncio event loops.",
        "Describe memory management in CPython, reference counting, and cyclic garbage collection mechanisms.",
        "How would you profile and optimize an API endpoint experiencing high latency and memory bloat?",
    ],
    "algorithms": [
        "Implement a Least Recently Used (LRU) Cache supporting get and put in O(1) time complexity.",
        "Given a stream of real-time integer metrics, design a data structure to retrieve the median in O(1) time.",
        "Solve the word break problem using dynamic programming and analyze the time and space complexity.",
    ],
    "behavioral": [
        "Describe a time when you strongly disagreed with a senior engineer's architectural choice and how you resolved it.",
        "Walk me through a production outage or critical bug you introduced, detailing the rollback, fix, and post-mortem.",
        "Tell me about a high-ambiguity project where requirements changed midway through execution. How did you adapt?",
    ],
    "speech": [
        "Deliver a 90-second technical overview of an async message queue maintaining a steady 130-150 WPM cadence.",
        "Practice answering a trade-off question without using filler words ('um', 'like', 'basically') using deliberate 1.5s pauses.",
        "Record a concise explanation of CAP theorem, modulating your pitch and varying volume for key takeaways.",
    ],
    "composure": [
        "Deliver a 2-minute architectural explanation while maintaining direct eye gaze at the camera lens and upright posture.",
        "Practice an answer while consciously resting hands calmly on the desk to eliminate fidgeting and head-sway.",
    ],
    "general": [
        "Structure an end-to-end response using the Problem -> Options -> Decision -> Outcome framework.",
        "Summarize the technical architecture of your most impactful project in exactly 2 minutes with quantifiable metrics.",
    ],
}


# =============================================================================
# 3. DOMAIN MATCHING & RESOURCE RESOLVER
# =============================================================================

def resolve_resource_category(topic: str) -> str:
    """Maps a topic or skill name to one of the curated resource categories."""
    if not topic:
        return "general"
    t_lower = topic.lower()

    if any(k in t_lower for k in ("system", "distributed", "microservice", "scale", "architect", "cloud")):
        return "system design"
    elif any(k in t_lower for k in ("database", "sql", "postgres", "query", "index", "acid", "relational", "orm")):
        return "database"
    elif any(k in t_lower for k in ("redis", "cache", "caching", "memcached", "invalidation")):
        return "redis"
    elif any(k in t_lower for k in ("python", "asyncio", "threading", "gil", "backend", "framework")):
        return "python"
    elif any(k in t_lower for k in ("algo", "data structure", "tree", "graph", "dynamic programming", "dsa", "leetcode")):
        return "algorithms"
    elif any(k in t_lower for k in ("behavioral", "star", "conflict", "leadership", "teamwork", "hr", "managerial", "culture")):
        return "behavioral"
    elif any(k in t_lower for k in ("speech", "pace", "filler", "voice", "pause", "cadence", "clarity", "vocal")):
        return "speech"
    elif any(k in t_lower for k in ("composure", "camera", "face", "eye contact", "gaze", "posture", "fidget")):
        return "composure"
    else:
        return "general"


def get_curated_resources_for_topic(topic: str, max_items: int = 2) -> List[Dict[str, str]]:
    """Returns verified curated learning resources for a topic."""
    cat = resolve_resource_category(topic)
    res_list = CURATED_RESOURCES.get(cat, CURATED_RESOURCES["general"])
    return res_list[:max_items]


def get_practice_questions_for_topic(topic: str, max_items: int = 2) -> List[str]:
    """Returns curated practice questions for a topic."""
    cat = resolve_resource_category(topic)
    q_list = PRACTICE_QUESTIONS.get(cat, PRACTICE_QUESTIONS["general"])
    return q_list[:max_items]


# =============================================================================
# 4. ACTION GENERATOR ENGINE
# =============================================================================

def build_improvement_plan(session_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generates 3 to 5 concrete action items based on ranked weak areas, speech/face scores,
    and interview gaps.
    Every action includes:
    - title
    - topic
    - priority (HIGH, MEDIUM)
    - description (actionable guidance)
    - practice_questions (2-3 items)
    - resources (curated verified links with titles and platforms)
    """
    actions: List[Dict[str, Any]] = []
    weak_areas = session_result.get("weak_areas", [])
    # Unmeasured components produce no speech/face actions (no evidence either way).
    speech_score = session_result.get("speech_score")
    face_score = session_result.get("face_score")
    content_score = session_result.get("content_score")
    round_type = session_result.get("round_type", "Technical")

    # 1. Actions from identified weak areas
    for idx, wa in enumerate(weak_areas[:3]):
        topic = wa.get("topic", "Domain Knowledge")
        avg_score = float(wa.get("average_score", 50.0))
        recommendation = wa.get("recommendation", f"Review core principles of {topic}.")
        evidence_list = wa.get("evidence", [])
        
        # Extract specific deduction reasons if available
        deduction_snippets = []
        for ev in evidence_list:
            for ded in ev.get("deductions", []):
                ded_reason = ded.get("reason", "")
                if ded_reason and ded_reason not in deduction_snippets:
                    deduction_snippets.append(ded_reason)

        if deduction_snippets:
            guidance = f"{recommendation} Focus specifically on addressing: {'; '.join(deduction_snippets[:2])}."
        else:
            guidance = f"{recommendation} Practice articulating architectural trade-offs, edge-cases, and concrete metrics."

        actions.append({
            "id": f"action-{idx + 1}",
            "title": f"Master {topic} Architecture & Trade-Offs",
            "topic": topic,
            "priority": "HIGH" if avg_score < 60.0 else "MEDIUM",
            "target_score": round(min(100.0, avg_score + 25.0), 1),
            "current_score": round(avg_score, 1),
            "description": guidance,
            "practice_questions": get_practice_questions_for_topic(topic, max_items=2),
            "resources": get_curated_resources_for_topic(topic, max_items=2),
        })

    # 2. Check Speech / Vocal Confidence
    if speech_score is not None and (speech_score < 75.0 or (len(actions) < 3 and speech_score < 85.0)):
        actions.append({
            "id": f"action-{len(actions) + 1}",
            "title": "Calibrate Vocal Cadence & Eliminate Filler Words",
            "topic": "Vocal Delivery",
            "priority": "HIGH" if speech_score < 60.0 else "MEDIUM",
            "target_score": 85.0,
            "current_score": round(speech_score, 1),
            "description": (
                "Maintain an ideal speaking pace between 130-155 words per minute. "
                "Replace filler words ('um', 'like', 'you know') with intentional 1.5-second pauses "
                "to structure complex thoughts before speaking."
            ),
            "practice_questions": get_practice_questions_for_topic("speech", max_items=2),
            "resources": get_curated_resources_for_topic("speech", max_items=2),
        })

    # 3. Check Face / Composure
    if face_score is not None and (face_score < 70.0 or (len(actions) < 3 and face_score < 80.0)):
        actions.append({
            "id": f"action-{len(actions) + 1}",
            "title": "Strengthen Camera Presence & Visual Composure",
            "topic": "Physical Composure",
            "priority": "MEDIUM",
            "target_score": 85.0,
            "current_score": round(face_score, 1),
            "description": (
                "Maintain direct eye contact with the camera lens during at least 65% of your answer. "
                "Position your webcam at eye level to support upright posture and minimize head sway or nervous fidgeting."
            ),
            "practice_questions": get_practice_questions_for_topic("composure", max_items=2),
            "resources": get_curated_resources_for_topic("composure", max_items=2),
        })

    # 4. Fill remaining slots up to 3-5 actions
    while len(actions) < 3:
        if round_type.lower() in ("technical", "mixed") and not any("system" in a["topic"].lower() for a in actions):
            actions.append({
                "id": f"action-{len(actions) + 1}",
                "title": "Incorporate Production Edge Cases & Benchmarks",
                "topic": "System Design",
                "priority": "MEDIUM",
                "target_score": 90.0,
                "current_score": round(content_score, 1) if content_score is not None else None,
                "description": (
                    "Elevate your answers by proactively citing production constraints: p99 latency SLAs, "
                    "cache invalidation thundering-herd mitigations, and database failover scenarios."
                ),
                "practice_questions": get_practice_questions_for_topic("system design", max_items=2),
                "resources": get_curated_resources_for_topic("system design", max_items=2),
            })
        elif not any("behavioral" in a["topic"].lower() or "star" in a["topic"].lower() for a in actions):
            actions.append({
                "id": f"action-{len(actions) + 1}",
                "title": "Structure Responses with the STAR Method",
                "topic": "Behavioral Framing",
                "priority": "MEDIUM",
                "target_score": 90.0,
                "current_score": 75.0,
                "description": (
                    "Deliver answers using Situation -> Task -> Action -> Result framing. "
                    "Ensure the Result clearly quantifies business impact (e.g., 'reduced API p99 latency by 42%')."
                ),
                "practice_questions": get_practice_questions_for_topic("behavioral", max_items=2),
                "resources": get_curated_resources_for_topic("behavioral", max_items=2),
            })
        else:
            actions.append({
                "id": f"action-{len(actions) + 1}",
                "title": "Advanced Algorithmic Complexity Articulation",
                "topic": "Algorithms",
                "priority": "MEDIUM",
                "target_score": 90.0,
                "current_score": 75.0,
                "description": (
                    "State time and space complexity upfront before writing or explaining code. "
                    "Explicitly walk through boundary test cases and memory allocation limits."
                ),
                "practice_questions": get_practice_questions_for_topic("algorithms", max_items=2),
                "resources": get_curated_resources_for_topic("algorithms", max_items=2),
            })

    # Limit to at most 5 actions
    return actions[:5]
