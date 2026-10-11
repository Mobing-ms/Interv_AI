# IntervAI Backend API

FastAPI backend for IntervAI, an AI mock-interview platform.

## Modules Implemented

### Phase 1.1: Authentication
- `POST /auth/signup`: Create user account with hashed password and return tokens.
- `POST /auth/login`: Authenticate user with rate limiting and generic error responses.
- `POST /auth/google`: Verify Google tokens or dev credentials, provision user.
- `GET /auth/me`: Retrieve current authenticated user profile.
- `POST /auth/refresh`: Issue new access token using refresh token.
- `POST /auth/logout`: Revoke session.
- `POST /auth/otp/request` & `POST /auth/otp/verify`: Optional 6-digit OTP verification.

### Phase 1.2: Education & Target-Role Profile (Onboarding)
- `GET /profile/education`: Fetch user's saved education profile.
- `PUT /profile/education`: Upsert degree, branch, college, graduation year, CGPA (0–10 or 0–4 with scale).
- `GET /profile/target`: Fetch user's saved target career profile.
- `PUT /profile/target`: Upsert target role, company type (Startup, Product, Service, MNC, Core/Other), experience level (Fresher, 0-2, 2-5, 5+), job description.
- `GET /profile/target/suggestions`: Retrieve target role recommendations.
- `GET /profile/status`: Get onboarding progression (`not_started`, `education_done`, `target_done`, `cv_done`, `profile_confirmed`) and current step.

### Phase 1.3: CV Upload & Text Extraction
- `POST /cv/upload`: Multipart upload with strict file validation (MIME type, PDF/DOCX only, max 5 MB, empty check, PDF encryption check). Returns specific error codes (`UNSUPPORTED_TYPE`, `TOO_LARGE`, `UNREADABLE`, `ENCRYPTED`). Stores original file in storage with unique key, tracks row in `cv_documents`.
- `GET /cv/{id}/status`: Poll extraction status (`uploaded`, `extracting`, `extracted`, `failed`), error message, and extracted text snippet.
- `GET /cv/latest`: Retrieve user's most recent uploaded CV document and parsing state.
- Extraction service: `pdfplumber` (text + tables), `python-docx` (paragraphs + tables + headers), with OCR fallback (`pytesseract` + `pdf2image`) for scanned PDFs.

### Phase 1.4: CV Structuring & Cross-Checking
- `POST /cv/{id}/parse`: Extracts structured JSON via centralized LLM service (prompt: *"extract only what is present in the text, never invent, use null for missing"*). Validates with Pydantic (`personal`, `education[]`, `skills` grouped, `projects[]`, `internships_experience[]`, `certifications[]`, `achievements[]`) and retries with error feedback if invalid. Cross-checks against user's `EducationProfile` and `TargetProfile`, saving structured data and flags to DB.
- `GET /cv/{id}/parsed`: Retrieves structured profile and cross-check flags (`MISMATCH` or `MISSING_SECTION`).
- `GET /cv/latest/parsed`: Retrieves the latest structured profile and cross-check flags for authenticated user.
- LLM Service (`app.services.llm`): Centralized wrapper with configurable provider (`mock`, `openai`, `gemini`, etc.), schema validation, backoff retries, timeouts, and logging.
### Phase 1.5: Profile Review, Flag Resolution & Versioned DB Persistence
- `PUT /profile/confirm`: Validates that no unresolved `HIGH`-severity flags remain. Saves user's canonical structured profile to the `profiles` table, increments `version = previous + 1`, and marks user's onboarding status as `profile_confirmed`. Returns the saved `ProfileOut`.
- `GET /profile`: Retrieves user's latest confirmed canonical profile (`ProfileOut`).
- `GET /profile/versions`: Returns profile revision history (version list with timestamps and associated CV IDs).
### Phase 2.1: Interview Setup & Returning-User Check
- `POST /interview/config`: Validates and saves interview configuration (`round_type`, `difficulty`, `duration_minutes`, `language`, `mode`, `focus_topics`). Sets `answer_timer_seconds` (60s for pressure mode, 120s for normal) and probing rules.
- `GET /interview/context`: Analyzes user memory. If new candidate, returns default baseline weights (equal weights across topics) and medium difficulty. If returning candidate, loads past topic scores, identified weak-area tags, previous asked questions (to avoid repeats), and adaptive recommendations.
- `GET /interview/config/latest`: Retrieves the candidate's latest interview configuration.
- `POST /interview/seed-history`: Dev endpoint / script to seed fake interview history (scores, weak areas, asked questions) to test returning candidate behavior.
- Seed script (`seed_user_history.py`): Run `python seed_user_history.py [email]` to simulate past sessions.

### Phase 2.2: Interview Blueprint Builder
- `POST /interview/blueprint`: Generates a deterministic, tailored interview blueprint.
  - Takes candidate's parsed CV, target role, session config, and historical memory context.
  - Computes weighted topic distribution (Technical: CV skills/projects/CS fundamentals; HR: self-intro, teamwork, conflict, motivation; Managerial: leadership, decision-making, ownership, prioritization; Mixed: configurable blend).
  - Boosts weights of weak areas identified in candidate memory.
  - Fits question count to duration (warm-up + question count * time per question + closing strictly equals total duration).
  - Enforces `follow_up_limit_per_topic = 2`.
  - Halves answer timer in Pressure mode (60s vs 120s), scaling up question pacing.
### Phase 2.3: Question Pool Generation & Question Bank
- `POST /interview/{id}/questions/generate`: Generates a seed pool of 2–3x required questions using LLM or context-aware generation grounded in CV skills/projects. Deduplicates near-duplicates via sentence embedding cosine similarity and eliminates any questions matching the user's `AskedQuestion` history. Ranks questions by topic weight, weak-area boost, and difficulty fit, attaching reserve follow-up templates per topic. Persists into `question_bank_items` table.
- `GET /interview/{id}/questions`: Retrieves active questions and reserve follow-ups for the given interview session.
- Models: `QuestionBankItem` (linked to `InterviewConfig` with foreign key and cascade deletion).

## How to Run

1. Activate virtual environment:
   ```bash
   cd backend
   .\venv\Scripts\Activate.ps1
   ```
2. Run database migrations:
   ```bash
   alembic upgrade head
   ```
3. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

## How to Test

Run the test suites:
```bash
python test_auth.py
python test_profile.py
python test_phase1_2.py
python test_cv.py
python test_cv_phase1_4.py
python test_profile_phase1_5.py
python test_interview_phase2_1.py
python test_interview_blueprint.py
python test_question_bank_phase2_3.py
```
To seed fake interview history for testing returning users:
```bash
python seed_user_history.py
```
