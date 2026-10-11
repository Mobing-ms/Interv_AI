# IntervAI — Public Deployment Guide (Production & Student Friendly)

This guide provides end-to-end instructions for deploying IntervAI to the public web with production-grade security, automatic HTTPS, WebSocket streaming, cloud database, and object storage.

---

## 1. Architecture Comparison & Recommendations

### Option (a): Managed Cloud & Serverless (Recommended for Student Projects)
*Best for zero-maintenance, zero/near-zero cost, and automated continuous deployment.*

| Component | Recommended Platform | Free Tier Limits | Trade-offs |
| :--- | :--- | :--- | :--- |
| **Frontend** | [Vercel](https://vercel.com) or [Netlify](https://netlify.com) | 100 GB bandwidth/mo, unlimited deployments, automatic wildcard HTTPS | Global edge CDN, instantaneous rollouts, zero server management. |
| **Backend & Worker** | [Render](https://render.com) or [Railway](https://railway.app) | Render: 750 free hours/mo; Railway: \$5 free trial | Render free tier spins down after 15 min of inactivity (50s cold start). Railway stays hot. |
| **Database** | [Neon Postgres](https://neon.tech) | 0.5 GB storage, serverless compute, auto-suspend | Instant branching, serverless connection pooling, daily backups. |
| **Cache / State** | [Upstash Redis](https://upstash.com) | 10,000 commands/day free forever | Serverless Redis, REST & TCP protocol, zero cluster administration. |
| **Object Storage** | [Cloudflare R2](https://www.cloudflare.com/products/r2/) | 10 GB storage free/mo, **\$0 egress fees** | Fully S3-compatible, presigned URLs, zero bandwidth egress charges. |

### Option (b): Single Linux VPS with Docker Compose
*Best for predictable performance, no cold starts, and all components running together.*

- **Hardware**: Hetzner CX22 (€3.79/mo) or DigitalOcean Droplet (\$6/mo) with 2 vCPUs, 4GB RAM, and 40GB SSD.
- **Stack**: Docker + Docker Compose running `postgres`, `redis`, `backend`, `worker`, and `caddy` (automatic Let's Encrypt SSL reverse proxy).
- **Trade-offs**: Requires setting up SSH keys, firewall (`ufw`), and automated database backups (`pg_dump` cron). No cold starts.

---

## 2. Honest Assessment: Whisper & MediaPipe on Free Tiers

> [!WARNING]
> **Can Free Tiers Run Local Whisper and MediaPipe?**
> **No.** Running local Whisper (`openai-whisper` or `faster-whisper`) on a 512MB RAM free tier (Render, Railway Free, Fly.io Free) will **immediately crash with `OOMKilled (exit code 137)`**. Loading the smallest Whisper model requires 400MB–800MB RAM plus PyTorch runtime overhead. Furthermore, running transcription on a single shared vCPU takes 10–20 seconds at 100% CPU, which blocks the Python asyncio event loop and drops candidate WebSocket connections.

### The Production Solution for Students:
1. **Speech-to-Text (STT)**: Use **[Groq Cloud Whisper API](https://console.groq.com)**:
   - **Cost**: 100% **Free** (up to 7,200 audio transcription requests/day, no credit card required).
   - **Speed**: Sub-300ms latency (~20x faster than real-time).
   - **Server Impact**: Consumes **0 MB RAM** and **0% CPU** on your backend server.
   - **Configuration**: Set `STT_PROVIDER=groq` and `STT_API_KEY=gsk_...` in your backend environment variables.
2. **Video Analysis**:
   - IntervAI samples webcam frames at **1 frame per second (1 fps)** and runs lightweight face/posture heuristics.
   - Uses $< 2\%$ CPU on standard cloud instances without overloading resources.

---

## 3. Step-by-Step Deployment: Option (a) Managed Cloud

### Step 1: Provision Cloud Database & Redis
1. **Neon Serverless Postgres**:
   - Sign up at [neon.tech](https://neon.tech) and create a project named `intervai`.
   - Copy the connection string:
     ```text
     postgresql://user:password@ep-xyz.us-east-2.aws.neon.tech/intervai?sslmode=require
     ```
2. **Upstash Redis**:
   - Sign up at [upstash.com](https://upstash.com) and create a Redis database.
   - Copy the Redis URI (format: `rediss://default:token@xyz.upstash.io:6379`).
3. **Cloudflare R2 Object Storage**:
   - In Cloudflare Dashboard $\to$ **R2** $\to$ Create bucket: `intervai-recordings`.
   - Go to **Manage R2 API Tokens** $\to$ Create API Token with *Object Read & Write* permissions.
   - Copy:
     - Access Key ID
     - Secret Access Key
     - S3 Endpoint URL (e.g. `https://<account_id>.r2.cloudflarestorage.com`)

---

### Step 2: Deploy Backend & Worker on Render

1. Sign up at [render.com](https://render.com) and click **New +** $\to$ **Web Service**.
2. Connect your GitHub repository: `https://github.com/Mobing-ms/Interv_AI.git`.
3. Configure settings:
   - **Name**: `intervai-backend`
   - **Root Directory**: `backend`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt && python run_migrations.py`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add Environment Variables in Render Dashboard:

| Variable Name | Production Value |
| :--- | :--- |
| `ENV` | `production` |
| `DEBUG` | `false` |
| `DEV_MODE` | `false` |
| `DATABASE_URL` | `postgresql://user:password@ep-xyz.../intervai?sslmode=require` |
| `REDIS_URL` | `rediss://default:token@xyz.upstash.io:6379` |
| `JWT_SECRET_KEY` | *(Generate via `openssl rand -hex 32`)* |
| `PUBLIC_API_URL` | `https://intervai-backend.onrender.com` |
| `CORS_ORIGINS` | `https://your-frontend.vercel.app` |
| `STORAGE_BACKEND` | `s3` |
| `S3_ENDPOINT_URL` | `https://<account_id>.r2.cloudflarestorage.com` |
| `S3_ACCESS_KEY_ID` | `<your-cloudflare-r2-access-key-id>` |
| `S3_SECRET_ACCESS_KEY` | `<your-cloudflare-r2-secret-key>` |
| `S3_BUCKET_NAME` | `intervai-recordings` |
| `STT_PROVIDER` | `groq` |
| `STT_API_KEY` | `gsk_...` *(from console.groq.com)* |
| `LLM_PROVIDER` | `openai` *(or `groq` or `gemini`)* |
| `LLM_API_KEY` | `<your-llm-api-key>` |
| `GOOGLE_CLIENT_ID` | `<your-client-id>.apps.googleusercontent.com` |

5. Click **Create Web Service**. Render will run `python run_migrations.py` on build and launch the API server.
6. Verify deployment by visiting:
   `https://intervai-backend.onrender.com/health` $\to$ Returns `{"status": "healthy"}`.

---

### Step 3: Deploy Frontend on Vercel

1. Sign up at [vercel.com](https://vercel.com) and click **Add New...** $\to$ **Project**.
2. Import repository `https://github.com/Mobing-ms/Interv_AI.git`.
3. Set **Root Directory** to `Interv_AI`.
4. Framework Preset: **Vite**.
5. Add Environment Variables:

| Variable Name | Production Value |
| :--- | :--- |
| `VITE_API_URL` | `https://intervai-backend.onrender.com` |
| `VITE_GOOGLE_CLIENT_ID` | `<your-client-id>.apps.googleusercontent.com` |
| `VITE_TURNSTILE_SITE_KEY` | `1x00000000000000000000AA` *(or Cloudflare Turnstile key)* |

6. Click **Deploy**. Vercel will build the frontend and provide your production URL (e.g., `https://interv-ai.vercel.app`).
7. **Important**: Go back to Render backend environment variables and ensure `CORS_ORIGINS` contains your exact Vercel URL (`https://interv-ai.vercel.app`).

---

## 4. Step-by-Step Deployment: Option (b) Single VPS Docker Compose

### Step 1: Provision Server & Install Docker
```bash
# SSH into your VPS
ssh root@your-server-ip

# Update packages and install Docker + Compose
apt-get update && apt-get install -y docker.io docker-compose-plugin git curl
systemctl enable --now docker
```

### Step 2: Clone Repo & Configure Secrets
```bash
git clone https://github.com/Mobing-ms/Interv_AI.git /opt/intervai
cd /opt/intervai

# Generate secure JWT secret
JWT_SECRET=$(openssl rand -hex 32)

# Create production .env for backend
cat <<EOF > backend/.env
ENV=production
DEBUG=false
DEV_MODE=false
DATABASE_URL=postgresql://postgres:postgrespassword@postgres:5432/intervai
REDIS_URL=redis://redis:6379/0
JWT_SECRET_KEY=$JWT_SECRET
CORS_ORIGINS=https://intervai.yourdomain.com
STORAGE_BACKEND=local
STT_PROVIDER=groq
STT_API_KEY=your_groq_api_key
LLM_PROVIDER=openai
LLM_API_KEY=your_llm_api_key
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
EOF
```

### Step 3: Launch Stack with Automatic Caddy HTTPS
Create `Caddyfile` for automated Let's Encrypt certificates and WebSocket streaming:
```caddy
intervai.yourdomain.com {
    # Reverse proxy backend API and WebSockets
    handle /session/*/stream* {
        reverse_proxy backend:8000
    }
    handle /session/*/live* {
        reverse_proxy backend:8000
    }
    handle /auth/* {
        reverse_proxy backend:8000
    }
    handle /profile/* {
        reverse_proxy backend:8000
    }
    handle /cv/* {
        reverse_proxy backend:8000
    }
    handle /interview/* {
        reverse_proxy backend:8000
    }
    handle /report/* {
        reverse_proxy backend:8000
    }
    handle /guest/* {
        reverse_proxy backend:8000
    }
    handle /health* {
        reverse_proxy backend:8000
    }

    # Serve React Frontend
    handle {
        reverse_proxy frontend:80
    }
}
```

Start the containers:
```bash
docker compose up -d --build
```

---

## 5. Camera, Microphone & Secure WebSockets (`wss://`)

Modern browsers enforce strict security restrictions on multimodal input:
1. **HTTPS is Mandatory**: `navigator.mediaDevices.getUserMedia()` is blocked on all insecure origins (`http://`) except `localhost`. In production, you must have an active SSL/TLS certificate.
2. **Secure WebSockets (`wss://`)**: Connecting to `ws://` from an `https://` origin triggers a `Mixed Content SecurityError`. IntervAI dynamically promotes WebSocket streams to `wss://` whenever served over HTTPS.
3. **Reverse Proxy Headers**: If running behind Nginx, Caddy, Cloudflare, or AWS ALB, ensure the proxy forwards:
   - `X-Forwarded-Proto: https`
   - `X-Forwarded-Host: your-domain.com`
   - `Upgrade: $http_upgrade`
   - `Connection: "upgrade"`

---

## 6. Google Cloud Console OAuth 2.0 Setup

To enable "Continue with Google" in production:

1. Open [Google Cloud Console Credentials](https://console.cloud.google.com/apis/credentials).
2. Select your project and click your **OAuth 2.0 Client ID** (Web application).
3. Under **Authorized JavaScript origins**, click **Add URI** and enter:
   - `https://your-frontend.vercel.app` (or `https://intervai.yourdomain.com`)
   - `http://localhost:5173` *(for local development)*
   - `http://localhost:5174`
4. Under **Authorized redirect URIs**, add:
   - `https://your-frontend.vercel.app`
   - `http://localhost:5173`
5. Go to **OAuth consent screen**:
   - Ensure App Name, User support email, and Developer contact information are filled.
   - If in **Testing** status: Add your Google email address under **Test users**.
   - If launching publicly: Click **Publish App** to switch status to **In production** (eliminates the test user whitelist requirement).
6. Copy the **Client ID** and update:
   - Frontend: `VITE_GOOGLE_CLIENT_ID`
   - Backend: `GOOGLE_CLIENT_ID`

---

## 7. Pre-Launch Production Checklist

Before sharing your public URL, verify each item:

- [ ] **Secrets Rotated**: `JWT_SECRET_KEY` is a cryptographically strong 32+ character hex string generated via `openssl rand -hex 32`. No default or placeholder secrets in `.env`.
- [ ] **Debug Mode Disabled**: `DEBUG=false` and `DEV_MODE=false`. OpenAPI docs (`/docs`, `/redoc`) are hidden from public indexing.
- [ ] **Rate Limiting Active**: `slowapi` limits login, signup, CV upload, and guest creation.
- [ ] **CORS Strict**: `CORS_ORIGINS` contains only your explicit frontend domain (no trailing slashes, no wildcard `*`).
- [ ] **Database Backups Active**: Automated daily snapshots enabled in Neon / Supabase or automated `pg_dump` backup job on VPS.
- [ ] **Object Storage Lifecycle**: Cloudflare R2 / S3 lifecycle rule configured or retention cleanup maintenance endpoint called (`POST /session/maintenance/cleanup-retention`).
- [ ] **Zero PII in Logs**: `PIIRedactionFilter` is active and scrubbing emails, passwords, and tokens.

---

## 8. Post-Deploy Verification Runbook

1. **Health Probe**:
   ```bash
   curl -i https://your-backend-url/health
   # Expected: HTTP 200 with {"status": "healthy", "checks": {"database": {"status": "ok"}, ...}}
   ```
2. **Public Guest Interview**:
   - Open your live site in an Incognito / Private window.
   - Click **"Just practice"** on the landing page.
   - Select role and start interview.
   - Verify camera/microphone permissions prompt without browser mixed-content warnings.
   - Complete 1 question, submit answer, and verify report generated without errors.
3. **Google Sign-In**:
   - Click **"Continue with Google"**.
   - Authenticate with your real Google account.
   - Verify candidate dashboard opens displaying your real name and email.
4. **Data Purge Verification**:
   - Navigate to Settings $\to$ "Delete My Data".
   - Confirm candidate data is purged and database returns clean state.
