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
.\venv\Scripts\python.exe test_interview_blueprint.py
.\venv\Scripts\python.exe test_question_bank_phase2_3.py
.\venv\Scripts\python.exe test_preinterview_phase3_1.py
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

### Phase 2.2: Interview Blueprint Builder (100% Complete & Verified)
- **Pure Function**: `build_interview_blueprint(profile, target_profile, config, user_context, mixed_ratio)`.
  - Determines topics based on round type:
    - `Technical`: CV skills (languages, frameworks, tools), projects deep-dive, target role architecture, and core CS fundamentals (DSA, DBMS, OS, Networks, System Design).
    - `HR`: Self-introduction, strengths/weaknesses, teamwork, conflict resolution, motivation, situational judgment.
    - `Managerial`: Leadership, decision-making under ambiguity, extreme ownership, prioritization, stakeholder management.
    - `Mixed`: Configurable ratio blending Technical, HR, and Managerial categories.
  - Boosts weights of weak areas identified in candidate memory (1.85x multiplier, ensuring heavy interview focus on growth areas).
  - Strict duration math: fits question count to chosen duration (`warm_up + (total_questions * time_per_question) + closing == total_duration`).
  - Mode differentiation: Normal mode = 120s timer; Pressure mode = 60s timer (scales up question pacing).
  - Strict topic follow-up limit: `follow_up_limit_per_topic = 2`.
  - Difficulty curve: custom trajectories for Easy, Medium, Hard, and Adaptive.
- **Endpoint**: `POST /interview/blueprint` automatically assembles user's canonical profile, target role, configuration, and memory context, supporting request overrides.
- **Test Suite**: `test_interview_blueprint.py` (9/9 tests passed).

### Phase 2.3: Question Pool Generation & Question Bank (100% Complete & Verified)
- **Model**: `QuestionBankItem` (`id`, `interview_id`, `question_hash`, `text`, `topic`, `subtopic`, `difficulty`, `question_type`, `expected_keywords`, `ideal_answer_points`, `max_time_seconds`, `cv_reference`, `is_weak_area`, `rank_score`, `is_reserve_followup`, `followup_templates`, `created_at`).
  - Foreign key linked to `interview_configs.id` with cascade deletion.
  - Alembic migration `bf5ad75e9047_create_question_bank_items_table.py` applied.
- **Deduplication Engine (`question_dedupe.py`)**:
  - Exact question fingerprinting via normalized SHA-256 (`compute_question_hash`).
  - Near-duplicate detection using term-frequency & sub-word n-gram vectorization with cosine similarity threshold ($\ge 0.82$).
  - Historical exclusion: drops questions matching the candidate's `AskedQuestion.question_hash` history so returning users never see repeated questions.
- **Generation & Ranking Engine (`question_generator.py`)**:
  - Generates 2-3x seed pool via LLM or context-aware generator grounded in CV projects, skills, education, and target role.
  - Project-based and skill-based questions strictly reference real CV items.
  - Tag validation and normalization (`conceptual`, `coding-explanation`, `scenario`, `behavioral`, `project-based`).
  - Scoring formula: $\text{rank\_score} = (\text{topic\_weight} \times 0.40) + (\text{weak\_area\_boost} \times 0.35) + (\text{diff\_fit} \times 0.10) + (\text{cv\_ref\_boost} \times 0.15)$.
  - Reserve follow-up questions: partitions pool into active questions (`total_question_count`) and reserve questions with follow-up templates attached per topic.
- **Endpoints**:
  - `POST /interview/{id}/questions/generate`: Generates, dedupes, ranks, and stores the question pool in the database (supports `force_regenerate=True`).
  - `GET /interview/{id}/questions`: Retrieves active questions and reserve follow-ups with blueprint summary.
- **Test Suite**: `test_question_bank_phase2_3.py` (7/7 tests passed).

---

---

## 5. Phase 3 Accomplishments & Architecture

### Phase 3.1: Pre-Interview Check, Consent, Calibration & Session Lifecycle (100% Complete & Verified)
- **Consent Screen & Enforcement**:
  - Clear terms detailing audio/video recording, multimodal AI behavioral & technical analysis, and configurable retention (`settings.RECORDING_RETENTION_DAYS = 30`).
  - Candidate right-to-delete guarantee.
  - `UserConsent` model (`id`, `user_id`, `version`, `retention_days`, `accepted`, `can_delete`, `accepted_at`).
  - Endpoints: `POST /session/consent` & `GET /session/consent`.
  - Blocks session creation with HTTP 403 if consent is missing.
- **Device & Network Diagnostics (Frontend + Backend)**:
  - Camera & Mic checks using `navigator.mediaDevices.getUserMedia`.
  - Live video preview with mirror orientation and head posture outline.
  - Live animated Web Audio volume meter (0–100% and dBFS indicator) with peak level tracking.
  - Network tests:
    - Round-trip ping latency (`GET /session/ping`, averages 3 pings).
    - Upload speed test (`POST /session/speed-test`, measures payload transfer in Mbps).
  - Categorized troubleshooting guidance with actionable resolution tips:
    - Permission Denied (`NotAllowedError`)
    - No Device Found (`NotFoundError`)
    - Device in Use (`NotReadableError` / competing software like Zoom/Teams)
    - Poor Network (>300ms latency or <0.5 Mbps bandwidth)
    - "Retry Diagnostics" button.
- **30-Second Baseline Calibration**:
  - User reads calibration sentence: *"I am ready to begin my interview with IntervAI, showcasing my system design, technical problem-solving, and communication skills."*
  - 30-second countdown timer with visual progress bar and real-time posture indicators.
  - Telemetry capture:
    - Face baseline (neutral expression 95%, center gaze alignment x=0.5, y=0.5, head pitch/yaw/roll).
    - Voice baseline (average volume in dBFS, pitch range in Hz, estimated speaking rate).
    - Ambient noise floor level (dBFS).
  - Model `SessionCalibration` linked to `interview_sessions.id`.
  - Endpoints: `POST /session/{id}/calibration` & `GET /session/{id}/calibration`.
- **Session Creation & WebSocket Streaming Connection**:
  - Model `InterviewSession` (`id`, `user_id`, `interview_id`, `status`, `session_token`, `started_at`, `ended_at`, `created_at`).
  - Alembic migration `fcb8b598a2e6` applied.
  - Endpoints: `POST /session` (creates session, validates consent, returns `id`, `session_token`, and `ws_url`) & `GET /session/{id}`.
  - WebSocket endpoint `@router.websocket("/session/{id}/stream")`:
    - Authenticates via query parameter `?token=...`.
    - Handles ping/pong, JSON events, and `MediaRecorder` video chunks (binary and base64).
    - Dispatches chunk acknowledgments (`chunk_ack`).
  - Client opens connection and smoothly navigates to `/interview/live/{session.id}`.
- **Test Suite**: `test_preinterview_phase3_1.py` (7/7 tests passed).

---

## 6. Project Phase Status Summary
- **Phase 1**: Authentication, Profile Onboarding, CV Extraction, Structuring, Canonical DB (Complete & Verified)
- **Phase 2**: Setup & Memory, Blueprint Builder, Question Pool & Deduplicated Bank (Complete & Verified)
- **Phase 3.1**: Pre-Interview Check, Consent, Calibration & Session (Complete & Verified)
- **Phase 3.2**: Next Phase (Interactive live turn-taking, speech-to-text audio pipeline, dynamic follow-up questioning).




