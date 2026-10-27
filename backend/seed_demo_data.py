"""
Demo Data Seeder (IntervAI Platform).
Populates realistic candidate profile, 3 completed historical sessions
across Technical, Behavioral/HR, and Managerial rounds with fused scores,
grounded reports, radar skill breakdowns, trend timelines, and ranked weak areas.

Usage:
    python seed_demo_data.py [email] [password]
Default credentials:
    Email: alex@example.com
    Password: Password123!
"""

import sys
import os
import json
import time
import secrets
import hashlib
from datetime import datetime, timezone, timedelta

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, Base, engine
from app.models import (
    User,
    EducationProfile,
    TargetProfile,
    Profile,
    InterviewConfig,
    InterviewSession,
    SessionCalibration,
    SessionResult,
    SessionReport,
    UserMemory,
    AskedQuestion,
    UserConsent,
)
from app.auth import hash_password
from app.services.answer_capture_service import default_storage_manager
from app.services.improvement_plan_service import build_improvement_plan
from app.services.report_generator_service import generate_grounded_report_with_recovery

from run_migrations import run_database_migrations
run_database_migrations()


def seed_demo_candidate(
    email: str = "alex@example.com",
    name: str = "Alex Morgan",
    password: str = "Password123!",
):
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        print(f"\n=======================================================")
        print(f"[IntervAI Seed] Seeding demo data for: {email}")
        print(f"=======================================================\n")

        # 1. Upsert Candidate User
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                name=name,
                email=email,
                password_hash=hash_password(password),
                auth_provider="local",
                is_verified=True,
                onboarding_status="profile_confirmed",
                created_at=now - timedelta(days=21),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"  [+] Created user: {user.name} (id={user.id})")
        else:
            user.name = name
            user.password_hash = hash_password(password)
            user.is_verified = True
            user.onboarding_status = "profile_confirmed"
            db.commit()
            print(f"  [*] Updated existing user: {user.name} (id={user.id})")

        user_id = user.id

        # 2. Consent
        consent = db.query(UserConsent).filter(UserConsent.user_id == user_id).first()
        if not consent:
            consent = UserConsent(
                user_id=user_id,
                version="1.0",
                retention_days=30,
                accepted=True,
                can_delete=True,
                accepted_at=now - timedelta(days=20),
            )
            db.add(consent)

        # 3. Education Profile
        edu = db.query(EducationProfile).filter(EducationProfile.user_id == user_id).first()
        if not edu:
            edu = EducationProfile(
                user_id=user_id,
                degree="Bachelor of Science",
                branch="Computer Science & Engineering",
                college="Stanford University",
                graduation_year=2023,
                cgpa=3.92,
                cgpa_scale=4.0,
                created_at=now - timedelta(days=20),
                updated_at=now - timedelta(days=20),
            )
            db.add(edu)

        # 4. Target Profile
        target = db.query(TargetProfile).filter(TargetProfile.user_id == user_id).first()
        if not target:
            target = TargetProfile(
                user_id=user_id,
                target_role="Senior Full-Stack Engineer",
                company_type="Product",
                experience_level="2-5",
                job_description="Architect scalable cloud microservices, high-performance web applications, and resilient distributed databases.",
                created_at=now - timedelta(days=20),
                updated_at=now - timedelta(days=20),
            )
            db.add(target)

        # 5. Canonical Profile
        canonical = db.query(Profile).filter(Profile.user_id == user_id).first()
        if not canonical:
            structured_cv = {
                "name": name,
                "email": email,
                "phone": "+1 (555) 321-9876",
                "links": ["https://github.com/alexmorgan", "https://linkedin.com/in/alexmorgan"],
                "summary": "Full-Stack Software Engineer with 4 years of experience building distributed systems and reactive frontends.",
                "skills": [
                    "TypeScript", "React", "Node.js", "Python", "Go", "Redis",
                    "PostgreSQL", "Kafka", "Docker", "Kubernetes", "AWS", "GraphQL"
                ],
                "experience": [
                    {
                        "role": "Software Engineer II",
                        "company": "Stripe",
                        "duration": "2023 - Present",
                        "highlights": [
                            "Engineered real-time payment reconciliation pipeline handling 15,000 TPS.",
                            "Optimized Redis distributed caching layer reducing latency by 42%."
                        ]
                    },
                    {
                        "role": "Frontend Engineer",
                        "company": "Vercel",
                        "duration": "2021 - 2023",
                        "highlights": [
                            "Built Next.js analytics dashboard with sub-second page loads.",
                            "Maintained core open-source UI component library."
                        ]
                    }
                ],
                "education": [
                    {
                        "degree": "Bachelor of Science in Computer Science",
                        "college": "Stanford University",
                        "graduation_year": 2023,
                        "cgpa": 3.92
                    }
                ]
            }
            canonical = Profile(
                user_id=user_id,
                structured_data=structured_cv,
                version=1,
                confirmed_at=now - timedelta(days=20),
                created_at=now - timedelta(days=20),
            )
            db.add(canonical)

        db.commit()

        # 6. Seed 3 Historical Completed Sessions
        sessions_seed_specs = [
            {
                "round_type": "Technical",
                "difficulty": "Medium",
                "days_ago": 14,
                "overall": 82.5,
                "content": 86.0,
                "speech": 78.0,
                "face": 81.0,
                "classification": "STRONG",
                "weak_areas": [
                    {"topic": "SQL Indexing & Lock Contention", "score": 68.0, "reason": "Did not analyze write amplification and lock escalation under multi-table joins."},
                    {"topic": "Clarity & Trade-offs", "score": 72.0, "reason": "Theoretical explanation omitted hardware capacity bounds."},
                ],
                "questions": [
                    ("How does Redis handle master-replica data synchronization and failover under network partitions?", "Distributed Systems", 88.0),
                    ("Explain the mechanics of B-Tree versus LSM-Tree storage engines for write-intensive database workloads.", "SQL Indexing & Lock Contention", 68.0),
                    ("How do you architect end-to-end WebSocket connection resilience with horizontal load balancers?", "System Architecture", 86.5),
                    ("Walk me through optimizing React 19 server components for high-throughput streaming dashboards.", "Frontend Architecture", 87.5),
                ],
            },
            {
                "round_type": "HR",
                "difficulty": "Medium",
                "days_ago": 7,
                "overall": 88.4,
                "content": 84.0,
                "speech": 92.5,
                "face": 89.0,
                "classification": "STRONG",
                "weak_areas": [
                    {"topic": "Executive Stakeholder Alignment", "score": 74.0, "reason": "Focus heavily on technical details rather than business ROI impact."},
                ],
                "questions": [
                    ("Tell me about a time you resolved a major technical disagreement with a principal architect.", "Conflict Resolution", 90.0),
                    ("How do you prioritize mission-critical feature delivery versus long-term technical debt?", "Technical Prioritization", 86.0),
                    ("Describe how you onboarded and mentored junior software engineers in your previous role.", "Mentorship & Culture", 89.2),
                ],
            },
            {
                "round_type": "Managerial",
                "difficulty": "Hard",
                "days_ago": 2,
                "overall": 76.2,
                "content": 73.5,
                "speech": 80.0,
                "face": 77.0,
                "classification": "AVERAGE",
                "weak_areas": [
                    {"topic": "Microservices Migration & Blast Radius", "score": 64.0, "reason": "Underestimated operational overhead and data synchronization challenges during dual-write phase."},
                    {"topic": "Incident Post-Mortem & Blameless Culture", "score": 71.0, "reason": "Remediation plan lacked automated regression tests for database deadlocks."},
                ],
                "questions": [
                    ("How do you design a phased migration from a monolithic backend to microservices without downtime?", "Microservices Migration & Blast Radius", 64.0),
                    ("Walk me through facilitating a high-severity production outage retrospective.", "Incident Post-Mortem & Blameless Culture", 71.0),
                    ("How do you calibrate interview rubrics to maintain a high hiring bar across engineering teams?", "Engineering Leadership", 84.0),
                    ("How do you handle underperformance in a senior engineer while maintaining team morale?", "Team Management", 85.8),
                ],
            },
        ]

        total_questions_seeded = 0

        for spec in sessions_seed_specs:
            sess_time = now - timedelta(days=spec["days_ago"])
            
            # InterviewConfig
            cfg = InterviewConfig(
                user_id=user_id,
                round_type=spec["round_type"],
                difficulty=spec["difficulty"],
                duration_minutes=30,
                language="English",
                mode="normal",
                focus_topics=[q[1] for q in spec["questions"]],
                created_at=sess_time,
            )
            db.add(cfg)
            db.commit()
            db.refresh(cfg)

            # InterviewSession
            token_str = secrets.token_urlsafe(32)
            sess = InterviewSession(
                user_id=user_id,
                interview_id=cfg.id,
                status="CLOSED",
                session_token=token_str,
                started_at=sess_time,
                ended_at=sess_time + timedelta(minutes=28),
                audio_file_key=f"sessions/{cfg.id}/audio_merged.bin",
                video_file_key=f"sessions/{cfg.id}/video_manifest.json",
                created_at=sess_time,
            )
            db.add(sess)
            db.commit()
            db.refresh(sess)

            # Calibration
            cal = SessionCalibration(
                session_id=sess.id,
                user_id=user_id,
                face_baseline={"neutral_score": 0.94, "gaze_center": {"x": 0.5, "y": 0.5}},
                voice_baseline={"average_volume_db": -23.0, "speaking_rate_wpm": 136.0},
                background_noise_level_db=-51.0,
                calibrated_at=sess_time,
            )
            db.add(cal)

            # Per-question scores & AskedQuestions
            pq_scores = []
            for idx, (q_text, topic, q_score) in enumerate(spec["questions"], start=1):
                total_questions_seeded += 1
                q_id = total_questions_seeded
                pq_scores.append({
                    "question_id": q_id,
                    "topic": topic,
                    "fused_score": q_score,
                    "content_score": q_score,
                    "speech_score": spec["speech"],
                    "face_score": spec["face"],
                    "transcript": f"Candidate gave a thorough response addressing {topic} in detail.",
                    "word_count": 85,
                })

                # AskedQuestion history
                q_hash = hashlib.sha256(q_text.strip().lower().encode("utf-8")).hexdigest()
                asked = AskedQuestion(
                    user_id=user_id,
                    question_hash=q_hash,
                    topic=topic,
                    question_text=q_text,
                    score=q_score,
                    asked_at=sess_time + timedelta(minutes=idx * 5),
                )
                db.add(asked)

                # Artifact dummy storage
                try:
                    default_storage_manager.save_audio_chunk(sess.id, q_id, 1, b"\x00\x01\x02" * 128)
                    default_storage_manager.save_transcript(
                        session_id=sess.id,
                        question_id=q_id,
                        transcript_data={
                            "text": f"In-depth answer for {topic}: {q_text}",
                            "words": [{"word": w, "start": i * 0.3, "end": (i + 1) * 0.3} for i, w in enumerate(q_text.split())],
                        },
                    )
                except Exception:
                    pass

            # SessionResult
            res_dict = {
                "session_id": sess.id,
                "overall_score": spec["overall"],
                "content_score": spec["content"],
                "speech_score": spec["speech"],
                "face_score": spec["face"],
                "classification": spec["classification"],
                "round_type": spec["round_type"],
                "role": target.target_role,
                "per_question_scores": pq_scores,
                "weak_areas": spec["weak_areas"],
                "weights_used": {"content": 0.55, "speech": 0.25, "face": 0.20},
                "comparisons": {
                    "cohort": {"percentile": 78.5, "benchmark_label": f"Platform Cohort ({spec['round_type']})"},
                    "trend": {"summary": f"Consistent {spec['classification']} execution across communication and technical depth."},
                },
            }

            result_row = SessionResult(
                session_id=sess.id,
                user_id=user_id,
                round_type=spec["round_type"],
                role=target.target_role,
                overall_score=spec["overall"],
                content_score=spec["content"],
                speech_score=spec["speech"],
                face_score=spec["face"],
                classification=spec["classification"],
                weak_areas=spec["weak_areas"],
                weights_used=res_dict["weights_used"],
                per_question_scores=pq_scores,
                comparisons=res_dict["comparisons"],
                created_at=sess_time,
            )
            db.add(result_row)
            db.commit()

            # SessionReport (Grounded)
            report_dict = generate_grounded_report_with_recovery(res_dict)
            report_row = SessionReport(
                session_id=sess.id,
                user_id=user_id,
                is_guest=False,
                report_data=report_dict,
                is_grounded=True,
                grounding_stats=report_dict.get("grounding_audit", {}),
                regeneration_rounds=0,
                dropped_claims_count=0,
                created_at=sess_time,
            )
            db.add(report_row)
            db.commit()

            print(f"  [+] Seeded Session #{sess.id} ({spec['round_type']} - {spec['overall']:.1f}/100 - {spec['classification']})")

        # 7. Update UserMemory
        memory = db.query(UserMemory).filter(UserMemory.user_id == user_id).first()
        topic_scores = {
            "Distributed Systems": 88.0,
            "SQL Indexing & Lock Contention": 68.0,
            "System Architecture": 86.5,
            "Frontend Architecture": 87.5,
            "Conflict Resolution": 90.0,
            "Technical Prioritization": 86.0,
            "Mentorship & Culture": 89.2,
            "Microservices Migration & Blast Radius": 64.0,
            "Incident Post-Mortem & Blameless Culture": 71.0,
            "Engineering Leadership": 84.0,
            "Team Management": 85.8,
        }
        weak_topics = [
            "Microservices Migration & Blast Radius",
            "SQL Indexing & Lock Contention",
            "Incident Post-Mortem & Blameless Culture",
        ]

        if not memory:
            memory = UserMemory(
                user_id=user_id,
                topic_scores=topic_scores,
                weak_topics=weak_topics,
                session_count=3,
                last_session_at=now - timedelta(days=2),
                created_at=now,
                updated_at=now,
            )
            db.add(memory)
        else:
            memory.topic_scores = topic_scores
            memory.weak_topics = weak_topics
            memory.session_count = 3
            memory.last_session_at = now - timedelta(days=2)
            memory.updated_at = now

        db.commit()
        print(f"\n  [+] UserMemory updated with {len(topic_scores)} topic scores and top weak areas:")
        for wt in weak_topics:
            print(f"      - {wt} (avg: {topic_scores[wt]:.1f})")

        print(f"\n=======================================================")
        print(f"[SUCCESS] Demo data seeded successfully!")
        print(f"Login credentials:")
        print(f"  Email:    {email}")
        print(f"  Password: {password}")
        print(f"Dashboard will display 3 historical sessions, radar skill charts,")
        print(f"progress trends, grounded reports, and weak-area retake blueprints.")
        print(f"=======================================================\n")

    finally:
        db.close()


if __name__ == "__main__":
    target_email = sys.argv[1] if len(sys.argv) > 1 else "alex@example.com"
    target_pw = sys.argv[2] if len(sys.argv) > 2 else "Password123!"
    seed_demo_candidate(email=target_email, password=target_pw)
