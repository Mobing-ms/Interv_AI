from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text, JSON, Index
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
    consents = relationship("UserConsent", back_populates="user", cascade="all, delete-orphan", order_by="desc(UserConsent.accepted_at)")
    sessions = relationship("InterviewSession", back_populates="user", cascade="all, delete-orphan", order_by="desc(InterviewSession.created_at)")
    session_results = relationship("SessionResult", back_populates="user", cascade="all, delete-orphan", order_by="desc(SessionResult.created_at)")
    session_reports = relationship("SessionReport", back_populates="user", cascade="all, delete-orphan", order_by="desc(SessionReport.created_at)")


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
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    is_guest = Column(Boolean, default=False, nullable=False, index=True)
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
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    is_guest = Column(Boolean, default=False, nullable=False, index=True)
    round_type = Column(String(50), nullable=False)  # Technical, HR, Managerial, Mixed
    difficulty = Column(String(50), nullable=False)  # Easy, Medium, Hard, Adaptive
    duration_minutes = Column(Integer, nullable=False)  # 15, 30, 45, etc.
    language = Column(String(50), default="English", nullable=False)
    mode = Column(String(50), default="normal", nullable=False)  # normal, pressure
    focus_topics = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="interview_configs")
    questions = relationship("QuestionBankItem", back_populates="interview_config", cascade="all, delete-orphan", order_by="desc(QuestionBankItem.rank_score)")
    sessions = relationship("InterviewSession", back_populates="interview_config", cascade="all, delete-orphan", order_by="desc(InterviewSession.created_at)")


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


class UserConsent(Base):
    __tablename__ = "user_consents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    is_guest = Column(Boolean, default=False, nullable=False, index=True)
    guest_id = Column(String(100), nullable=True, index=True)
    version = Column(String(50), default="v1.0", nullable=False)
    retention_days = Column(Integer, default=30, nullable=False)
    accepted = Column(Boolean, default=True, nullable=False)
    can_delete = Column(Boolean, default=True, nullable=False)
    accepted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="consents")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    is_guest = Column(Boolean, default=False, nullable=False, index=True)
    guest_id = Column(String(100), nullable=True, index=True)
    interview_id = Column(Integer, ForeignKey("interview_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), default="created", nullable=False)  # created, active, completed, aborted, CLOSED
    session_token = Column(String(255), unique=True, index=True, nullable=False)
    audio_file_key = Column(String(500), nullable=True)
    video_file_key = Column(String(500), nullable=True)
    aligned_data_key = Column(String(500), nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="sessions")
    interview_config = relationship("InterviewConfig", back_populates="sessions")
    calibration = relationship("SessionCalibration", back_populates="session", uselist=False, cascade="all, delete-orphan")
    signals = relationship("SignalTimeSeries", back_populates="session", cascade="all, delete-orphan")
    integrity_events = relationship("IntegrityEvent", back_populates="session", cascade="all, delete-orphan")
    analysis_job = relationship("SessionAnalysisJob", back_populates="session", uselist=False, cascade="all, delete-orphan")
    result = relationship("SessionResult", back_populates="session", uselist=False, cascade="all, delete-orphan")
    report = relationship("SessionReport", back_populates="session", uselist=False, cascade="all, delete-orphan")


class SessionCalibration(Base):
    __tablename__ = "session_calibrations"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    face_baseline = Column(JSON, default=dict, nullable=False)   # {"neutral_score": float, "gaze_center": {"x": float, "y": float}, "head_pose": {"pitch": float, "yaw": float, "roll": float}}
    voice_baseline = Column(JSON, default=dict, nullable=False)  # {"average_volume_db": float, "pitch_range_hz": [float, float]}
    background_noise_level_db = Column(Float, default=-50.0, nullable=False)
    calibration_text = Column(String(500), nullable=True)
    calibrated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    session = relationship("InterviewSession", back_populates="calibration")
    user = relationship("User")


class SignalTimeSeries(Base):
    __tablename__ = "signal_time_series"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, nullable=False, index=True)
    timestamp = Column(Float, nullable=False, index=True)
    metric = Column(String(64), nullable=False, index=True)
    value = Column(Float, nullable=False)
    extra_data = Column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_signal_sess_q_ts", "session_id", "question_id", "timestamp"),
        Index("ix_signal_sess_metric", "session_id", "metric"),
    )

    session = relationship("InterviewSession", back_populates="signals")


class IntegrityEvent(Base):
    __tablename__ = "integrity_events"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, nullable=True, index=True)
    type = Column(String(64), nullable=False, index=True)  # tab_switch, window_blur, fullscreen_exit, clipboard_copy, clipboard_paste, multiple_faces, face_missing
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=True)
    duration_seconds = Column(Float, default=0.0, nullable=False)
    severity = Column(String(20), default="MEDIUM", nullable=False)  # LOW, MEDIUM, HIGH
    details = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    session = relationship("InterviewSession", back_populates="integrity_events")


class SessionAnalysisJob(Base):
    __tablename__ = "session_analysis_jobs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    job_id = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(50), default="pending", nullable=False)  # pending, processing, completed, partial, failed
    progress = Column(Integer, default=0, nullable=False)
    current_step = Column(String(100), default="queued", nullable=False)
    is_partial = Column(Boolean, default=False, nullable=False)
    missing_sections = Column(JSON, default=list, nullable=False)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    aligned_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    session = relationship("InterviewSession", back_populates="analysis_job")


class SessionResult(Base):
    __tablename__ = "session_results"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    is_guest = Column(Boolean, default=False, nullable=False, index=True)
    round_type = Column(String(50), nullable=False)
    role = Column(String(150), nullable=True)
    overall_score = Column(Float, nullable=False)
    content_score = Column(Float, nullable=False)
    speech_score = Column(Float, nullable=False)
    face_score = Column(Float, nullable=False)
    classification = Column(String(50), nullable=False)  # STRONG, AVERAGE, WEAK
    weights_used = Column(JSON, nullable=False)
    per_question_scores = Column(JSON, nullable=False)
    comparisons = Column(JSON, nullable=False)
    weak_areas = Column(JSON, nullable=False)
    strengths = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    session = relationship("InterviewSession", back_populates="result")
    user = relationship("User", back_populates="session_results")


class SessionReport(Base):
    __tablename__ = "session_reports"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    is_guest = Column(Boolean, default=False, nullable=False, index=True)
    report_data = Column(JSON, nullable=False)
    is_grounded = Column(Boolean, default=True, nullable=False)
    grounding_stats = Column(JSON, nullable=False)
    regeneration_rounds = Column(Integer, default=0, nullable=False)
    dropped_claims_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    session = relationship("InterviewSession", back_populates="report")
    user = relationship("User", back_populates="session_reports")


class GuestIpLog(Base):
    __tablename__ = "guest_ip_logs"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(64), index=True, nullable=False)
    session_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)







