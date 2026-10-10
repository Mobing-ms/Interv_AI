"""
Script to seed fake interview history for a user to test returning-user detection,
past topic scores, weak-area detection, and asked-question tracking.

Usage:
    python seed_user_history.py [optional_user_email]
"""

import sys
import os
import hashlib
from datetime import datetime, timezone, timedelta

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, Base, engine
from app.models import User, UserMemory, AskedQuestion
from app.auth import hash_password
from app.services.interview_context import load_user_context

Base.metadata.create_all(bind=engine)


def seed_history_for_user(email: str = "alex@intervai.dev"):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"User with email '{email}' not found. Creating test candidate...")
            user = User(
                name="Alex Candidate",
                email=email,
                password_hash=hash_password("Password123!"),
                auth_provider="local",
                is_verified=True,
                onboarding_status="profile_confirmed",
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        now = datetime.now(timezone.utc)
        two_days_ago = now - timedelta(days=2)

        # 1. Seed / Upsert UserMemory
        memory = db.query(UserMemory).filter(UserMemory.user_id == user.id).first()
        topic_scores = {
            "React architecture": 64.0,
            "State management": 58.0,
            "System design": 78.0,
            "Communication": 86.0,
            "Problem solving": 82.0,
            "Clarity & trade-offs": 60.0,
        }
        weak_topics = ["State management", "Clarity & trade-offs", "React architecture"]

        if not memory:
            memory = UserMemory(
                user_id=user.id,
                topic_scores=topic_scores,
                weak_topics=weak_topics,
                session_count=5,
                last_session_at=two_days_ago,
                created_at=now,
                updated_at=now,
            )
            db.add(memory)
        else:
            memory.topic_scores = topic_scores
            memory.weak_topics = weak_topics
            memory.session_count = max(memory.session_count, 5)
            memory.last_session_at = two_days_ago
            memory.updated_at = now

        # 2. Seed AskedQuestions history
        sample_questions = [
            (
                "Can you walk me through the trade-offs between Redux, Zustand, and React Context for large applications?",
                "State management",
                58.0,
                now - timedelta(days=2, hours=3),
            ),
            (
                "How do you profile and prevent unnecessary re-renders in deeply nested React component trees?",
                "React architecture",
                65.0,
                now - timedelta(days=2, hours=2),
            ),
            (
                "How would you design a distributed rate limiter that handles 100,000 requests per second?",
                "System design",
                80.0,
                now - timedelta(days=4),
            ),
            (
                "Tell me about a time you had a fundamental technical disagreement with senior leadership. How did you resolve it?",
                "Communication",
                89.0,
                now - timedelta(days=6),
            ),
            (
                "Describe your step-by-step framework for debugging a silent memory leak in a Node/Python microservice.",
                "Problem solving",
                82.0,
                now - timedelta(days=8),
            ),
        ]

        seeded_count = 0
        for text, topic, score, asked_time in sample_questions:
            q_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            exists = (
                db.query(AskedQuestion)
                .filter(AskedQuestion.user_id == user.id, AskedQuestion.question_hash == q_hash)
                .first()
            )
            if not exists:
                db.add(
                    AskedQuestion(
                        user_id=user.id,
                        question_hash=q_hash,
                        topic=topic,
                        question_text=text,
                        score=score,
                        asked_at=asked_time,
                    )
                )
                seeded_count += 1

        db.commit()

        # 3. Verify via service
        ctx = load_user_context(user.id, db)
        print("==================================================================")
        print(f"SUCCESS: Seeded interview history for '{user.email}' (User ID: {user.id})")
        print("==================================================================")
        print(f" - Returning Candidate Status : {ctx.is_returning}")
        print(f" - Total Sessions Completed   : {ctx.session_count}")
        print(f" - Last Session Timestamp     : {ctx.last_session_at}")
        print(f" - Identified Weak Areas      : {ctx.weak_areas}")
        print(f" - Topic Scores Loaded        : {ctx.past_scores}")
        print(f" - Prior Asked Questions      : {len(ctx.history_asked_questions)} questions tracked")
        print(f" - Baseline Weights (Tuned)   : {ctx.baseline_weights}")
        print(f" - Recommended Starting Diff  : {ctx.recommended_difficulty}")
        print("==================================================================")
        return user.id

    finally:
        db.close()


if __name__ == "__main__":
    target_email = sys.argv[1] if len(sys.argv) > 1 else "alex@intervai.dev"
    seed_history_for_user(target_email)
