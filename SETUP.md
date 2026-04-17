# LegalAI — Setup Guide

Everything needed to run the full stack on Mac Mini M4.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | `brew install python@3.11` |
| Node.js | 18+ | `brew install node` |
| PostgreSQL | 15+ | `brew install postgresql@15 && brew services start postgresql@15` |
| Ollama | latest | `brew install ollama && ollama serve` |
| Llama 3.1 8B | — | `ollama pull llama3.1:8b` |
| Cloudflare Tunnel | latest | `brew install cloudflared` |

### Verify Services Running

```bash
# PostgreSQL
pg_isready
# → accepting connections

# Ollama
curl http://localhost:11434/api/tags
# → {"models":[{"name":"llama3.1:8b",...}]}
```

---

## 1. Database

```bash
createdb legalai
```

Tables auto-create on first backend start (SQLAlchemy `create_all`).

---

## 2. API Keys

### Pinecone
- Dashboard: https://app.pinecone.io
- Copy your API key (same one used in `legal-data/.env`)

### Gemini Flash 2.0
- Dashboard: https://aistudio.google.com/apikey
- Create API key → copy

### Clerk (Auth)
- Dashboard: https://dashboard.clerk.com
- Create application → enable Google OAuth + Email/Password
- Copy **Publishable Key** and **Secret Key**
- Set redirect URLs:
  - Sign-in: `/sign-in`
  - Sign-up: `/sign-up`
  - After sign-in: `/chat`
  - After sign-up: `/chat`

---

## 3. Backend Setup

```bash
cd /Users/parthagrawal99/legal-ai/backend

# Create .env from template
cp .env.example .env
```

### Fill `.env`:

```env
PINECONE_API_KEY=your-pinecone-key
GEMINI_API_KEY=your-gemini-key
DATABASE_URL=postgresql+asyncpg://localhost/legalai
OLLAMA_URL=http://localhost:11434
PROCESSED_DATA_PATH=/Users/parthagrawal99/legal-data/processed
CATALOG_DB_PATH=/Users/parthagrawal99/legal-data/processed/catalog.db
LEGAL_DATA_PATH=/Users/parthagrawal99/legal-data
TOP_K_FINAL=5
```

### Install dependencies:

```bash
pip install -r requirements.txt
```

> **Note:** ML packages (torch, transformers, sentence-transformers, pinecone-client) are already installed system-wide from the data pipeline work. The backend imports them via `sys.path` from `/Users/parthagrawal99/legal-data/`.

### Run:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

First start loads InLegalBERT + reranker (~30s), then:

```
[startup] Loading InLegalBERT + reranker...
[search_service] Models loaded.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Verify:

```bash
curl http://localhost:8000/health
# → {"status":"ok"}

# Test search (takes ~5-10s first time)
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "SARFAESI auction without proper notice"}'
```

---

## 4. Frontend Setup

```bash
cd /Users/parthagrawal99/legal-ai/frontend
```

### Fill `.env.local`:

```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
```

> **Without Clerk keys:** App still works with a demo user. Auth screens won't render but `/chat` is accessible.

### Install & run:

```bash
npm install
npm run dev
```

Open http://localhost:3000 → redirects to `/sign-in` (or `/chat` if Clerk not configured).

---

## 5. Cloudflare Tunnel (Production)

Expose both services through a custom domain.

```bash
# Login (one-time)
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create legalai

# Configure
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: legalai
credentials-file: /Users/parthagrawal99/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: app.yourdomain.com
    service: http://localhost:3000
  - hostname: api.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
EOF

# Add DNS records
cloudflared tunnel route dns legalai app.yourdomain.com
cloudflared tunnel route dns legalai api.yourdomain.com

# Run
cloudflared tunnel run legalai
```

Update frontend `.env.local` for production:
```env
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
```

### Auto-start on boot (launchd):

```bash
cloudflared service install
# This creates a launchd plist that starts the tunnel on boot
```

---

## 6. Mac Mini Always-On

### Keep services running after SSH disconnect:

```bash
# Backend
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > ~/legalai-backend.log 2>&1 &

# Frontend
cd /Users/parthagrawal99/legal-ai/frontend
nohup npm run start -- -p 3000 > ~/legalai-frontend.log 2>&1 &

# Ollama (already a service via brew)
brew services start ollama
```

Or use **launchd plist** for each (recommended):

```bash
# Example: /Library/LaunchDaemons/com.legalai.backend.plist
# Restarts automatically on crash
```

### Prevent sleep:

```bash
sudo pmset -a disablesleep 1
sudo pmset -a sleep 0
```

---

## File Locations

| What | Path |
|------|------|
| Processed case JSONs | `/Users/parthagrawal99/legal-data/processed/{year}/*.json` |
| SQLite catalog | `/Users/parthagrawal99/legal-data/processed/catalog.db` |
| Embedded IDs tracker | `/Users/parthagrawal99/legal-data/embedded_ids.txt` |
| Search scripts | `/Users/parthagrawal99/legal-data/search_pro_*.py` |
| Backend code | `/Users/parthagrawal99/legal-ai/backend/` |
| Frontend code | `/Users/parthagrawal99/legal-ai/frontend/` |
| Backend .env | `/Users/parthagrawal99/legal-ai/backend/.env` |
| Frontend .env | `/Users/parthagrawal99/legal-ai/frontend/.env.local` |

---

## Port Map

| Service | Port | URL |
|---------|------|-----|
| Next.js frontend | 3000 | http://localhost:3000 |
| FastAPI backend | 8000 | http://localhost:8000 |
| PostgreSQL | 5432 | postgresql://localhost/legalai |
| Ollama | 11434 | http://localhost:11434 |

---

## Monthly Costs

| Item | Cost |
|------|------|
| Pinecone (free tier) | ₹0 |
| Gemini Flash 2.0 (~1000 breakdowns/mo) | ~₹400 |
| Custom domain | ~₹70/mo (₹800/yr) |
| Clerk (free tier, 10k MAUs) | ₹0 |
| **Total** | **~₹500/mo** |

---

## Troubleshooting

**Backend won't start — "Pinecone API key not found"**
→ Check `.env` file exists and has `PINECONE_API_KEY` set.

**Backend won't start — "TRANSFORMERS_OFFLINE" error**
→ Models not cached locally. Run once with `--allow-online`:
```bash
# From legal-data dir
python3 search_test.py --allow-online "test query"
```

**"Summary unavailable — Ollama not responding"**
→ Check Ollama running: `curl http://localhost:11434/api/tags`
→ Pull model if missing: `ollama pull llama3.1:8b`

**Clerk redirect loop**
→ Check `NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in` is set in `.env.local`
→ Restart `npm run dev` after changing env vars.

**Breakdown returns fallback (Llama instead of Gemini)**
→ Check `GEMINI_API_KEY` in backend `.env`. Gemini has rate limits on free tier — wait and retry.

**Case not found (404 on breakdown/summary)**
→ `case_id` from Pinecone is the hash ID (e.g. `4f98f1ef122b`), not the INSC citation. Verify with:
```bash
curl -X POST http://localhost:8000/api/breakdown \
  -H "Content-Type: application/json" \
  -d '{"case_id": "4f98f1ef122b", "year": 2022}'
```

**SQLite catalog missing**
→ Rebuild: `cd /Users/parthagrawal99/legal-data && python3 search_pro_intelligent.py --rebuild-catalog`
