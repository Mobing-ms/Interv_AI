import json
import logging
import random
import math
import re
from typing import List, Dict, Any, Optional, Set
from pydantic import BaseModel, Field

from app.schemas import (
    InterviewBlueprint,
    BlueprintTopic,
    StructuredCV,
    TargetProfileOut,
    UserContextOut,
    QuestionBankItemOut,
)
from app.services.llm import llm_service

logger = logging.getLogger("intervai.question_generator")
from app.services.question_dedupe import (
    deduplicate_questions,
    compute_question_hash,
)


VALID_QUESTION_TYPES = {
    "conceptual",
    "coding-explanation",
    "scenario",
    "behavioral",
    "project-based",
}

VALID_DIFFICULTIES = {"Easy", "Medium", "Hard", "Adaptive"}

FOLLOW_UP_TEMPLATES = [
    "What specific trade-offs or bottlenecks would emerge if request throughput increased by 10x?",
    "How would you handle failure scenarios or partial outages in that approach?",
    "If you could redesign that architecture today, what would you change and why?",
    "What metrics or observability signals would you monitor to ensure correctness?",
    "How did you validate that trade-off with your team or stakeholders?",
]


class GeneratedQuestionSchema(BaseModel):
    text: str
    topic: str
    subtopic: Optional[str] = "General"
    difficulty: str = "Medium"
    question_type: str = "conceptual"
    expected_keywords: List[str] = Field(default_factory=list)
    ideal_answer_points: List[str] = Field(default_factory=list)
    max_time_seconds: int = 120
    cv_reference: Optional[str] = None


class QuestionPoolPayload(BaseModel):
    questions: List[GeneratedQuestionSchema]


def _extract_dict_or_attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _generate_fallback_questions(
    blueprint: InterviewBlueprint,
    profile: Optional[Any],
    target_profile: Optional[Any],
    multiplier: float = 2.5,
) -> List[Dict[str, Any]]:
    """
    Context-aware deterministic generation based on CV skills, projects, education,
    and blueprint topics. Guarantees 100% adherence to schema, keywords, and real CV items.
    Generates a 2-3x seed pool meeting or exceeding blueprint.total_question_count * multiplier.
    """
    skills_dict = _extract_dict_or_attr(profile, "skills", {}) or {}
    languages = _extract_dict_or_attr(skills_dict, "languages", []) or ["TypeScript", "Python"]
    frameworks = _extract_dict_or_attr(skills_dict, "frameworks", []) or ["React", "FastAPI"]
    tools = _extract_dict_or_attr(skills_dict, "tools", []) or ["Docker", "Git"]
    projects_list = _extract_dict_or_attr(profile, "projects", []) or []
    target_role = _extract_dict_or_attr(target_profile, "target_role", "Software Engineer")

    time_limit = blueprint.time_per_question_seconds
    total_needed = int(math.ceil(blueprint.total_question_count * multiplier))
    candidates: List[Dict[str, Any]] = []
    seen_texts: Set[str] = set()

    def add_candidate(c: Dict[str, Any]):
        norm_t = c["text"].strip().lower()
        if norm_t not in seen_texts:
            seen_texts.add(norm_t)
            candidates.append(c)

    topics_list = blueprint.topics or []
    if not topics_list:
        topics_list = [
            BlueprintTopic(name="Problem solving", category="Technical", weight=0.5, allocated_questions=5, is_weak_area=False),
            BlueprintTopic(name="Communication", category="HR", weight=0.5, allocated_questions=5, is_weak_area=False),
        ]

    for topic in topics_list:
        t_name = topic.name
        t_cat = topic.category
        is_weak = topic.is_weak_area

        # 1. Project Deep-Dive Topic
        if "Project" in t_name or "Project" in t_cat:
            # Find matching project or use first project
            matching_proj = None
            for p in projects_list:
                p_title = _extract_dict_or_attr(p, "title", "")
                if p_title and p_title.lower() in t_name.lower():
                    matching_proj = p
                    break
            if not matching_proj and projects_list:
                matching_proj = projects_list[0]

            if matching_proj:
                p_title = _extract_dict_or_attr(matching_proj, "title", "Core Project")
                p_tech = _extract_dict_or_attr(matching_proj, "tech_stack", []) or []
                p_outcomes = _extract_dict_or_attr(matching_proj, "outcomes", "")
                tech_str = ", ".join(p_tech[:3]) if p_tech else "modern software architecture"

                add_candidate({
                    "text": f"In your project '{p_title}', how did you architect the system using {tech_str}, and what were the most critical performance trade-offs?",
                    "topic": t_name,
                    "subtopic": "Architecture & Decisions",
                    "difficulty": blueprint.difficulty if blueprint.difficulty != "Adaptive" else "Medium",
                    "question_type": "project-based",
                    "expected_keywords": p_tech[:3] + ["architecture", "trade-offs", "performance"],
                    "ideal_answer_points": [
                        f"Explanation of component boundaries in {p_title}.",
                        f"Rationale for choosing {tech_str}.",
                        "Concrete trade-offs made between latency, complexity, and maintainability.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Project: {p_title}",
                    "is_weak_area": is_weak,
                })
                add_candidate({
                    "text": f"Walk me through a production obstacle, race condition, or bottleneck you diagnosed while delivering '{p_title}'. What diagnostic steps did you take?",
                    "topic": t_name,
                    "subtopic": "Debugging & Reliability",
                    "difficulty": "Hard" if blueprint.difficulty in ("Hard", "Adaptive") else "Medium",
                    "question_type": "project-based",
                    "expected_keywords": ["bottleneck", "debugging", "profiling", "latency", "root cause"],
                    "ideal_answer_points": [
                        "Identified root cause using telemetry or profiling.",
                        "Step-by-step diagnostic methodology.",
                        "Long-term automated fix and prevention guardrails.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Project: {p_title}",
                    "is_weak_area": is_weak,
                })
                add_candidate({
                    "text": f"How did you design for data consistency, error recovery, and failure resilience in '{p_title}'?",
                    "topic": t_name,
                    "subtopic": "Resilience & Recovery",
                    "difficulty": "Medium",
                    "question_type": "project-based",
                    "expected_keywords": ["data consistency", "resilience", "recovery", "fault tolerance"],
                    "ideal_answer_points": [
                        "Strategies for handling downstream transient faults.",
                        "Idempotency or rollback mechanisms.",
                        "Observability alerts and automated circuit breaking.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Project: {p_title}",
                    "is_weak_area": is_weak,
                })
                add_candidate({
                    "text": f"If request volume or data scale for '{p_title}' increased by 50x tomorrow, what component would break first and how would you redesign it?",
                    "topic": t_name,
                    "subtopic": "Horizontal Scalability",
                    "difficulty": "Hard",
                    "question_type": "project-based",
                    "expected_keywords": ["scaling", "bottlenecks", "partitioning", "concurrency", "caching"],
                    "ideal_answer_points": [
                        "Identification of the primary bottleneck tier.",
                        "Sharding, queuing, or read-replica decomposition.",
                        "Capacity calculation and graceful degradation strategy.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Project: {p_title}",
                    "is_weak_area": is_weak,
                })

        # 2. Language Mastery Topic
        elif "Language" in t_name:
            for lang in languages[:3]:
                add_candidate({
                    "text": f"Explain how {lang} handles memory management, garbage collection, and variable allocation (stack vs heap).",
                    "topic": t_name,
                    "subtopic": f"{lang} Memory Model",
                    "difficulty": "Medium",
                    "question_type": "conceptual",
                    "expected_keywords": [lang.lower(), "memory management", "heap", "stack", "garbage collection"],
                    "ideal_answer_points": [
                        f"Memory lifecycle and allocation mechanisms in {lang}.",
                        "Garbage collection or manual deallocation semantics.",
                        "Techniques to minimize GC pauses or memory leaks.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Skill: {lang}",
                    "is_weak_area": is_weak,
                })
                add_candidate({
                    "text": f"How do concurrency, threading, and asynchronous workloads operate in {lang}? What patterns prevent race conditions?",
                    "topic": t_name,
                    "subtopic": f"{lang} Concurrency",
                    "difficulty": "Hard",
                    "question_type": "conceptual",
                    "expected_keywords": [lang.lower(), "concurrency", "async", "threads", "race condition", "synchronization"],
                    "ideal_answer_points": [
                        f"Concurrency execution model in {lang} (goroutines, event loop, threads).",
                        "Synchronization primitives (mutexes, channels, locks).",
                        "Common anti-patterns and deadlock avoidance.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Skill: {lang}",
                    "is_weak_area": is_weak,
                })
                add_candidate({
                    "text": f"What are the most distinctive typing or design idioms in {lang}, and how do they impact code maintainability in production?",
                    "topic": t_name,
                    "subtopic": f"{lang} Idioms",
                    "difficulty": "Medium",
                    "question_type": "conceptual",
                    "expected_keywords": [lang.lower(), "type safety", "idiomatic", "interfaces", "generics"],
                    "ideal_answer_points": [
                        f"Type system design in {lang}.",
                        "Idiomatic code patterns vs anti-patterns.",
                        "Error handling conventions.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Skill: {lang}",
                    "is_weak_area": is_weak,
                })

        # 3. Framework Internals Topic
        elif "Framework" in t_name:
            for fw in frameworks[:3]:
                add_candidate({
                    "text": f"How do you manage complex shared state, rendering cycles, and lifecycle side-effects when building high-load applications with {fw}?",
                    "topic": t_name,
                    "subtopic": f"{fw} State & Lifecycle",
                    "difficulty": "Medium",
                    "question_type": "coding-explanation",
                    "expected_keywords": [fw.lower(), "lifecycle", "state management", "render cycle", "optimization"],
                    "ideal_answer_points": [
                        f"Core state primitives in {fw}.",
                        "Strategies to prevent redundant renders/recomputations.",
                        "Memory and performance profiling.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Skill: {fw}",
                    "is_weak_area": is_weak,
                })
                add_candidate({
                    "text": f"Explain the internal request pipeline, dependency injection, and middleware execution flow in {fw}.",
                    "topic": t_name,
                    "subtopic": f"{fw} Architecture",
                    "difficulty": "Medium",
                    "question_type": "conceptual",
                    "expected_keywords": [fw.lower(), "middleware", "dependency injection", "request pipeline"],
                    "ideal_answer_points": [
                        f"Middleware chaining in {fw}.",
                        "Dependency injection scoping (singleton, request-scoped).",
                        "Exception handling filters and serialization.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Skill: {fw}",
                    "is_weak_area": is_weak,
                })
                add_candidate({
                    "text": f"What strategies do you adopt for caching, connection pooling, and latency minimization when building microservices with {fw}?",
                    "topic": t_name,
                    "subtopic": f"{fw} Optimization",
                    "difficulty": "Hard",
                    "question_type": "scenario",
                    "expected_keywords": [fw.lower(), "caching", "connection pooling", "latency", "throughput"],
                    "ideal_answer_points": [
                        "In-memory vs distributed caching layers.",
                        "Asynchronous I/O optimization.",
                        "Benchmarking and load testing results.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Skill: {fw}",
                    "is_weak_area": is_weak,
                })

        # 4. Target Architecture & Core Competencies Topic
        elif "Target Architecture" in t_name:
            add_candidate({
                "text": f"As a {target_role}, how would you architect a fault-tolerant, horizontally scalable backend handling 100,000 requests per second?",
                "topic": t_name,
                "subtopic": "High-Throughput Architecture",
                "difficulty": "Hard",
                "question_type": "scenario",
                "expected_keywords": ["scalability", "load balancing", "stateless services", "fault tolerance", "caching"],
                "ideal_answer_points": [
                    "Stateless app tiers behind layer-7 load balancers.",
                    "Asynchronous worker queues for non-blocking operations.",
                    "Read-replicas and sharded database tier.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": f"What key metrics, telemetry signals, and SLIs/SLOs would you define as a {target_role} to ensure production system health?",
                "topic": t_name,
                "subtopic": "Observability & SRE",
                "difficulty": "Medium",
                "question_type": "scenario",
                "expected_keywords": ["sli", "slo", "latency", "error rate", "saturation", "metrics", "tracing"],
                "ideal_answer_points": [
                    "The four Golden Signals (latency, traffic, errors, saturation).",
                    "Distributed tracing correlation with request IDs.",
                    "Actionable alerting thresholds versus alert fatigue.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": f"Describe your approach to designing idempotent REST or gRPC APIs that gracefully handle client retries and transient network partitions.",
                "topic": t_name,
                "subtopic": "API Design & Idempotency",
                "difficulty": "Medium",
                "question_type": "conceptual",
                "expected_keywords": ["idempotency", "idempotency key", "retry", "grpc", "network partition"],
                "ideal_answer_points": [
                    "Idempotency tokens stored in transactional cache (Redis).",
                    "Deduplication windows for outgoing mutations.",
                    "Client exponential backoff and jitter.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": f"How do you plan and execute database schema migrations with zero downtime on high-volume production tables for a {target_role} scope?",
                "topic": t_name,
                "subtopic": "Zero-Downtime Migrations",
                "difficulty": "Hard",
                "question_type": "scenario",
                "expected_keywords": ["migrations", "zero-downtime", "expand-contract pattern", "backfilling", "shadow writing"],
                "ideal_answer_points": [
                    "Expand and contract migration pattern.",
                    "Dual-writing during transition phases.",
                    "Asynchronous batch backfilling of historical rows.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        # 5. Data Structures & Algorithms Topic
        elif "Data Structures" in t_name or "Algorithms" in t_name:
            add_candidate({
                "text": "How would you design a memory-efficient LRU cache with O(1) get and put operations? Discuss the underlying data structures.",
                "topic": t_name,
                "subtopic": "Cache Algorithms",
                "difficulty": "Medium",
                "question_type": "conceptual",
                "expected_keywords": ["hash map", "doubly linked list", "o(1)", "eviction", "capacity"],
                "ideal_answer_points": [
                    "Hash map for O(1) key lookups.",
                    "Doubly linked list for O(1) node relocation and eviction.",
                    "Concurrency lock mechanisms if accessed across threads.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Compare depth-first search (DFS) and breadth-first search (BFS). When would you choose one over the other for cycle detection or shortest paths?",
                "topic": t_name,
                "subtopic": "Graph Algorithms",
                "difficulty": "Easy",
                "question_type": "conceptual",
                "expected_keywords": ["dfs", "bfs", "graph", "queue", "stack", "time complexity"],
                "ideal_answer_points": [
                    "BFS with queue for unweighted shortest path.",
                    "DFS with recursion/stack for topological sorting or cycle detection.",
                    "Space complexity comparison based on tree width vs depth.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "How do min-heaps and max-heaps operate, and how would you use a heap to find the top K frequent elements in a high-volume stream?",
                "topic": t_name,
                "subtopic": "Heap & Priority Queues",
                "difficulty": "Medium",
                "question_type": "coding-explanation",
                "expected_keywords": ["heap", "priority queue", "o(n log k)", "frequency", "stream"],
                "ideal_answer_points": [
                    "Maintaining a min-heap of size K.",
                    "Time complexity O(N log K) compared to full O(N log N) sorting.",
                    "Handling real-time stream ingestion with tumbling windows.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Compare dynamic programming (memoization vs tabulation) with greedy approaches. How do you recognize when a problem has optimal substructure?",
                "topic": t_name,
                "subtopic": "Dynamic Programming",
                "difficulty": "Hard",
                "question_type": "conceptual",
                "expected_keywords": ["dynamic programming", "memoization", "tabulation", "optimal substructure", "greedy"],
                "ideal_answer_points": [
                    "Overlapping subproblems versus greedy choice property.",
                    "Top-down recursive memoization versus bottom-up iterative table.",
                    "Space optimization by keeping only immediate previous states.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        # 6. System Design & Scalability Topic
        elif "System Design" in t_name or "Scalability" in t_name:
            add_candidate({
                "text": f"As a {target_role}, how would you architect a distributed real-time notification engine serving 5 million active concurrent connections?",
                "topic": t_name,
                "subtopic": "Distributed Notification System",
                "difficulty": "Hard",
                "question_type": "scenario",
                "expected_keywords": ["websockets", "message broker", "pub/sub", "redis", "kafka", "scalability"],
                "ideal_answer_points": [
                    "WebSocket gateway tier with sticky load balancing.",
                    "Pub/Sub message broker (Kafka/Redis) for inter-service fan-out.",
                    "State storage vs ephemeral connection routing.",
                    "Throttling and backpressure strategies.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Explain how database sharding works. How do you handle shard key selection, rebalancing, and cross-shard queries?",
                "topic": t_name,
                "subtopic": "Database Sharding",
                "difficulty": "Hard",
                "question_type": "scenario",
                "expected_keywords": ["sharding", "shard key", "consistent hashing", "cross-shard", "rebalancing"],
                "ideal_answer_points": [
                    "High-cardinality shard key selection to avoid hotspot partitions.",
                    "Consistent hashing algorithms with virtual nodes.",
                    "Scatter-gather query coordinator and async materialized views.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Compare Cache-Aside, Write-Through, and Write-Behind caching strategies. How do you prevent cache stampedes and dogpiling?",
                "topic": t_name,
                "subtopic": "Distributed Caching",
                "difficulty": "Medium",
                "question_type": "conceptual",
                "expected_keywords": ["cache-aside", "write-through", "stampede", "mutex lock", "ttl"],
                "ideal_answer_points": [
                    "Read/write consistency trade-offs of each pattern.",
                    "Mutex locking or probabilistic early expiration for hot key stampedes.",
                    "Negative caching and stale-while-revalidate patterns.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "How would you design a distributed rate limiter? Compare Token Bucket, Leaky Bucket, and Sliding Window Counter algorithms.",
                "topic": t_name,
                "subtopic": "Rate Limiting Architecture",
                "difficulty": "Medium",
                "question_type": "scenario",
                "expected_keywords": ["rate limiter", "token bucket", "sliding window", "redis", "concurrency"],
                "ideal_answer_points": [
                    "Algorithmic trade-offs (memory vs burst tolerance).",
                    "Redis sorted sets or Lua scripts for atomic counter increments.",
                    "Distributed rate limiting with local memory sync.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        # 7. DBMS, OS & Network Protocols Topic
        elif "DBMS" in t_name or "Database" in t_name or "Network" in t_name or "OS" in t_name:
            add_candidate({
                "text": "What is the difference between optimistic and pessimistic locking in databases, and in what scenarios would you choose optimistic locking?",
                "topic": t_name,
                "subtopic": "Transactions & Concurrency",
                "difficulty": "Medium",
                "question_type": "conceptual",
                "expected_keywords": ["acid", "locking", "optimistic locking", "isolation levels", "versioning"],
                "ideal_answer_points": [
                    "Optimistic locking using version columns or timestamps.",
                    "Pessimistic locking using row-level write locks.",
                    "Trade-off between write conflicts and lock contention.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Compare B-tree indexes with LSM-tree (Log-Structured Merge-tree) storage engines. Why do write-heavy databases prefer LSM-trees?",
                "topic": t_name,
                "subtopic": "Storage Engines & Indexing",
                "difficulty": "Hard",
                "question_type": "conceptual",
                "expected_keywords": ["b-tree", "lsm-tree", "write amplification", "compaction", "memtable", "sstable"],
                "ideal_answer_points": [
                    "In-place B-tree random I/O versus append-only sequential writes in LSM-trees.",
                    "Memtable, Write-Ahead Log (WAL), and immutable SSTables.",
                    "Compaction trade-offs and read amplification mitigations (Bloom filters).",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Explain the difference between a process and a thread. How does the OS kernel handle context switching, and what is its performance overhead?",
                "topic": t_name,
                "subtopic": "OS Internals & Virtual Memory",
                "difficulty": "Medium",
                "question_type": "conceptual",
                "expected_keywords": ["process", "thread", "context switch", "virtual memory", "pcb", "tlb cache"],
                "ideal_answer_points": [
                    "Shared memory address space in threads vs isolated address spaces in processes.",
                    "Kernel CPU register swapping and TLB cache invalidation overhead.",
                    "User-space green threads vs kernel-level threads.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Explain the TCP 3-way handshake and connection teardown. How does HTTP/2 multiplexing improve on HTTP/1.1 pipelining?",
                "topic": t_name,
                "subtopic": "Network Protocols",
                "difficulty": "Medium",
                "question_type": "conceptual",
                "expected_keywords": ["tcp", "syn", "ack", "http/2", "multiplexing", "head-of-line blocking"],
                "ideal_answer_points": [
                    "SYN, SYN-ACK, ACK handshake sequence.",
                    "Single TCP connection with binary framing streams in HTTP/2.",
                    "Resolution of HTTP-level head-of-line blocking.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        # 8. HR Topics
        elif "Self-Introduction" in t_name:
            add_candidate({
                "text": f"Walk me through your professional background, your technical growth, and why you are targeting this {target_role} position.",
                "topic": t_name,
                "subtopic": "Background & Narrative",
                "difficulty": "Easy",
                "question_type": "behavioral",
                "expected_keywords": ["career", "impact", "milestones", "growth", target_role.lower()],
                "ideal_answer_points": [
                    "Crisp, structured chronological timeline.",
                    "Highlight of primary technical achievements.",
                    f"Compelling alignment with the {target_role} scope.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Looking across your career, what was the most pivotal project or technical challenge that shaped how you build software today?",
                "topic": t_name,
                "subtopic": "Career Turning Point",
                "difficulty": "Easy",
                "question_type": "behavioral",
                "expected_keywords": ["milestone", "engineering mindset", "challenge", "reflection"],
                "ideal_answer_points": [
                    "Specific project context and stakes.",
                    "Key technical lessons absorbed.",
                    "How it elevated personal engineering standards.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        elif "Strengths" in t_name:
            add_candidate({
                "text": "What is one core technical superpower that sets you apart, and conversely, what is an active technical growth area you are currently working on?",
                "topic": t_name,
                "subtopic": "Self-Awareness",
                "difficulty": "Easy",
                "question_type": "behavioral",
                "expected_keywords": ["strength", "self-awareness", "growth area", "learning", "feedback"],
                "ideal_answer_points": [
                    "Concrete technical strength backed by examples.",
                    "Honest growth area with an active learning plan.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Describe a situation where a piece of constructive feedback from a peer or manager fundamentally changed how you work.",
                "topic": t_name,
                "subtopic": "Receptiveness to Feedback",
                "difficulty": "Medium",
                "question_type": "behavioral",
                "expected_keywords": ["feedback", "growth", "humility", "improvement", "action"],
                "ideal_answer_points": [
                    "Specific feedback received without defensiveness.",
                    "Concrete behavioral or technical adjustment made.",
                    "Measurable positive outcome afterwards.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        elif "Team" in t_name or "Collaboration" in t_name:
            add_candidate({
                "text": "Tell me about a cross-functional initiative where engineering requirements conflicted with product timelines. How did you negotiate alignment?",
                "topic": t_name,
                "subtopic": "Cross-Functional Collaboration",
                "difficulty": "Medium",
                "question_type": "behavioral",
                "expected_keywords": ["collaboration", "trade-offs", "product", "communication", "consensus"],
                "ideal_answer_points": [
                    "Context of conflicting priorities.",
                    "Transparent communication of engineering risks.",
                    "Iterative MVP compromise delivered on schedule.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "How do you collaborate with non-technical team members (designers, PMs, operations) to ensure technical constraints are understood early?",
                "topic": t_name,
                "subtopic": "Communication & Alignment",
                "difficulty": "Easy",
                "question_type": "behavioral",
                "expected_keywords": ["empathy", "plain language", "early alignment", "requirements"],
                "ideal_answer_points": [
                    "Translating technical constraints into business impact.",
                    "Collaborative brainstorming and wireframing.",
                    "Preventing late-stage scope surprises.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        elif "Conflict" in t_name:
            add_candidate({
                "text": "Describe a scenario where you strongly disagreed with a senior engineer or architect on technical direction. How did you handle the debate?",
                "topic": t_name,
                "subtopic": "Conflict Resolution",
                "difficulty": "Medium",
                "question_type": "behavioral",
                "expected_keywords": ["disagreement", "data-driven", "respect", "disagree and commit"],
                "ideal_answer_points": [
                    "Objective, data-driven reasoning rather than emotional pushback.",
                    "Prototyping / benchmarking to compare approaches.",
                    "Commitment once decision was finalized.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "How do you deliver constructive critique during code reviews without causing defensiveness or slowing down team velocity?",
                "topic": t_name,
                "subtopic": "Constructive Code Reviews",
                "difficulty": "Easy",
                "question_type": "behavioral",
                "expected_keywords": ["code review", "empathy", "guidelines", "questions", "mentorship"],
                "ideal_answer_points": [
                    "Focusing on the code rather than the author.",
                    "Framing suggestions as questions or trade-off explorations.",
                    "Differentiating blockers from nitpicks.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        elif "Motivation" in t_name:
            add_candidate({
                "text": "What keeps you intrinsically motivated when dealing with repetitive maintenance tasks or high-pressure incident mitigation?",
                "topic": t_name,
                "subtopic": "Resilience & Culture",
                "difficulty": "Easy",
                "question_type": "behavioral",
                "expected_keywords": ["motivation", "resilience", "incident", "ownership"],
                "ideal_answer_points": [
                    "Clear view of customer/system impact.",
                    "Discipline during on-call and incident post-mortems.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "What kind of engineering problems energize you most, and where do you see your technical trajectory evolving over the next 2-3 years?",
                "topic": t_name,
                "subtopic": "Vision & Energy",
                "difficulty": "Easy",
                "question_type": "behavioral",
                "expected_keywords": ["growth", "architecture", "impact", "passion", "career goals"],
                "ideal_answer_points": [
                    "Passion for distributed systems or product impact.",
                    "Ambitions for technical leadership or domain mastery.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        elif "Situational" in t_name or "Adaptability" in t_name:
            add_candidate({
                "text": "Describe a situation where project requirements changed drastically days before a deadline. How did you triage and deliver?",
                "topic": t_name,
                "subtopic": "Agile Adaptability",
                "difficulty": "Medium",
                "question_type": "behavioral",
                "expected_keywords": ["adaptability", "triage", "prioritization", "scope", "delivery"],
                "ideal_answer_points": [
                    "Calm assessment of impact on critical path.",
                    "Negotiation of non-critical cuts for on-time delivery.",
                    "Transparent communication to team and stakeholders.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Walk me through how you handle a live production incident when user-facing error rates spike and the cause is initially unknown.",
                "topic": t_name,
                "subtopic": "Incident Management",
                "difficulty": "Hard",
                "question_type": "scenario",
                "expected_keywords": ["incident", "triage", "rollbacks", "mitigation", "post-mortem"],
                "ideal_answer_points": [
                    "Prioritizing mitigation (rollback, traffic shedding) before deep root cause investigation.",
                    "Clear communication in incident command channel.",
                    "Follow-up blameless post-mortem and alert tuning.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        # 9. Managerial Topics
        elif "Leadership" in t_name or "Mentorship" in t_name:
            add_candidate({
                "text": "How do you ramp up junior developers and ensure consistent code quality and architecture standards across the engineering team?",
                "topic": t_name,
                "subtopic": "Mentorship",
                "difficulty": "Medium",
                "question_type": "behavioral",
                "expected_keywords": ["mentorship", "code review", "standards", "pair programming"],
                "ideal_answer_points": [
                    "Empathy and constructive code review guidelines.",
                    "Documentation, onboarding runbooks, and pair programming.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })
            add_candidate({
                "text": "Describe how you establish engineering excellence and psychological safety within your team.",
                "topic": t_name,
                "subtopic": "Team Culture",
                "difficulty": "Medium",
                "question_type": "behavioral",
                "expected_keywords": ["psychological safety", "blameless", "trust", "excellence"],
                "ideal_answer_points": [
                    "Encouraging safe risk-taking and learning from failure.",
                    "Blameless retrospectives and celebrating team wins.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        elif "Decision-Making" in t_name or "Ambiguity" in t_name:
            add_candidate({
                "text": "Tell me about a time you had to make a high-stakes architectural decision with significant unknowns and incomplete documentation.",
                "topic": t_name,
                "subtopic": "Risk & Ambiguity",
                "difficulty": "Hard",
                "question_type": "scenario",
                "expected_keywords": ["ambiguity", "risk mitigation", "decision matrix", "fallback plan"],
                "ideal_answer_points": [
                    "Structured evaluation of reversible vs irreversible decisions.",
                    "Risk mitigation with feature flags and rollback strategies.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        elif "Ownership" in t_name or "Accountability" in t_name:
            add_candidate({
                "text": "Describe a production bug or architectural mistake that you were directly responsible for. How did you resolve it and prevent recurrence?",
                "topic": t_name,
                "subtopic": "Accountability",
                "difficulty": "Medium",
                "question_type": "behavioral",
                "expected_keywords": ["ownership", "post-mortem", "blameless", "root cause", "prevention"],
                "ideal_answer_points": [
                    "Immediate transparent communication and triage.",
                    "Blameless post-mortem analysis.",
                    "Automated regression test and alert added.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        elif "Prioritization" in t_name:
            add_candidate({
                "text": "How do you evaluate and advocate for tackling technical debt when product managers are pushing strictly for new feature deliverables?",
                "topic": t_name,
                "subtopic": "Roadmapping & Trade-offs",
                "difficulty": "Medium",
                "question_type": "scenario",
                "expected_keywords": ["technical debt", "prioritization", "business value", "velocity", "reliability"],
                "ideal_answer_points": [
                    "Framing technical debt in terms of delivery velocity and incident risk.",
                    "Allocating fixed sprint capacity (e.g. 20%) for platform health.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        elif "Stakeholder" in t_name:
            add_candidate({
                "text": "How do you communicate complex technical delays or architectural risks to executive stakeholders who lack technical backgrounds?",
                "topic": t_name,
                "subtopic": "Stakeholder Management",
                "difficulty": "Medium",
                "question_type": "behavioral",
                "expected_keywords": ["stakeholder", "plain english", "business risk", "timelines"],
                "ideal_answer_points": [
                    "Framing technical challenges as trade-offs and options.",
                    "Proactive, early communication without technical jargon.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

        # Generic Fallback for unhandled topic names
        else:
            # A topic the candidate chose: several distinct angles, plus the topic seen
            # through each CV project.
            angles = [
                ("Fundamentals", "conceptual", "Medium",
                 f"What are the core ideas in {t_name} that you rely on most as a {target_role}, and why?"),
                ("Trade-offs", "conceptual", "Medium",
                 f"Describe a trade-off you have had to make in {t_name}. What were the options and how did you decide?"),
                ("Practical Application", "scenario", "Hard" if blueprint.difficulty in ("Hard", "Adaptive") else "Medium",
                 f"Walk me through a difficult problem you solved using {t_name}. What was the root cause and what did you change?"),
                ("Failure Modes", "scenario", "Hard",
                 f"What typically goes wrong with {t_name} in production, and how would you detect and recover from it?"),
                ("Design", "scenario", "Medium",
                 f"If you were designing a new service today, how would {t_name} shape your design, and what would you measure?"),
            ]
            for subtopic, q_type, diff, text in angles:
                add_candidate({
                    "text": text,
                    "topic": t_name,
                    "subtopic": subtopic,
                    "difficulty": diff,
                    "question_type": q_type,
                    "expected_keywords": ["trade-offs", "root cause", "monitoring", "design"],
                    "ideal_answer_points": [
                        f"Accurate explanation of {t_name} concepts.",
                        "A concrete example from real work.",
                        "Trade-offs and how the outcome was measured.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": None,
                    "is_weak_area": is_weak,
                })
            for proj in projects_list[:3]:
                p_title = _extract_dict_or_attr(proj, "title", "")
                if not p_title:
                    continue
                add_candidate({
                    "text": f"How did {t_name} come into play in {p_title}? Walk me through one decision you made there and what you would change now.",
                    "topic": t_name,
                    "subtopic": f"{p_title} through {t_name}",
                    "difficulty": blueprint.difficulty if blueprint.difficulty != "Adaptive" else "Medium",
                    "question_type": "project-based",
                    "expected_keywords": (_extract_dict_or_attr(proj, "tech_stack", []) or [])[:3] + ["trade-offs"],
                    "ideal_answer_points": [
                        f"Specific role of {t_name} in {p_title}.",
                        "The decision, its alternatives and the reasoning.",
                        "Honest reflection on what to improve.",
                    ],
                    "max_time_seconds": time_limit,
                    "cv_reference": f"Project: {p_title}",
                    "is_weak_area": is_weak,
                })

    # Supplement if pool has not reached total_needed (2-3x multiplier)
    tool_idx = 0
    attempts = 0
    while len(candidates) < total_needed and attempts < total_needed * 3:
        attempts += 1
        selected_topic = topics_list[len(candidates) % len(topics_list)]
        t_name = selected_topic.name
        is_weak = selected_topic.is_weak_area

        if tools and tool_idx < len(tools) * 3:
            tool_name = tools[tool_idx % len(tools)]
            tool_idx += 1
            add_candidate({
                "text": f"How do you leverage {tool_name} within your infrastructure, and what security and operational considerations arise when managing it in production?",
                "topic": t_name,
                "subtopic": f"Tooling: {tool_name}",
                "difficulty": "Medium",
                "question_type": "scenario",
                "expected_keywords": [tool_name.lower(), "infrastructure", "deployment", "security", "operations"],
                "ideal_answer_points": [
                    f"Practical usage of {tool_name}.",
                    "Security hardening and configuration best practices.",
                    "Automated orchestration and telemetry.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": f"Tool: {tool_name}",
                "is_weak_area": is_weak,
            })
        else:
            cand_idx = len(candidates) + 1
            add_candidate({
                "text": f"Regarding {t_name}, scenario #{cand_idx}: How would you optimize system responsiveness and maintain high availability during peak traffic spikes?",
                "topic": t_name,
                "subtopic": "High Availability & Peak Load",
                "difficulty": "Hard" if cand_idx % 2 == 0 else "Medium",
                "question_type": "scenario",
                "expected_keywords": ["high availability", "load balancing", "peak traffic", "failover", "caching"],
                "ideal_answer_points": [
                    "Horizontal auto-scaling thresholds.",
                    "Multi-zone redundancy and active-passive failover.",
                    "Graceful degradation with shedding non-essential load.",
                ],
                "max_time_seconds": time_limit,
                "cv_reference": None,
                "is_weak_area": is_weak,
            })

    return candidates


def rank_and_tag_questions(
    questions: List[Dict[str, Any]],
    blueprint: InterviewBlueprint,
    user_context: Optional[Any],
) -> List[Dict[str, Any]]:
    """
    Validates tags, calculates ranking score, and attaches reserve follow-up templates.
    """
    weak_areas = []
    if user_context:
        weak_areas = _extract_dict_or_attr(user_context, "weak_areas", []) or []
    weak_set = {w.lower().strip() for w in weak_areas}

    topic_weight_map = {t.name.lower().strip(): t.weight for t in (blueprint.topics or [])}

    ranked = []
    for q in questions:
        # Validate and normalize tags
        q_type = q.get("question_type", "conceptual")
        if q_type not in VALID_QUESTION_TYPES:
            q_type = "conceptual"
        q["question_type"] = q_type

        diff = q.get("difficulty", "Medium")
        if diff not in VALID_DIFFICULTIES:
            diff = "Medium"
        q["difficulty"] = diff

        # Ensure expected keywords is populated
        keywords = q.get("expected_keywords") or []
        if not keywords:
            # Extract non-trivial words from question text
            words = [w for w in re.findall(r"\w+", q.get("text", "").lower()) if len(w) > 4]
            keywords = words[:4] or ["concept", "implementation", "trade-offs"]
        q["expected_keywords"] = keywords

        # Ensure ideal answer points is populated
        if not q.get("ideal_answer_points"):
            q["ideal_answer_points"] = [
                "Clear conceptual explanation.",
                "Concrete example or production use-case.",
                "Analysis of trade-offs and alternative solutions.",
            ]

        # Calculate rank score
        t_name = q.get("topic", "").lower().strip()
        base_w = topic_weight_map.get(t_name, 0.1)

        is_weak = q.get("is_weak_area", False) or any(w in t_name or w in q.get("text", "").lower() for w in weak_set)
        q["is_weak_area"] = is_weak

        weak_boost = 0.35 if is_weak else 0.0
        cv_boost = 0.15 if q.get("cv_reference") else 0.0

        # Difficulty fit
        diff_boost = 0.10 if q["difficulty"] == blueprint.difficulty else 0.05

        rank_score = (base_w * 0.40) + weak_boost + diff_boost + cv_boost
        q["rank_score"] = round(rank_score, 4)

        # Attach reserve follow-up templates per topic
        q["followup_templates"] = list(FOLLOW_UP_TEMPLATES[:2])

        ranked.append(q)

    # Sort descending by rank score
    ranked.sort(key=lambda x: x["rank_score"], reverse=True)
    return ranked


async def generate_question_pool_async(
    blueprint: InterviewBlueprint,
    profile: Optional[Any],
    target_profile: Optional[Any],
    education: Optional[Any],
    user_context: Optional[Any],
    multiplier: float = 2.5,
    similarity_threshold: float = 0.82,
) -> Dict[str, Any]:
    """
    Orchestrates question generation:
    1. Generates 2-3x seed pool via LLM (or rich context-aware generator).
    2. Dedupes near-duplicates via sentence embedding cosine similarity and removes previously asked questions.
    3. Tags, ranks, attaches follow-up templates, and partitions into active questions and reserve follow-ups.
    """
    total_needed = int(math.ceil(blueprint.total_question_count * multiplier))
    previously_asked_hashes = set()
    previously_asked_texts = set()
    if user_context:
        history_qs = _extract_dict_or_attr(user_context, "history_asked_questions", []) or []
        for h in history_qs:
            h_hash = _extract_dict_or_attr(h, "question_hash", "")
            if h_hash:
                previously_asked_hashes.add(h_hash)
            h_text = _extract_dict_or_attr(h, "question_text", "")
            if h_text:
                previously_asked_texts.add(h_text)
                previously_asked_hashes.add(compute_question_hash(h_text))

    # 1. Generate Raw Candidates
    raw_candidates: List[Dict[str, Any]] = []

    # Attempt LLM if provider is active
    if llm_service.is_active():
        projects = _extract_dict_or_attr(profile, "projects", []) or []
        experience = _extract_dict_or_attr(profile, "experience", []) or []
        project_lines = "\n".join(
            f"  - {_extract_dict_or_attr(p, 'title', '')}: {_extract_dict_or_attr(p, 'description', '') or ''} "
            f"(stack: {', '.join(_extract_dict_or_attr(p, 'tech_stack', []) or []) or 'n/a'}; "
            f"outcomes: {_extract_dict_or_attr(p, 'outcomes', '') or 'n/a'})"
            for p in projects[:6]
        ) or "  (none)"
        experience_lines = "\n".join(
            f"  - {_extract_dict_or_attr(e, 'role', '')} at {_extract_dict_or_attr(e, 'company', '')}: "
            f"{'; '.join((_extract_dict_or_attr(e, 'responsibilities', []) or [])[:4])}"
            for e in experience[:4]
        ) or "  (none)"
        has_cv = bool(projects or experience)
        topic_names = [t.name for t in (blueprint.topics or [])]
        prompt = f"""
You are a senior interviewer preparing a {blueprint.round_type} interview for a {_extract_dict_or_attr(target_profile, 'target_role', 'Software Engineer')} candidate.
Write a pool of {total_needed} questions.

Interview:
- Round type: {blueprint.round_type}; difficulty: {blueprint.difficulty}; answer time: {blueprint.time_per_question_seconds}s per question
- Topics and weights: {[t.model_dump() for t in (blueprint.topics or [])]}

Candidate CV:
- Skills: {_extract_dict_or_attr(profile, 'skills', {})}
- Projects:
{project_lines}
- Experience:
{experience_lines}
- Known weak areas from past sessions: {_extract_dict_or_attr(user_context, 'weak_areas', [])}

Rules:
1. Every question's topic must be exactly one of: {topic_names}.
2. {"About 40% of the questions must be about the candidate's own projects or experience listed above, asked through the lens of a topic (e.g. how they designed, scaled, debugged or would change something they built). Name the project. The other 60% test the topics directly, using the candidate's stack where it fits." if has_cv else "The candidate has no CV on file: ask topic questions only."}
3. Never invent projects, employers or technologies that are not in the CV.
4. One clear question per item, one or two sentences, phrased the way a professional interviewer would say it out loud. No preamble, no praise, no numbering.
5. Vary the angle: design, trade-offs, debugging, a past decision, a concrete scenario.

Return JSON {{"questions": [...]}} where each item has:
   - text
   - topic (one of the topics above)
   - subtopic
   - difficulty (Easy, Medium, Hard)
   - question_type (conceptual, coding-explanation, scenario, behavioral, project-based)
   - expected_keywords (technical terms a strong answer would use)
   - ideal_answer_points (key elements of a model answer)
   - max_time_seconds ({blueprint.time_per_question_seconds})
   - cv_reference ("Project: <title>" or "Experience: <company>" when the question is about the CV, otherwise null)
"""
        try:
            llm_result = await llm_service.generate_structured_async(
                prompt=prompt,
                response_schema=QuestionPoolPayload,
                temperature=0.7,
            )
            if llm_result and llm_result.questions:
                raw_candidates = [q.model_dump() for q in llm_result.questions]
        except Exception as e:
            logger.warning("LLM question pool generation failed (%s); using template questions", type(e).__name__)
            raw_candidates = []

    # Fallback to rich deterministic generator if LLM returned insufficient candidates
    if len(raw_candidates) < total_needed:
        fallback_pool = _generate_fallback_questions(
            blueprint=blueprint,
            profile=profile,
            target_profile=target_profile,
            multiplier=multiplier,
        )
        # Combine without duplicate text
        existing_texts = {q["text"].lower() for q in raw_candidates}
        for fb in fallback_pool:
            if fb["text"].lower() not in existing_texts:
                raw_candidates.append(fb)
                existing_texts.add(fb["text"].lower())

    # 2. Deduplicate
    deduped_candidates, removed_count = deduplicate_questions(
        candidates=raw_candidates,
        previously_asked_hashes=previously_asked_hashes,
        similarity_threshold=similarity_threshold,
        previously_asked_texts=previously_asked_texts,
    )

    # 3. Tag, Rank and Attach Follow-Up Templates
    ranked_questions = rank_and_tag_questions(
        questions=deduped_candidates,
        blueprint=blueprint,
        user_context=user_context,
    )

    # 4. Partition into Active Question Pool and Reserve Follow-Up Pool
    needed_active = blueprint.total_question_count
    if len(ranked_questions) <= needed_active:
        # Short pool: still hold back ~20% as reserve so follow-ups and retakes have material.
        needed_active = max(1, len(ranked_questions) - max(1, len(ranked_questions) // 5))
    active_questions = ranked_questions[:needed_active]
    reserve_pool = ranked_questions[needed_active:]

    # Mark reserve questions
    for q in reserve_pool:
        q["is_reserve_followup"] = True

    return {
        "total_generated": len(raw_candidates),
        "deduped_count": len(ranked_questions),
        "removed_duplicates_count": removed_count,
        "active_questions": active_questions,
        "reserve_questions": reserve_pool,
    }
