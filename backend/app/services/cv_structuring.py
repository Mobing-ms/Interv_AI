import logging
from datetime import datetime, timezone
from typing import Tuple, List, Optional
from sqlalchemy.orm import Session

from app.models import CVDocument, EducationProfile, TargetProfile
from app.schemas import StructuredCV, CrossCheckFlag
from app.services.llm import llm_service
from app.services.cv_cross_check import cross_check_cv

logger = logging.getLogger("intervai.cv_structuring")

STRICT_SYSTEM_PROMPT = """You are an expert CV / Resume structuring parser for IntervAI.
Your task is to analyze the extracted CV text and extract structured information into strict JSON format.

RULES:
1. Extract only what is present in the text, never invent, use null for missing.
2. Group skills strictly into: languages, frameworks, tools, domains, soft.
3. For education: degree, branch, college, year, cgpa.
4. For projects: title, description, tech_stack, role, outcomes.
5. For internships/experience: company, role, duration, responsibilities.
6. Certifications and achievements as simple lists of strings.
7. Return a single valid JSON object strictly conforming to the requested schema. Never output explanations outside JSON.
"""

JSON_SCHEMA_HINT = """
Target Schema:
{
  "personal": {"name": string|null, "email": string|null, "phone": string|null, "links": [string]},
  "education": [{"degree": string|null, "branch": string|null, "college": string|null, "year": int|string|null, "cgpa": float|string|null}],
  "skills": {"languages": [string], "frameworks": [string], "tools": [string], "domains": [string], "soft": [string]},
  "projects": [{"title": string, "description": string|null, "tech_stack": [string], "role": string|null, "outcomes": string|null}],
  "internships_experience": [{"company": string, "role": string, "duration": string|null, "responsibilities": [string]}],
  "certifications": [string],
  "achievements": [string]
}
"""


async def structure_cv_text(raw_text: str) -> StructuredCV:
    """Sends extracted CV text to the LLM and validates against Pydantic schema with retry."""
    user_prompt = f"CV TEXT TO PARSE:\n{raw_text}\n\n{JSON_SCHEMA_HINT}"
    structured: StructuredCV = await llm_service.generate_structured_json(
        system_prompt=STRICT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_cls=StructuredCV,
        max_retries=1,  # retry once with validation error appended as requested
    )
    return structured


async def parse_and_cross_check_cv(
    cv_doc: CVDocument,
    db: Session,
) -> Tuple[StructuredCV, List[CrossCheckFlag]]:
    """Structures CV document text using LLM and runs cross-checks against education & target profiles."""
    if not cv_doc.raw_text or not cv_doc.raw_text.strip():
        raise ValueError("CV document has no extracted text to structure.")

    # 1. LLM Structuring
    structured_cv = await structure_cv_text(cv_doc.raw_text)

    # 2. Fetch user's education and target profiles for cross-checking
    education_profile = (
        db.query(EducationProfile).filter(EducationProfile.user_id == cv_doc.user_id).first()
    )
    target_profile = (
        db.query(TargetProfile).filter(TargetProfile.user_id == cv_doc.user_id).first()
    )

    # 3. Cross-Check
    flags = cross_check_cv(
        cv_data=structured_cv,
        education_form=education_profile,
        target_profile=target_profile,
    )

    # 4. Save to Database
    cv_doc.structured_data = structured_cv.model_dump()
    cv_doc.cross_check_flags = [f.model_dump() for f in flags]
    cv_doc.parsed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cv_doc)

    return structured_cv, flags
