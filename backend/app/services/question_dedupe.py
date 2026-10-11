import re
import math
import hashlib
from typing import List, Dict, Any, Set, Tuple


def normalize_question_text(text: str) -> str:
    """
    Normalizes text for consistent hashing and comparison.
    """
    cleaned = re.sub(r"[^\w\s]", "", text.lower())
    return " ".join(cleaned.split())


def compute_question_hash(text: str) -> str:
    """
    Produces deterministic 16-character SHA-256 fingerprint for question text.
    """
    norm = normalize_question_text(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _build_sentence_vector(text: str, vocabulary: Dict[str, int]) -> List[float]:
    """
    Builds a term-frequency vector with sub-word / character 3-gram weighting
    for robust semantic overlap detection.
    """
    norm = normalize_question_text(text)
    words = norm.split()
    vec = [0.0] * len(vocabulary)

    # Word frequencies
    for w in words:
        if w in vocabulary:
            vec[vocabulary[w]] += 1.0

    # Character 3-grams for morphological similarity
    for i in range(len(norm) - 2):
        gram = norm[i : i + 3]
        if gram in vocabulary:
            vec[vocabulary[gram]] += 0.5

    # L2 normalize
    norm_val = math.sqrt(sum(x * x for x in vec))
    if norm_val > 0:
        vec = [x / norm_val for x in vec]
    return vec


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(vec1, vec2))
    return max(0.0, min(1.0, dot))


def deduplicate_questions(
    candidates: List[Dict[str, Any]],
    previously_asked_hashes: Set[str],
    similarity_threshold: float = 0.82,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Dedupes a candidate question pool:
    1. Removes any question whose hash matches the user's AskedQuestion history.
    2. Removes near-duplicate questions within the pool using sentence embedding cosine similarity.

    Returns:
        (deduped_questions, total_removed_count)
    """
    # Step 1: Filter against historical asked questions
    history_filtered = []
    removed_history_count = 0

    for q in candidates:
        q_hash = q.get("question_hash") or compute_question_hash(q.get("text", ""))
        q["question_hash"] = q_hash

        if q_hash in previously_asked_hashes:
            removed_history_count += 1
            continue
        history_filtered.append(q)

    if not history_filtered:
        return [], removed_history_count

    # Step 2: Build vocabulary across candidate texts for embedding vectorization
    vocab: Dict[str, int] = {}
    for q in history_filtered:
        norm = normalize_question_text(q.get("text", ""))
        for w in norm.split():
            if w not in vocab:
                vocab[w] = len(vocab)
        for i in range(len(norm) - 2):
            gram = norm[i : i + 3]
            if gram not in vocab:
                vocab[gram] = len(vocab)

    # Compute vectors
    vectors = [_build_sentence_vector(q.get("text", ""), vocab) for q in history_filtered]

    # Step 3: Sequential greedy deduplication
    accepted: List[Dict[str, Any]] = []
    accepted_vectors: List[List[float]] = []
    duplicate_count = 0

    for q, vec in zip(history_filtered, vectors):
        is_duplicate = False
        for acc_vec in accepted_vectors:
            sim = _cosine_similarity(vec, acc_vec)
            if sim >= similarity_threshold:
                is_duplicate = True
                duplicate_count += 1
                break

        if not is_duplicate:
            accepted.append(q)
            accepted_vectors.append(vec)

    total_removed = removed_history_count + duplicate_count
    return accepted, total_removed
