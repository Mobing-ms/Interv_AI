# IntervAI — Autonomous AI Interview Coaching Platform

IntervAI is an enterprise-grade multimodal AI interview coaching platform. It provides real-time state machine orchestration, facial presence tracking, speech fluency analysis, rubric-based content evaluation, grounded report synthesis with claim verification, and personalized weak-area improvement plans.

---

## Architecture Overview

```
                      +---------------------------------------+
                      |       React 19 + Vite Frontend        |
                      | (Audio/Video Streams, WebSockets, UI) |
                      +-------------------+-------------------+
                                          |
                        HTTP / REST       |   WebSocket Stream
                       (Port 8000)        |    (Live Pipeline)
                                          v
                      +---------------------------------------+
                      |         FastAPI Core Backend          |
                      |  - State Machine Orchestrator         |
                      |  - Multi-Modal Signal Analyzers       |
                      |  - Score Fusion & Comparison Engine   |
                      |  - 3-Pass Grounded Report Generator   |
                      +-------------------+-------------------+
                                          |
                +-------------------------+-------------------------+
                |                                                   |
                v                                                   v
+-------------------------------+                   +-------------------------------+
|    Database (SQLite / PG)     |                   |    Redis Queue / State Store  |
|  - Users, Profiles, CVs       |                   |  - Real-time Session State    |
|  - Sessions, Reports, Memory  |                   |  - Idempotent Analysis Jobs   |
+-------------------------------+                   +-------------------------------+
```

---

## Prerequisites

- **Python**: 3.11 or higher
- **Node.js**: 18.x or higher (`npm` 9+)
- **Redis** *(Optional)*: `redis://localhost:6379` (In-memory fallback operates automatically if Redis is offline)

---

## Setup & Run Instructions

### 1. Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

**Key `.env` Configurations:**
```ini
DATABASE_URL=sqlite:///./intervai.db
JWT_SECRET_KEY=intervai-super-secret-jwt-key-2026-production-ready
RECORDING_RETENTION_DAYS=30
GUEST_RETENTION_HOURS=24
LLM_PROVIDER=groq          # Options: "mock", "groq", "openai", "gemini" (see API keys below)
LLM_API_KEY=               # Your provider key
GOOGLE_CLIENT_ID=          # Google OAuth Web Client ID
TURNSTILE_SECRET_KEY=      # Cloudflare Turnstile secret key
```

**API keys (where they go):**

All keys go in `backend/.env` (copied from `backend/.env.example` above). That file is git-ignored, so keys never get committed. Without keys the app still runs, but on `mock` providers: canned questions, heuristic grading and no real transcription.

One free [Groq](https://console.groq.com/keys) key covers both the interviewer (LLM) and speech-to-text:

```ini
# backend/.env
LLM_PROVIDER=groq
LLM_MODEL=openai/gpt-oss-20b         # generates questions, grades answers, writes follow-ups
LLM_API_KEY=gsk_your_groq_key

STT_PROVIDER=groq
STT_MODEL=whisper-large-v3-turbo     # transcribes each spoken answer
STT_API_KEY=gsk_your_groq_key        # can be the same key
```

| Key | What it's for | Needed? |
|---|---|---|
| `LLM_API_KEY` | Questions, grading, Ava's reactions and follow-ups | Yes, for a real interview (`mock` otherwise) |
| `STT_API_KEY` | Whisper transcription of spoken answers | Recommended; without it only the browser's live transcript (Chrome) is used |
| `JWT_SECRET_KEY` | Signs login tokens | Set any long random string; if empty, logins reset on every restart |
| `GOOGLE_CLIENT_ID` | "Continue with Google" | Optional |
| `TURNSTILE_SECRET_KEY` | Bot check on guest mode | Optional in development, required in production |

Restart the backend after changing `.env`. The free Groq tier rate-limits (HTTP 429); the app retries once and then falls back to its built-in rules for that answer.

**Apply Migrations & Seed Demo Data:**
```bash
# Run database migrations
python migrate.py

# Seed realistic candidate with 3 completed sessions & radar analytics
python seed_demo_data.py
```
> **Default Demo Login:**  
> **Email:** `alex@example.com`  
> **Password:** `Password123!`

**Start the Backend Server:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
API Documentation will be available at [http://localhost:8000/docs](http://localhost:8000/docs).

---

### 2. Frontend Setup

```bash
cd Interv_AI

# Install dependencies
npm install

# Configure environment variables
cp .env.example .env
```

**Frontend `.env`:**
```ini
VITE_API_BASE_URL=http://localhost:8000   # no API keys go in the frontend; they stay in backend/.env
VITE_GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
VITE_TURNSTILE_SITE_KEY=1x00000000000000000000AA
```

**Start the Frontend Dev Server:**
```bash
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

### 3. Background Worker & Queue Execution

IntervAI supports both synchronous pipeline processing (for local testing) and Celery/RQ workers:
```bash
# Optional: Celery analysis worker (if Redis queue is active)
celery -A app.services.analysis_pipeline worker --loglevel=info
```
If no Celery worker is present, the pipeline executes synchronously or via background tasks without dropping jobs.

---

## Testing & Verification

### Run End-to-End Test Suite
Executes the full candidate lifecycle (Registration -> Profile Confirmation -> CV Parsing -> Pre-Check -> 3-Question Scripted Interview -> Analysis Pipeline -> Grounded Report -> Retake Loop -> GDPR Delete Data):
```bash
cd backend
.\venv\Scripts\python.exe -m unittest test_e2e_full_flow.py
```

### Run All Unit & Feature Tests
```bash
cd backend
.\venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py"
```

### Verify Frontend Build
```bash
cd Interv_AI
npm run build
```

---

## Error Handling & Resilience Matrix

| Failure Mode | Backend Handler & Fallback | User-Facing Notification | Structured Logging |
| :--- | :--- | :--- | :--- |
| **Invalid / Corrupted CV** | `cv_extractor.py`: Multi-parser cascade (pdfplumber -> PyPDF2 -> pypdf -> OCR). Rejects password-protected or unreadable files with HTTP 400. | Actionable alert with error code (`ENCRYPTED`, `UNREADABLE`, `TOO_LARGE`). | `[CV][cv_id=X][user_id=Y]` |
| **Device / Network Failure** | Pre-check diagnostics (`/session/ping`, `/session/speed-test`). Re-tests hardware with troubleshooting modals. | Modal instructions on microphone/camera permissions and latency thresholds (<150ms). | `[Precheck][session_id=X]` |
| **Silence / Hesitation** | `SilenceNudgeDetector`: 8.0s continuous silence detector emits gentle empathetic nudge. | Avatar subtitles: *"Take your time, let me know if you want me to repeat the question."* | `[Orchestrator][session_id=X]` |
| **STT or LLM Provider Drop** | `evaluator_service.py`: Low-temperature LLM scoring with automatic fallback to deterministic rubric rule engine. Network timeouts retry with exponential backoff. | Seamless transition without halting the interview; candidate sees continuous evaluation. | `[LLM][session_id=X]` |
| **WebSocket Stream Drop** | Frontend `ws.onclose` exponential backoff reconnect loop (2s, 4s, 8s...). Backend restores question and timer state from Redis. | Toast: *"Live stream disconnected. Reconnecting in 2s..."* followed by reconnection toast. | `[SessionState][session_id=X]` |
| **Queue / Analysis Failure** | `analysis_pipeline.py`: Idempotent job deduplication (`session_analysis:{id}`) with 3 exponential backoff retries. Broken modules marked as `is_partial`. | Real-time polling screen with step progress; report writer displays missing section notice. | `[AnalysisJob][session_id=X]` |
| **Report Grounding Failure** | `report_generator_service.py`: 2-pass claim verification against transcript & scores. Flags unsupported claims; regenerates up to 2 rounds, then drops hallucinated claims. | Report displays verified evidence references; ungrounded statements are discarded. | `[Grounding][session_id=X]` |

---

## Privacy & Security Hardening

- **Authorization & IDOR Protection**: All endpoints verify ownership (`session.user_id == current_user.id` or signed guest token matching `session.guest_id`).
- **Expiring Signed Recording URLs**: Audio and video media access requires cryptographically signed HMAC-SHA256 URLs with 1-hour expiration (`/session/{id}/recording/{type}?expires=...&sig=...`).
- **Data Retention & Scheduled Cleanup**:
  - Registered user recordings: Retained for 30 days (`settings.RECORDING_RETENTION_DAYS`), then purged by `cleanup_all_expired_recordings`.
  - Anonymous guest data: Purged automatically after 24 hours (`settings.GUEST_RETENTION_HOURS`).
  - Endpoint: `POST /session/maintenance/cleanup-retention`.
- **GDPR / CCPA "Delete My Data"**: `DELETE /profile/me/data` permanently purges all uploaded CV files, audio/video recordings, sessions, reports, user memory, and consent records.
- **Strict Security Headers**: Applied to all HTTP responses:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `Content-Security-Policy: default-src 'self'; frame-ancestors 'none';`
  - `Referrer-Policy: strict-origin-when-cross-origin`
- **Zero PII in Logs**: `PIIRedactionFilter` automatically redacts email addresses, phone numbers, auth tokens, and passwords from all application logs.
