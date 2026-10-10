import re
from typing import List, Optional, Set
from app.schemas import (
    StructuredCV,
    CrossCheckFlag,
    CrossCheckFlagType,
    SeverityLevel,
)
from app.models import EducationProfile, TargetProfile

ROLE_KEYWORDS_MAP = {
    "frontend": {"javascript", "typescript", "react", "vue", "angular", "html", "css", "next.js", "frontend", "ui", "tailwind", "redux", "web"},
    "backend": {"python", "java", "node", "golang", "go", "fastapi", "django", "spring", "sql", "postgresql", "mysql", "mongodb", "docker", "microservices", "backend", "api", "redis"},
    "fullstack": {"javascript", "typescript", "react", "node", "python", "fastapi", "fullstack", "web", "sql", "next.js", "django"},
    "data science": {"python", "machine learning", "deep learning", "pytorch", "tensorflow", "nlp", "llm", "pandas", "numpy", "scikit-learn", "data science", "statistics", "ai"},
    "machine learning": {"python", "machine learning", "deep learning", "pytorch", "tensorflow", "nlp", "llm", "pandas", "numpy", "scikit-learn", "ai"},
    "devops": {"docker", "kubernetes", "aws", "gcp", "azure", "ci/cd", "terraform", "linux", "devops", "cloud", "ansible", "jenkins"},
    "cloud": {"docker", "kubernetes", "aws", "gcp", "azure", "terraform", "cloud"},
    "mobile": {"flutter", "react native", "swift", "kotlin", "ios", "android", "mobile"},
    "qa": {"testing", "selenium", "cypress", "jest", "pytest", "automation", "qa"},
}

DEGREE_LEVEL_MAP = {
    "bachelor": {"bachelor", "b.tech", "btech", "b.e", "be", "b.s", "bs", "bsc", "undergraduate", "bca"},
    "master": {"master", "m.tech", "mtech", "m.e", "me", "m.s", "ms", "msc", "postgraduate", "mca", "mba"},
    "ph.d.": {"ph.d", "phd", "doctorate", "doctoral"},
    "diploma": {"diploma", "associate"},
}


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _get_degree_category(degree_name: Optional[str]) -> Optional[str]:
    norm = _normalize(degree_name)
    for cat, keywords in DEGREE_LEVEL_MAP.items():
        for kw in keywords:
            if kw in norm:
                return cat
    return None


def cross_check_cv(
    cv_data: StructuredCV,
    education_form: Optional[EducationProfile] = None,
    target_profile: Optional[TargetProfile] = None,
) -> List[CrossCheckFlag]:
    flags: List[CrossCheckFlag] = []

    # 1. Missing Section Validations
    if not cv_data.projects:
        flags.append(
            CrossCheckFlag(
                type=CrossCheckFlagType.MISSING_SECTION,
                field="projects",
                cv_value="None",
                form_value=None,
                severity=SeverityLevel.HIGH,
                message="No projects section found in CV. Interviewers frequently evaluate hands-on projects.",
            )
        )

    all_skills: List[str] = (
        cv_data.skills.languages
        + cv_data.skills.frameworks
        + cv_data.skills.tools
        + cv_data.skills.domains
        + cv_data.skills.soft
    )
    if not all_skills:
        flags.append(
            CrossCheckFlag(
                type=CrossCheckFlagType.MISSING_SECTION,
                field="skills",
                cv_value="None",
                form_value=None,
                severity=SeverityLevel.HIGH,
                message="No skills section found in CV.",
            )
        )

    # 2. Education Form Cross-Check
    if education_form:
        if not cv_data.education:
            flags.append(
                CrossCheckFlag(
                    type=CrossCheckFlagType.MISSING_SECTION,
                    field="education",
                    cv_value="None",
                    form_value=education_form.degree,
                    severity=SeverityLevel.HIGH,
                    message="No education section found in CV despite education profile provided.",
                )
            )
        else:
            # Check Degree
            form_deg_cat = _get_degree_category(education_form.degree)
            cv_deg_cats = [_get_degree_category(e.degree) for e in cv_data.education if e.degree]
            cv_degrees = [e.degree for e in cv_data.education if e.degree]
            if form_deg_cat and cv_deg_cats and (form_deg_cat not in cv_deg_cats):
                flags.append(
                    CrossCheckFlag(
                        type=CrossCheckFlagType.MISMATCH,
                        field="degree",
                        cv_value=", ".join(cv_degrees) if cv_degrees else "Not specified",
                        form_value=education_form.degree,
                        severity=SeverityLevel.MEDIUM,
                        message=f"Degree mismatch: Education form specifies '{education_form.degree}', but CV lists '{', '.join(cv_degrees)}'.",
                    )
                )

            # Check Branch/Major
            if education_form.branch:
                form_branch_norm = _normalize(education_form.branch)
                form_branch_tokens = set(form_branch_norm.split()) - {"and", "of", "in", "engineering", "technology"}
                cv_branches = [e.branch for e in cv_data.education if e.branch]
                
                matched_branch = False
                for cv_b in cv_branches:
                    cv_b_norm = _normalize(cv_b)
                    cv_tokens = set(cv_b_norm.split())
                    if form_branch_tokens & cv_tokens or form_branch_norm in cv_b_norm or cv_b_norm in form_branch_norm:
                        matched_branch = True
                        break

                if cv_branches and not matched_branch:
                    flags.append(
                        CrossCheckFlag(
                            type=CrossCheckFlagType.MISMATCH,
                            field="branch",
                            cv_value=", ".join(cv_branches),
                            form_value=education_form.branch,
                            severity=SeverityLevel.MEDIUM,
                            message=f"Branch mismatch: Form specifies '{education_form.branch}', but CV lists '{', '.join(cv_branches)}'.",
                        )
                    )

            # Check College/University
            if education_form.college:
                form_col_norm = _normalize(education_form.college)
                stop_words = {"university", "college", "institute", "of", "technology", "the"}
                form_col_tokens = set(form_col_norm.split()) - stop_words
                cv_colleges = [e.college for e in cv_data.education if e.college]

                matched_college = False
                for cv_col in cv_colleges:
                    cv_col_norm = _normalize(cv_col)
                    cv_tokens = set(cv_col_norm.split()) - stop_words
                    if (form_col_tokens and form_col_tokens & cv_tokens) or form_col_norm in cv_col_norm or cv_col_norm in form_col_norm:
                        matched_college = True
                        break

                if cv_colleges and not matched_college:
                    flags.append(
                        CrossCheckFlag(
                            type=CrossCheckFlagType.MISMATCH,
                            field="college",
                            cv_value=", ".join(cv_colleges),
                            form_value=education_form.college,
                            severity=SeverityLevel.MEDIUM,
                            message=f"College mismatch: Form specifies '{education_form.college}', but CV lists '{', '.join(cv_colleges)}'.",
                        )
                    )

            # Check Graduation Year
            if education_form.graduation_year:
                cv_years = []
                for e in cv_data.education:
                    if e.year:
                        years = re.findall(r"\b(20\d\d|19\d\d)\b", str(e.year))
                        cv_years.extend([int(y) for y in years])

                if cv_years and education_form.graduation_year not in cv_years:
                    flags.append(
                        CrossCheckFlag(
                            type=CrossCheckFlagType.MISMATCH,
                            field="graduation_year",
                            cv_value=", ".join(str(y) for y in cv_years),
                            form_value=str(education_form.graduation_year),
                            severity=SeverityLevel.HIGH,
                            message=f"Graduation year mismatch: Form specifies '{education_form.graduation_year}', but CV indicates '{', '.join(str(y) for y in cv_years)}'.",
                        )
                    )

            # Check CGPA
            if education_form.cgpa is not None:
                cv_cgpas = []
                for e in cv_data.education:
                    if e.cgpa is not None:
                        try:
                            # Match float or int
                            cgpa_val = float(str(e.cgpa).split("/")[0].strip())
                            cv_cgpas.append(cgpa_val)
                        except (ValueError, IndexError):
                            pass

                if cv_cgpas:
                    closest_diff = min(abs(val - float(education_form.cgpa)) for val in cv_cgpas)
                    if closest_diff >= 0.4:
                        flags.append(
                            CrossCheckFlag(
                                type=CrossCheckFlagType.MISMATCH,
                                field="cgpa",
                                cv_value=", ".join(str(val) for val in cv_cgpas),
                                form_value=str(education_form.cgpa),
                                severity=SeverityLevel.MEDIUM,
                                message=f"CGPA mismatch: Form specifies '{education_form.cgpa}', but CV indicates '{', '.join(str(val) for val in cv_cgpas)}'.",
                            )
                        )

    # 3. Target Profile Cross-Check
    if target_profile:
        # Check target role alignment against skills & projects
        target_role_norm = _normalize(target_profile.target_role)
        role_tokens = set(target_role_norm.split()) - {"engineer", "developer", "specialist", "lead", "senior", "junior", "intern"}

        # Gather expected skills from map
        expected_keywords: Set[str] = set()
        for key, kw_set in ROLE_KEYWORDS_MAP.items():
            if key in target_role_norm:
                expected_keywords.update(kw_set)
        expected_keywords.update(role_tokens)

        # Collect all candidate skill keywords (lowercased)
        candidate_skills_lower = set([_normalize(s) for s in all_skills])
        for p in cv_data.projects:
            candidate_skills_lower.update([_normalize(t) for t in p.tech_stack])
            if p.title:
                candidate_skills_lower.update(_normalize(p.title).split())
        for exp in cv_data.internships_experience:
            if exp.role:
                candidate_skills_lower.update(_normalize(exp.role).split())

        def _matches_skill(cand_s: str, exp_k: str) -> bool:
            if not cand_s or not exp_k:
                return False
            if cand_s == exp_k:
                return True
            if len(cand_s) >= 3 and len(exp_k) >= 3:
                cand_words = set(cand_s.split())
                exp_words = set(exp_k.split())
                if cand_words & exp_words:
                    return True
                if cand_s.startswith(exp_k) or exp_k.startswith(cand_s):
                    return True
            return False

        has_overlap = False
        for exp_kw in expected_keywords:
            if any(_matches_skill(s, exp_kw) for s in candidate_skills_lower if s):
                has_overlap = True
                break

        if expected_keywords and not has_overlap:
            cv_skills_summary = ", ".join(all_skills[:6]) if all_skills else "No skills listed"
            flags.append(
                CrossCheckFlag(
                    type=CrossCheckFlagType.MISMATCH,
                    field="target_role_skills",
                    cv_value=cv_skills_summary,
                    form_value=target_profile.target_role,
                    severity=SeverityLevel.HIGH,
                    message=f"Target role is '{target_profile.target_role}', but CV does not list relevant skills or experience for this role.",
                )
            )

        # Check experience level vs CV experience
        if target_profile.experience_level in ("2-5", "5+", "2-5 years", "5+ years"):
            if not cv_data.internships_experience:
                flags.append(
                    CrossCheckFlag(
                        type=CrossCheckFlagType.MISMATCH,
                        field="experience",
                        cv_value="No professional experience listed",
                        form_value=target_profile.experience_level,
                        severity=SeverityLevel.MEDIUM,
                        message=f"Target profile specifies '{target_profile.experience_level}' experience, but CV contains no experience entries.",
                    )
                )

    return flags
