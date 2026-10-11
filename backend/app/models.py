from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    auth_provider = Column(String(50), default="local", nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    onboarding_status = Column(String(50), default="not_started", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    education_profile = relationship("EducationProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    target_profile = relationship("TargetProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    cv_documents = relationship("CVDocument", back_populates="user", cascade="all, delete-orphan", order_by="desc(CVDocument.created_at)")
    profiles = relationship("Profile", back_populates="user", cascade="all, delete-orphan", order_by="desc(Profile.version)")
    interview_configs = relationship("InterviewConfig", back_populates="user", cascade="all, delete-orphan", order_by="desc(InterviewConfig.created_at)")
    memory = relationship("UserMemory", back_populates="user", uselist=False, cascade="all, delete-orphan")
    asked_questions = relationship("AskedQuestion", back_populates="user", cascade="all, delete-orphan", order_by="desc(AskedQuestion.asked_at)")


class EmailOTP(Base):
    __tablename__ = "email_otps"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True, nullable=False)
    otp = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class EducationProfile(Base):
    __tablename__ = "education_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    degree = Column(String(100), nullable=False)
    branch = Column(String(100), nullable=False)
    college = Column(String(255), nullable=False)
    graduation_year = Column(Integer, nullable=False)
    cgpa = Column(Float, nullable=True)
    cgpa_scale = Column(Float, default=10.0, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="education_profile")


class TargetProfile(Base):
    __tablename__ = "target_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    target_role = Column(String(150), nullable=False)
    company_type = Column(String(50), nullable=False)
    experience_level = Column(String(50), nullable=False)
    job_description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="target_profile")


class CVDocument(Base):
    __tablename__ = "cv_documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    file_key = Column(String(255), nullable=False, unique=True, index=True)
    filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=False)
    status = Column(String(50), default="uploaded", nullable=False)  # uploaded, extracting, extracted, failed
    raw_text = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=True)  # UNSUPPORTED_TYPE, TOO_LARGE, UNREADABLE, ENCRYPTED
    error_message = Column(Text, nullable=True)
    structured_data = Column(JSON, nullable=True)
    cross_check_flags = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    extracted_at = Column(DateTime, nullable=True)
    parsed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="cv_documents")


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    structured_data = Column(JSON, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    cv_document_id = Column(Integer, ForeignKey("cv_documents.id", ondelete="SET NULL"), nullable=True)
    confirmed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="profiles")
    cv_document = relationship("CVDocument")


class InterviewConfig(Base):
    __tablename__ = "interview_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    round_type = Column(String(50), nullable=False)  # Technical, HR, Managerial, Mixed
    difficulty = Column(String(50), nullable=False)  # Easy, Medium, Hard, Adaptive
    duration_minutes = Column(Integer, nullable=False)  # 15, 30, 45, etc.
    language = Column(String(50), default="English", nullable=False)
    mode = Column(String(50), default="normal", nullable=False)  # normal, pressure
    focus_topics = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="interview_configs")
    questions = relationship("QuestionBankItem", back_populates="interview_config", cascade="all, delete-orphan", order_by="desc(QuestionBankItem.rank_score)")


class UserMemory(Base):
    __tablename__ = "user_memories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    topic_scores = Column(JSON, default=dict, nullable=False)  # {"React architecture": 68.0, ...}
    weak_topics = Column(JSON, default=list, nullable=False)   # ["React architecture", "Clarity"]
    session_count = Column(Integer, default=0, nullable=False)
    last_session_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="memory")


class AskedQuestion(Base):
    __tablename__ = "asked_questions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_hash = Column(String(64), nullable=False, index=True)
    topic = Column(String(100), nullable=False, index=True)
    question_text = Column(Text, nullable=True)
    asked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    score = Column(Float, nullable=True)

    user = relationship("User", back_populates="asked_questions")


class QuestionBankItem(Base):
    __tablename__ = "question_bank_items"

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(Integer, ForeignKey("interview_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    question_hash = Column(String(64), nullable=False, index=True)
    text = Column(Text, nullable=False)
    topic = Column(String(100), nullable=False, index=True)
    subtopic = Column(String(100), nullable=True)
    difficulty = Column(String(50), nullable=False)  # Easy, Medium, Hard, Adaptive
    question_type = Column(String(50), nullable=False)  # conceptual, coding-explanation, scenario, behavioral, project-based
    expected_keywords = Column(JSON, default=list, nullable=False)
    ideal_answer_points = Column(JSON, default=list, nullable=False)
    max_time_seconds = Column(Integer, default=120, nullable=False)
    cv_reference = Column(String(255), nullable=True)
    is_weak_area = Column(Boolean, default=False, nullable=False)
    rank_score = Column(Float, default=0.0, nullable=False)
    is_reserve_followup = Column(Boolean, default=False, nullable=False)
    followup_templates = Column(JSON, default=list, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    interview_config = relationship("InterviewConfig", back_populates="questions")



