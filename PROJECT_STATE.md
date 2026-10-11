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

## 6. Phase 4 Accomplishments & Architecture

### Phase 4.1: Interview Session Orchestrator (Core State Machine & WebSocket Protocol) (100% Complete & Verified)
- **State Machine per Session**:
  - Full autonomous + reactive turn-taking state machine: `GREETING` → `WARMUP` → `ASKING` → `LISTENING` → `EVALUATING` → `ROUTING` → `CLOSING` → `ENDED`, with unified `ERROR` handling.
  - Enforces smooth progression through interview rounds with duration and difficulty constraints.
- **Redis Session State Persistence**:
  - Real-time serialization to Redis (`SessionStateData`):
    - `current_question`: Active question dictionary (`id`, `text`, `time_limit`, `topic`, `subtopic`, `difficulty`, `is_follow_up`).
    - `topic`: Current domain area.
    - `follow_up_count_per_topic`: Follow-up tracker (strictly enforcing max 2 follow-ups per topic).
    - `elapsed_time`: High-precision timer tracking session progression.
    - `session_context`: History list of asked questions, candidate answers, scores, feedback, and key points covered.
    - `integrity_events`: Telemetry log of tab switches, gaze tracking lost, etc.
  - Seamless fallback to embedded FakeRedis if standalone Redis instance is not running on developer machines.
- **WebSocket Protocol (Server ⇄ Client Events)**:
  - **Server → Client**: `avatar_speak` (text, audio_url), `question` (id, text, time_limit), `nudge`, `redirect`, `round_end`, `state_sync`, `heartbeat_ack`, `connected`, `chunk_ack`, `binary_chunk_ack`, `pong`, `error`.
  - **Client → Server**: `audio_chunk`, `video_frame`, `answer_started`, `answer_ended`, `integrity_event`, `heartbeat`, `ping`, `media_chunk`.
- **Reconnection Resilience & Heartbeat Handling**:
  - Network drops mid-interview preserve exact state in Redis.
  - Reconnecting client sends auth token and receives `connected(resumed=True)` and `state_sync`.
  - Re-surfaces current question without losing previous Q/A history or restarting the round.
  - Heartbeat monitor updates `last_heartbeat` timestamp and detects timeouts.
- **Pluggable Architecture & Testable Interfaces**:
  - `QuestionSelectorProtocol` + `StubQuestionSelector`
  - `TTSModuleProtocol` + `StubTTS`
  - `EvaluatorModuleProtocol` + `StubEvaluator`
  - `RouterModuleProtocol` + `StubRouter`
- **Endpoints**:
  - `GET /session/{id}/state`: Read current Redis session state.
  - `WebSocket /session/{id}/live`: Dedicated full orchestrator WebSocket endpoint.
  - `WebSocket /session/{id}/stream?orchestrate=true`: Dual-mode streaming endpoint.
- **Verification**:
  - `test_orchestrator_phase4_1.py`: 5/5 unit & integration tests passing (scripted fake client full session, dropped connection recovery, pressure mode countdowns, integrity events, stream flag delegation).

### Phase 4.2: Interviewer Side (Avatar Greeting, Question Selector & TTS Service) (100% Complete & Verified)
- **Avatar Greeting & Warmup**:
  - Contextual candidate greeting generated from name and target role.
  - Standardized warmup inquiry: "Tell me about yourself and your background."
  - Animated avatar with interactive states: `speaking`, `listening`, `thinking`.
- **Question Selector Service (`select_next_question`)**:
  - Weighted selection by blueprint topic weights, current difficulty curve, and CV relevance priority.
  - Pending follow-up prioritization and strict question de-duplication against `session_context`.
- **Text-to-Speech (TTS) Service**:
  - Provider abstraction with gTTS provider and browser SpeechSynthesis fallback.
  - Audio caching (`/session/tts/audio/{hash}.mp3`), subtitles generation, and audio endpoint `GET /session/tts/audio/{filename}`.
- **Frontend Playback Ready Signal**:
  - Subtitle display synchronized with speech audio.
  - Audio playback completion dispatches `client_ready`, starting orchestrator answer recording and countdown timer.
- **Verification**: `test_interviewer_phase4_2.py` (8/8 tests passed).

---

### Phase 4.3: Answer Capture (VAD, Streaming STT, 8s Silence Nudge & Storage) (100% Complete & Verified)
- **Audio & Video Streaming**:
  - Frontend records and streams 16 kHz mono PCM chunks via `MediaRecorder` over WebSocket.
  - 1 fps offscreen canvas video frame capture streamed over WebSocket.
  - Visual mic activity meter (`AudioContext` / `AnalyserNode`), countdown timer, and prominent "I'm done" manual backup button.
  - Real-time streaming candidate transcript display (`transcript_update`).
- **8-Second Silence Rule & Hesitation Logging**:
  - Watchdog timer tracks answer duration. If candidate remains silent for 8s, emits gentle rephrase/nudge and records hesitation event in `integrity_events`. Strictly limited to at most one nudge per question.
- **Voice Activity Detection (VAD)**:
  - `VADDetector` combines WebRTC VAD with RMS noise floor gating (`rms < 100.0` prevents false positive noise detections).
  - `VoiceActivityTracker` automatically concludes answer after 2.5s silence with protection against cutting off candidates mid-thought (requires $\ge 1.0$s minimum speech duration).
- **Streaming Speech-to-Text with Word-Level Timestamps**:
  - `StreamingSTTService` outputs transcripts with progressive word timings (`[{"word": ..., "start": ..., "end": ...}]`).
- **Session Artifact Storage Manager**:
  - Persists audio chunks (`audio_chunks/chunk_XXXX.bin`), 1 fps video frames (`frames/frame_XXXX.jpg`), and word-timed transcript (`transcript.json`) under `storage/sessions/{session_id}/{question_id}/`.
  - Accessible via `GET /session/{id}/question/{question_id}/artifacts`.
- **Verification**: `test_answer_capture_phase4_3.py` (7/7 tests passed; 50/50 full regression tests passed).

### Phase 4.4: Evaluator & Dynamic Router (100% Complete & Verified)
- **Evaluation Rubric & LLM Prompt Template (`backend/app/prompts/evaluation_rubric.py`)**:
  - Single, tunable source of truth for evaluation criteria.
  - Multi-dimensional scoring: Relevance (0-10), Correctness (0-10), Depth (0-10), Overall Score (0-10).
  - STAR Completeness rubric for behavioral questions (Situation, Task, Action, Result) with quantified sub-scores.
  - Classification standards: `STRONG`, `OK`, `WEAK_VAGUE`, `OFF_TOPIC`.
  - Justification requirements with mandatory direct transcript quotation.
- **Answer Evaluator (`backend/app/services/evaluator_service.py`)**:
  - Pure Python keyword coverage computed in code (`compute_keyword_coverage`) with case/punctuation normalization and substring/token matching (`matched`, `missing`, `coverage_ratio`).
  - STAR completeness detector (`evaluate_star_completeness`) analyzing behavioral structure.
  - Low-temperature LLM scoring with fallback to `deterministic_evaluate` for reproducible offline operation.
  - Appends full validated evaluation breakdown to persistent `session_context`.
- **Pure Router Decision Logic (`backend/app/services/router_service.py`)**:
  - Pure function `decide_route(state, last_eval, blueprint)` implementing branching:
    - `WEAK_VAGUE`: Generates targeted probing follow-up from answer gap, strictly enforcing $\le 2$ follow-ups per topic (`probing_follow_up`).
    - `STRONG`: Raises difficulty (`Easy` → `Medium` → `Hard`) or deepens technical exploration on the same topic.
    - `OFF_TOPIC`: Politely redirects candidate and repeats original question once (`redirect`).
    - Topic Done: Advances to next blueprint topic when question allocation is met.
    - Round Done: Assesses elapsed time, target question count, or topic coverage; routes to `close`.
- **Closing & Candidate Q&A Handling**:
  - "Any questions for us?" wrap-up handling with `handle_closing_inquiry` (culture, tech stack, general questions) followed by thank-you and clean session termination (`status = "completed"`).
- **Verification**: `test_evaluator_router_phase4_4.py` (9/9 tests passed; 59/59 full regression tests passed).

### Phase 4.5: Parallel Signal Workers & Time-Series Telemetry Store (100% Complete & Verified)
- **Video Signal Worker (1 fps)**:
  - Non-blocking frame analysis using landmark geometry and MediaPipe face mesh with dynamic fallback.
  - Per-frame metrics: `face_present`, `eye_contact` (vs calibration baseline), `head_yaw`, `head_pitch`, `head_roll`, `emotion_valence`, `posture_alignment`, `movement_level` (fidgeting displacement).
- **Audio Signal Worker (16 kHz chunks)**:
  - Non-blocking audio analysis computing `volume_rms` (RMS volume in dB), `pitch_hz` (autocorrelation pitch tracker), `speech_pace_wpm` (from streaming STT timings), `filler_count` & `filler_rate` (regex matching "um", "uh", "like", "you know", "basically", etc.), `pause_count`, and `clarity_proxy`.
- **Time-Series Telemetry Store (`signal_time_series`)**:
  - Model `SignalTimeSeries`: `session_id`, `question_id`, `timestamp`, `metric`, `value`, `extra_data`.
  - Compound indexes for efficient real-time lookups: `ix_signal_sess_q_ts` (`session_id`, `question_id`, `timestamp`) and `ix_signal_sess_metric` (`session_id`, `metric`).
  - In-memory cache + asynchronous batch flusher (`SignalBatchStore`).
- **Asynchronous Processing & Backpressure**:
  - `ParallelSignalProcessor` runs worker event loops with bounded queues (`max_video_queue=10`, `max_audio_queue=25`).
  - Drops oldest frames/chunks when saturated rather than stalling or lagging the interview state machine.
- **Debug Endpoints**:
  - `GET /session/{id}/question/{question_id}/signals` and `GET /session/{id}/signals`.
  - Returns per-question video & audio signals, aggregated summary metrics, and side-by-side comparison against calibration baseline (`head_yaw_delta_from_baseline`, `eye_contact_relative_to_baseline`).
- **Verification**: `test_signal_workers_phase4_5.py` (6/6 tests passed; 65/65 full regression tests passed).

### Phase 4.6: Integrity Monitor (Frontend Telemetry, Video Multi-Face/Missing Face Detection, Gentle Warning & Flagging) (100% Complete & Verified)
- **Frontend Telemetry Listeners**:
  - Page Visibility API (`visibilitychange`): detects tab switching and sends `tab_switch`.
  - Window blur listener (`window.addEventListener('blur')`): detects app unfocus and sends `window_blur`.
  - Fullscreen API (`fullscreenchange`): detects fullscreen exit and sends `fullscreen_exit`.
  - Clipboard monitoring (`copy`, `paste`, `cut`): detects external copy/paste attempts and sends `clipboard_copy` / `clipboard_paste`.
  - Streams events via WebSocket with timestamps and active question ID.
- **Backend Video Worker Integrity Detection**:
  - Detects second face in camera view (`multiple_faces`, `severity="HIGH"`).
  - Detects candidate absence/face missing for > N seconds (`face_missing`, configurable threshold e.g. 3.0s).
- **First-Time Gentle Warning**:
  - Emits `integrity_warning` message over WebSocket on first infraction: *"Gentle reminder: Please remain facing the camera in full view and keep this window active."*
  - Subsequent events are recorded silently for the report without spamming the candidate.
- **Threshold Flagging without Auto-Termination**:
  - Does NOT terminate or abort the interview; candidate finishes uninterrupted.
  - Configurable threshold (e.g. 3 events): marks session and report as flagged (`is_flagged = True`, `flag_reasons = [...]`).
- **Data Model & REST Query Endpoints**:
  - Table `integrity_events`: `id`, `session_id`, `question_id`, `type`, `start_time`, `end_time`, `duration_seconds`, `severity`, `details`, `created_at`.
  - `GET /session/{id}/integrity-events` and `GET /session/{id}/integrity`: returns full list of events, aggregated breakdown by type and severity, and threshold flag assessment.
- **Verification**: `test_integrity_monitor_phase4_6.py` (6/6 tests passed; 71/71 full regression tests passed).

---

## 7. Project Phase Status Summary
- **Phase 1**: Authentication, Profile Onboarding, CV Extraction, Structuring, Canonical DB (Complete & Verified)
- **Phase 2**: Setup & Memory, Blueprint Builder, Question Pool & Deduplicated Bank (Complete & Verified)
- **Phase 3**: Pre-Interview Check, Consent, Calibration & Session Lifecycle (Complete & Verified)
- **Phase 4**: Full Live Interview Engine (100% Complete & Verified across all 6 prompts):
  - **4.1**: Session Orchestrator State Machine & WebSocket Protocol
  - **4.2**: Interviewer Side (Avatar Greeting, Question Selector, TTS Engine)
  - **4.3**: Answer Capture (Audio/Video Streaming, VAD, 8s Silence Nudge, Word-Timed STT, Storage)
  - **4.4**: Answer Evaluator (Rubric, Code Keyword Coverage, STAR) & Dynamic Router
  - **4.5**: Parallel Signal Workers (Video & Audio), Time-Series Telemetry Store & Baseline Comparison
  - **4.6**: Integrity Monitor (Frontend Events, Video Multi-Face/Missing Face, Warning, Threshold Flagging)
- **Phase 5**: Post-interview comprehensive evaluation report, analytics, feedback generation.







