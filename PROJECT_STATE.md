# IntervAI — Project Memory & Phase 1 -> Phase 2 Handover

This file serves as the permanent memory and architectural record for IntervAI. When resuming work in a new session or after a machine reboot, read this file first.

---

## 1. Project Overview & Repository
- **Remote Git Repository**: `https://github.com/Mobing-ms/Interv_AI.git` (Branch: `main`)
- **Workspace Location**: `c:\Users\soory\Downloads\InterAI`
- **Frontend Directory**: `c:\Users\soory\Downloads\InterAI\Interv_AI` (React 18 + TypeScript + Vite + Tailwind CSS)
- **Backend Directory**: `c:\Users\soory\Downloads\InterAI\backend` (and mirrored in `Interv_AI/backend` for Git tracking)
- **Database**: SQLite at `c:\Users\soory\Downloads\InterAI\backend\intervai.db` (managed via SQLAlchemy and Alembic)

---

## 2. Phase 1 Accomplishments (100% Complete & Verified)

### Phase 1.1: Authentication
- **User Model**: `id`, `name`, `email`, `password_hash`, `auth_provider`, `is_verified`, `onboarding_status`, `created_at`.
- **JWT Auth**: Access token (60 min) + Refresh token (7 days).
- **Endpoints**:
  - `POST /auth/signup`
  - `POST /auth/login` (Rate limited via SlowAPI)
  - `POST /auth/google` (Google ID token / dev credentials)
  - `GET /auth/me`
  - `POST /auth/refresh`
  - `POST /auth/logout`
  - `POST /auth/otp/request` & `POST /auth/otp/verify` (Dev OTP flag in `.env`)
- **Frontend Wiring**: Unified auth context (`authContext.tsx`), API client (`api.ts`), protected routes, real user greeting on Dashboard.

### Phase 1.2: Education & Target Career Onboarding
- **Models**: `EducationProfile` (degree, branch, college, graduation year, CGPA 0-10 or 0-4) and `TargetProfile` (target role, company type, experience level, job description).
- **Endpoints**: `GET/PUT /profile/education`, `GET/PUT /profile/target`, `GET /profile/target/suggestions`, `GET /profile/status`.
- **Frontend Wiring**: Step 1 and Step 2 connected with inline validation, local storage draft auto-save, and onboarding step resume.

### Phase 1.3: CV Upload & Text Extraction
- **Model**: `CVDocument` (`id`, `user_id`, `file_key`, `filename`, `file_size`, `mime_type`, `status`, `extracted_text`, `error_code`, `error_message`).
- **Validation**: PDF and DOCX only, 5 MB limit, unreadable/empty detection, PDF encryption/password check. Specific error codes (`UNSUPPORTED_TYPE`, `TOO_LARGE`, `UNREADABLE`, `ENCRYPTED`).
- **Extraction Engine**: `pdfplumber` (text + tables), `python-docx` (paragraphs + tables + headers), OCR fallback (`pytesseract` + `pdf2image`) for scanned PDFs.
- **Endpoints**: `POST /cv/upload` (multipart), `GET /cv/{id}/status`, `GET /cv/latest`.
- **Frontend Wiring**: Drag-and-drop file upload, extraction progress polling, error banners with re-upload buttons.

### Phase 1.4: CV Structuring & Cross-Checking
- **LLM Structuring**: Strict extraction prompt ("extract only what is present, never invent, use null for missing"). Validated via Pydantic (`personal`, `education[]`, `skills`, `projects[]`, `internships_experience[]`, `certifications[]`, `achievements[]`) with automatic retry on schema errors.
- **Cross-Check Engine**: Evaluates CV vs education form and target profile. Emits `CrossCheckFlag` objects (`MISMATCH` or `MISSING_SECTION`) with severity (`HIGH`, `MEDIUM`, `LOW`).
- **Endpoints**: `POST /cv/{id}/parse`, `GET /cv/{id}/parsed`, `GET /cv/latest/parsed`.

### Phase 1.5: Profile Review, Flag Resolution & Canonical DB
- **Model**: `Profile` (`id`, `user_id`, `structured_data`, `version`, `cv_document_id`, `confirmed_at`, `created_at`).
- **Confirmation Logic**: Blocks confirmation (`HTTP 400`) if any `HIGH`-severity flags remain unresolved. Increments `version = latest_version + 1`, marks `user.onboarding_status = "profile_confirmed"`.
- **Endpoints**: `PUT /profile/confirm`, `GET /profile`, `GET /profile/versions`.
- **Frontend Wiring**: Step 4 review interface with editable cards for all sections, add/remove items, "Keep CV value" / "Use form value" flag resolution buttons, and confirmation button enabled only once high-severity items are addressed.

---

## 3. How to Resume After Machine Reboot

### A. Start the Backend API (FastAPI)
```powershell
cd c:\Users\soory\Downloads\InterAI\backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Runs at: `http://127.0.0.1:8000`

### B. Start the Frontend (Vite)
```powershell
cd c:\Users\soory\Downloads\InterAI\Interv_AI
npm run dev
```
Runs at: `http://localhost:5173` or `http://localhost:5174`

### C. Run Backend Tests
```powershell
cd c:\Users\soory\Downloads\InterAI\backend
.\venv\Scripts\python.exe test_auth.py
.\venv\Scripts\python.exe test_phase1_2.py
.\venv\Scripts\python.exe test_cv.py
.\venv\Scripts\python.exe test_cv_phase1_4.py
.\venv\Scripts\python.exe test_profile_phase1_5.py
.\venv\Scripts\python.exe test_interview_phase2_1.py
```

To seed simulated returning-candidate history:
```powershell
.\venv\Scripts\python.exe seed_user_history.py
```

---

## 4. Phase 2 Progress & Architecture

### Phase 2.1: Interview Setup & Returning-User Check (100% Complete & Verified)
- **Models**:
  - `InterviewConfig`: `id`, `user_id`, `round_type` (Technical, HR, Managerial, Mixed), `difficulty` (Easy, Medium, Hard, Adaptive), `duration_minutes` (15, 30, 45, 60), `language`, `mode` (normal, pressure), `focus_topics`, `created_at`.
  - `UserMemory`: `id`, `user_id`, `topic_scores` JSON, `weak_topics` JSON, `session_count`, `last_session_at`, timestamps.
  - `AskedQuestion`: `id`, `user_id`, `question_hash`, `topic`, `question_text`, `asked_at`, `score`.
- **Service `load_user_context(user_id, db)`**:
  - New users: returns `is_returning=False`, default baseline equal weights (0.25 each), Medium difficulty start.
  - Returning users: loads `is_returning=True`, past scores, identified weak-area tags, history of asked questions (to avoid repeats), and weak-area boosted weights.
- **Endpoints**:
  - `POST /interview/config`: Validates and saves setup, computes `answer_timer_seconds` (60s for pressure mode, 120s for normal).
  - `GET /interview/context`: Returns candidate memory and recommendations.
  - `GET /interview/config/latest`: Returns candidate's most recent configuration.
  - `POST /interview/seed-history`: Dev endpoint to simulate candidate history.
- **Frontend Setup Screen (`Setup` in `main.tsx`)**:
  - Round selector: Technical, HR, Managerial, Mixed.
  - Difficulty: Easy, Medium, Hard, Adaptive.
  - Duration: 15, 30, 45, 60 min.
  - Language: English, Spanish, German, French, Hindi.
  - Pressure Mode toggle: Active callout highlighting 60s answer limits and aggressive follow-up challenges.
  - Returning Candidate Badge: Displays `Session #{N+1}`, weak areas quick-add buttons, past topic scores, and prior questions index indicator.
  - New Candidate Badge: Displays baseline evaluation indicator.
  - Saved to `POST /interview/config` before transitioning to precheck.

### Upcoming Next in Phase 2
- **Phase 2.2**: Interview Blueprint & LLM Seed Question Pool (blueprint generator, seed question generation from CV & round type, dedupe, tag, rank, Question Bank persistence).

