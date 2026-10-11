from datetime import datetime
from enum import Enum
from typing import Optional, List, Union, Any, Dict
from pydantic import BaseModel, EmailStr, Field, model_validator, ConfigDict


class UserSignUp(BaseModel):
    name: str = Field(..., min_length=1, description="Full name of user")
    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(..., min_length=8, description="Password of at least 8 characters")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    credential: Optional[str] = None
    token: Optional[str] = None
    id_token: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None


class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerify(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    auth_provider: str
    is_verified: bool
    onboarding_status: str = "not_started"
    created_at: datetime

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class MessageResponse(BaseModel):
    message: str


# --- Phase 1.2 Education Profile Schemas ---

class EducationProfileCreate(BaseModel):
    degree: str = Field(..., min_length=1, max_length=100, description="Degree name, e.g. Bachelor's degree")
    branch: str = Field(..., min_length=1, max_length=100, description="Branch/Major, e.g. Computer Science")
    college: str = Field(..., min_length=1, max_length=255, description="College or university name")
    graduation_year: int = Field(..., ge=1980, le=2035, description="Year of study or graduation")
    cgpa: Optional[float] = Field(None, description="CGPA or GPA score")
    cgpa_scale: Optional[float] = Field(10.0, description="CGPA scale, either 4.0 or 10.0")

    @model_validator(mode="after")
    def validate_cgpa(self):
        scale = self.cgpa_scale or 10.0
        if scale not in (4.0, 10.0):
            raise ValueError("CGPA scale must be either 4.0 or 10.0")
        if self.cgpa is not None:
            if self.cgpa < 0 or self.cgpa > scale:
                raise ValueError(f"CGPA must be between 0 and {scale}")
        return self


class EducationProfileOut(BaseModel):
    id: int
    user_id: int
    degree: str
    branch: str
    college: str
    graduation_year: int
    cgpa: Optional[float]
    cgpa_scale: Optional[float]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Phase 1.2 Target Profile Schemas ---

VALID_COMPANY_TYPES = ["Startup", "Product", "Service", "MNC", "Core/Other"]
VALID_EXPERIENCE_LEVELS = ["Fresher", "0-2", "2-5", "5+"]

TARGET_ROLE_SUGGESTIONS = [
    "Frontend Engineer",
    "Backend Engineer",
    "Fullstack Engineer",
    "Software Engineer",
    "Data Scientist",
    "Machine Learning Engineer",
    "DevOps Engineer",
    "Product Manager",
    "System Architect",
    "Mobile Developer (iOS/Android)",
    "QA / Test Automation Engineer",
]


class TargetProfileCreate(BaseModel):
    target_role: str = Field(..., min_length=1, max_length=150, description="Target role name")
    company_type: str = Field(..., description="Target company type")
    experience_level: str = Field(..., description="Candidate experience level")
    job_description: Optional[str] = Field(None, description="Optional job description for tailored practice")

    @model_validator(mode="after")
    def validate_fields(self):
        # Validate company type
        matched_company = next((c for c in VALID_COMPANY_TYPES if c.lower() == self.company_type.lower()), None)
        if not matched_company:
            raise ValueError(f"Invalid company type. Must be one of: {', '.join(VALID_COMPANY_TYPES)}")
        self.company_type = matched_company

        # Validate experience level
        # Accept variations like 'Student'/'1–3 years' from original mock and normalize
        exp_input = self.experience_level.strip()
        matched_exp = next((e for e in VALID_EXPERIENCE_LEVELS if e.lower() == exp_input.lower()), None)
        if not matched_exp:
            if exp_input.lower() in ("student", "fresher"):
                matched_exp = "Fresher"
            elif "1" in exp_input or "2" in exp_input or "0" in exp_input:
                matched_exp = "0-2"
            elif "3" in exp_input or "4" in exp_input or "5" in exp_input:
                matched_exp = "2-5"
            else:
                matched_exp = "5+"
        self.experience_level = matched_exp
        return self


class TargetProfileOut(BaseModel):
    id: int
    user_id: int
    target_role: str
    company_type: str
    experience_level: str
    job_description: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TargetSuggestionsOut(BaseModel):
    suggestions: List[str]
    company_types: List[str]
    experience_levels: List[str]


class OnboardingStatusOut(BaseModel):
    onboarding_status: str
    current_step: int
    education_done: bool
    target_done: bool
    cv_done: bool
    profile_confirmed: bool


# --- Phase 1.3 CV Schemas ---

class CVUploadResponse(BaseModel):
    id: int
    file_key: str
    filename: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class CVStatusResponse(BaseModel):
    id: int
    status: str
    filename: str
    file_size: int
    text_length: Optional[int] = None
    raw_text: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    extracted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CVErrorResponse(BaseModel):
    error_code: str
    detail: str
    message: str


# --- Phase 1.4 CV Structuring & Cross-Check Schemas ---

class PersonalInfo(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    links: List[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    degree: Optional[str] = None
    branch: Optional[str] = None
    college: Optional[str] = None
    year: Optional[Union[int, str]] = None
    cgpa: Optional[Union[float, str]] = None


class SkillGroups(BaseModel):
    languages: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    soft: List[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    title: str
    description: Optional[str] = None
    tech_stack: List[str] = Field(default_factory=list)
    role: Optional[str] = None
    outcomes: Optional[str] = None


class ExperienceItem(BaseModel):
    company: str
    role: str
    duration: Optional[str] = None
    responsibilities: List[str] = Field(default_factory=list)


class StructuredCV(BaseModel):
    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    education: List[EducationItem] = Field(default_factory=list)
    skills: SkillGroups = Field(default_factory=SkillGroups)
    projects: List[ProjectItem] = Field(default_factory=list)
    internships_experience: List[ExperienceItem] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    achievements: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_experience_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize internships / experience alias keys
            if "internships_experience" not in data or not data["internships_experience"]:
                if "internships" in data and data["internships"]:
                    data["internships_experience"] = data["internships"]
                elif "experience" in data and data["experience"]:
                    data["internships_experience"] = data["experience"]
        return data

    model_config = ConfigDict(populate_by_name=True)


class CrossCheckFlagType(str, Enum):
    MISMATCH = "MISMATCH"
    MISSING_SECTION = "MISSING_SECTION"


class SeverityLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CrossCheckFlag(BaseModel):
    type: CrossCheckFlagType
    field: str
    cv_value: Optional[str] = None
    form_value: Optional[str] = None
    severity: SeverityLevel
    message: str


class CVParsedResponse(BaseModel):
    id: int
    status: str
    structured_data: Optional[StructuredCV] = None
    cross_check_flags: List[CrossCheckFlag] = Field(default_factory=list)
    parsed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Phase 1.5 Canonical Profile Schemas ---

class ProfileConfirmRequest(BaseModel):
    structured_data: StructuredCV
    unresolved_flags: Optional[List[CrossCheckFlag]] = Field(default_factory=list)
    cv_document_id: Optional[int] = None


class ProfileOut(BaseModel):
    id: int
    user_id: int
    version: int
    structured_data: StructuredCV
    cv_document_id: Optional[int] = None
    confirmed_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# --- Phase 2.1 Interview Setup & Memory Schemas ---

VALID_ROUND_TYPES = ["Technical", "HR", "Managerial", "Mixed"]
VALID_DIFFICULTIES = ["Easy", "Medium", "Hard", "Adaptive"]
VALID_MODES = ["normal", "pressure"]
VALID_DURATIONS = [10, 15, 20, 30, 45, 60]


class InterviewConfigCreate(BaseModel):
    round_type: str = Field(..., description="Round type: Technical, HR, Managerial, Mixed")
    difficulty: str = Field(default="Medium", description="Difficulty: Easy, Medium, Hard, Adaptive")
    duration_minutes: int = Field(default=30, description="Duration in minutes (e.g. 15, 30, 45)")
    language: str = Field(default="English", description="Interview language (e.g. English)")
    mode: str = Field(default="normal", description="Mode: normal or pressure")
    focus_topics: Optional[List[str]] = Field(default_factory=list, description="Target topics or weak areas")

    @model_validator(mode="after")
    def validate_fields(self):
        # Case-insensitive normalization
        round_matched = next((r for r in VALID_ROUND_TYPES if r.lower() == self.round_type.strip().lower()), None)
        if not round_matched:
            raise ValueError(f"Invalid round_type '{self.round_type}'. Must be one of: {', '.join(VALID_ROUND_TYPES)}")
        self.round_type = round_matched

        diff_matched = next((d for d in VALID_DIFFICULTIES if d.lower() == self.difficulty.strip().lower()), None)
        if not diff_matched:
            raise ValueError(f"Invalid difficulty '{self.difficulty}'. Must be one of: {', '.join(VALID_DIFFICULTIES)}")
        self.difficulty = diff_matched

        mode_clean = self.mode.strip().lower()
        if mode_clean not in VALID_MODES:
            raise ValueError(f"Invalid mode '{self.mode}'. Must be one of: {', '.join(VALID_MODES)}")
        self.mode = mode_clean

        if self.duration_minutes < 5 or self.duration_minutes > 120:
            raise ValueError("duration_minutes must be between 5 and 120 minutes")

        return self


class InterviewConfigOut(BaseModel):
    id: int
    user_id: int
    round_type: str
    difficulty: str
    duration_minutes: int
    language: str
    mode: str
    focus_topics: Optional[List[str]] = Field(default_factory=list)
    answer_timer_seconds: int = 120
    pressure_rules: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


class AskedQuestionOut(BaseModel):
    id: int
    question_hash: str
    topic: str
    question_text: Optional[str] = None
    asked_at: datetime
    score: Optional[float] = None

    class Config:
        from_attributes = True


class UserContextOut(BaseModel):
    is_returning: bool
    session_count: int
    last_session_at: Optional[datetime] = None
    past_scores: Dict[str, float] = Field(default_factory=dict)
    weak_areas: List[str] = Field(default_factory=list)
    history_asked_questions: List[AskedQuestionOut] = Field(default_factory=list)
    baseline_weights: Dict[str, float] = Field(default_factory=dict)
    recommended_difficulty: str = "Medium"
    recommended_round: str = "Technical"
    recommended_duration: int = 30
    mode_presets: Dict[str, Any] = Field(default_factory=dict)


# --- Phase 2.2 Interview Blueprint Schemas ---

class BlueprintTopic(BaseModel):
    name: str
    category: str  # "Technical", "HR", "Managerial", "Project", "Core"
    weight: float
    allocated_questions: int
    is_weak_area: bool = False
    description: Optional[str] = None


class TimeBreakdown(BaseModel):
    warm_up_seconds: int
    questions_total_seconds: int
    closing_seconds: int
    total_allocated_seconds: int
    total_duration_seconds: int
    time_per_question_seconds: int


class InterviewBlueprint(BaseModel):
    round_type: str
    difficulty: str
    duration_minutes: int
    mode: str
    total_question_count: int
    time_per_question_seconds: int
    follow_up_limit_per_topic: int = 2
    difficulty_curve: List[str]
    topics: List[BlueprintTopic]
    warm_up_questions: List[str]
    closing_questions: List[str]
    time_breakdown: TimeBreakdown
    mixed_ratio: Optional[Dict[str, float]] = None


class InterviewBlueprintRequest(BaseModel):
    config_id: Optional[int] = None
    round_type: Optional[str] = None
    difficulty: Optional[str] = None
    duration_minutes: Optional[int] = None
    language: Optional[str] = None
    mode: Optional[str] = None
    focus_topics: Optional[List[str]] = None
    mixed_ratio: Optional[Dict[str, float]] = None


# --- Phase 2.3 Question Pool Generation & Bank Schemas ---

class QuestionBankItemOut(BaseModel):
    id: int
    interview_id: int
    question_hash: str
    text: str
    topic: str
    subtopic: Optional[str] = None
    difficulty: str
    question_type: str
    expected_keywords: List[str] = Field(default_factory=list)
    ideal_answer_points: List[str] = Field(default_factory=list)
    max_time_seconds: int
    cv_reference: Optional[str] = None
    is_weak_area: bool = False
    rank_score: float = 0.0
    is_reserve_followup: bool = False
    followup_templates: Optional[List[str]] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True


class QuestionPoolOut(BaseModel):
    interview_id: int
    total_generated: int
    deduped_count: int
    questions: List[QuestionBankItemOut]
    reserve_followups: List[QuestionBankItemOut]
    blueprint_summary: Dict[str, Any]


class QuestionGenerationRequest(BaseModel):
    force_regenerate: Optional[bool] = False
    similarity_threshold: Optional[float] = 0.82
    multiplier: Optional[float] = 2.5





