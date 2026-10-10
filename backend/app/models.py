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

