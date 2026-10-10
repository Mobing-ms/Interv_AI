import json
import logging
import asyncio
from typing import Type, TypeVar, Optional, Callable, Any, Dict
import httpx
from pydantic import BaseModel, ValidationError
from app.config import settings

logger = logging.getLogger("intervai.llm")

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMValidationError(LLMError):
    pass


class LLMService:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER.lower()
        self.model = settings.LLM_MODEL
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.timeout = settings.LLM_TIMEOUT_SECONDS
        self.max_retries = settings.LLM_MAX_RETRIES
        self._mock_handler: Optional[Callable[[str, str], Dict[str, Any]]] = None

    def set_mock_handler(self, handler: Optional[Callable[[str, str], Dict[str, Any]]]):
        """Allows test suites to mock LLM responses directly."""
        self._mock_handler = handler

    async def call_raw_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Invokes the configured LLM provider and returns the raw string response."""
        prompt_size = len(system_prompt) + len(user_prompt)
        logger.info(f"[LLM] Dispatching request to provider='{self.provider}' model='{self.model}' | Prompt length: {prompt_size} chars")

        if self._mock_handler:
            mock_res = self._mock_handler(system_prompt, user_prompt)
            if isinstance(mock_res, str):
                raw_text = mock_res
            else:
                raw_text = json.dumps(mock_res)
            logger.info(f"[LLM] Mock handler returned {len(raw_text)} chars")
            return raw_text

        if self.provider == "mock":
            # Default fallback mock parser for dev without API keys
            raw_text = self._default_mock_response(system_prompt, user_prompt)
            logger.info(f"[LLM] Built-in mock returned {len(raw_text)} chars")
            return raw_text

        elif self.provider in ("openai", "azure", "groq", "ollama"):
            base_url = self.base_url or "https://api.openai.com/v1"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
                res.raise_for_status()
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                logger.info(f"[LLM] Provider returned response of {len(content)} chars")
                return content

        elif self.provider == "gemini":
            base_url = self.base_url or f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER PROMPT:\n{user_prompt}"}],
                    }
                ],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": 0.0,
                },
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(base_url, json=payload)
                res.raise_for_status()
                data = res.json()
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                logger.info(f"[LLM] Gemini returned response of {len(content)} chars")
                return content

        else:
            raise LLMError(f"Unsupported LLM provider: {self.provider}")

    async def generate_structured_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_cls: Type[T],
        max_retries: Optional[int] = None,
    ) -> T:
        """
        Invokes LLM with JSON-mode output, validates against Pydantic schema,
        and retries with backoff and validation error feedback appended if invalid.
        """
        retries = self.max_retries if max_retries is None else max_retries
        current_user_prompt = user_prompt
        last_error = None

        for attempt in range(retries + 1):
            try:
                raw_response = await self.call_raw_llm(system_prompt, current_user_prompt)

                # Strip markdown code fencing if LLM wraps in ```json ... ```
                clean_response = raw_response.strip()
                if clean_response.startswith("```json"):
                    clean_response = clean_response[7:]
                elif clean_response.startswith("```"):
                    clean_response = clean_response[3:]
                if clean_response.endswith("```"):
                    clean_response = clean_response[:-3]
                clean_response = clean_response.strip()

                parsed_dict = json.loads(clean_response)
                validated_model = schema_cls.model_validate(parsed_dict)
                return validated_model

            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)
                logger.warning(
                    f"[LLM] Validation failed on attempt {attempt + 1}/{retries + 1}: {last_error}"
                )

                if attempt < retries:
                    # Retry once with the validation error appended as requested
                    backoff = 0.5 * (2 ** attempt)
                    await asyncio.sleep(backoff)
                    current_user_prompt = (
                        f"{user_prompt}\n\n"
                        f"[CRITICAL ERROR ON PREVIOUS ATTEMPT]:\n"
                        f"Your output failed validation with the following error:\n{last_error}\n"
                        f"Ensure you return valid JSON strictly conforming to the requested schema. Do not invent fields."
                    )
                else:
                    break

        raise LLMValidationError(
            f"Failed to produce valid structured JSON after {retries + 1} attempts. Last error: {last_error}"
        )

    def _default_mock_response(self, system_prompt: str, user_prompt: str) -> str:
        """Heuristic mock response when no LLM key is configured in dev mode."""
        lower_prompt = user_prompt.lower()
        
        # Simple extraction heuristics from CV text
        name = "Candidate"
        email = None
        phone = None
        links = []

        import re
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", user_prompt)
        if email_match:
            email = email_match.group(0)

        phone_match = re.search(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", user_prompt)
        if phone_match:
            phone = phone_match.group(0)

        link_matches = re.findall(r"(https?://[^\s]+|github\.com/[^\s]+|linkedin\.com/in/[^\s]+)", user_prompt)
        if link_matches:
            links = link_matches

        # Check education
        education = []
        if "degree" in lower_prompt or "university" in lower_prompt or "bachelor" in lower_prompt or "b.tech" in lower_prompt or "master" in lower_prompt:
            deg = "Bachelor of Science" if "bachelor" in lower_prompt or "b.tech" in lower_prompt else "Master of Science" if "master" in lower_prompt else "Bachelor's degree"
            branch = "Computer Science" if "computer science" in lower_prompt else "Engineering"
            college = "University"
            if "stanford" in lower_prompt:
                college = "Stanford University"
            elif "mit" in lower_prompt or "massachusetts institute" in lower_prompt:
                college = "MIT"
            elif "berkeley" in lower_prompt:
                college = "UC Berkeley"
            
            year_match = re.search(r"\b(202[0-9]|201[0-9])\b", user_prompt)
            year = int(year_match.group(0)) if year_match else 2026
            education.append({
                "degree": deg,
                "branch": branch,
                "college": college,
                "year": year,
                "cgpa": 3.8
            })

        # Check skills
        skills = {
            "languages": [s for s in ["Python", "TypeScript", "JavaScript", "Java", "C++", "Go", "SQL"] if s.lower() in lower_prompt],
            "frameworks": [s for s in ["React", "FastAPI", "Next.js", "Django", "Vue", "Spring", "PyTorch", "TensorFlow"] if s.lower() in lower_prompt],
            "tools": [s for s in ["Docker", "Git", "Kubernetes", "AWS", "Linux", "PostgreSQL", "MongoDB"] if s.lower() in lower_prompt],
            "domains": [s for s in ["Web Development", "Machine Learning", "Cloud", "Distributed Systems"] if s.lower() in lower_prompt],
            "soft": [s for s in ["Teamwork", "Communication", "Problem Solving", "Leadership"] if s.lower() in lower_prompt]
        }

        # Check projects
        projects = []
        if "project" in lower_prompt:
            projects.append({
                "title": "Platform Application",
                "description": "Full-stack application built with modern architecture",
                "tech_stack": [s for s in ["React", "Python", "FastAPI", "Docker"] if s.lower() in lower_prompt] or ["Python"],
                "role": "Lead Developer",
                "outcomes": "Increased test coverage and latency by 40%"
            })

        # Experience
        experience = []
        if "intern" in lower_prompt or "experience" in lower_prompt or "engineer at" in lower_prompt:
            experience.append({
                "company": "Tech Corp",
                "role": "Software Engineering Intern",
                "duration": "June 2024 - August 2024",
                "responsibilities": ["Built REST APIs", "Optimized database queries"]
            })

        return json.dumps({
            "personal": {"name": name, "email": email, "phone": phone, "links": links},
            "education": education,
            "skills": skills,
            "projects": projects,
            "internships_experience": experience,
            "certifications": [],
            "achievements": []
        })


# Global singleton instance
llm_service = LLMService()
