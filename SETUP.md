# LegalAI — Setup Guide

Indian Supreme Court search and analysis. BGE-M3 hybrid search (dense + sparse) on Qdrant Cloud, answers via Gemini Flash.

---

## Architecture

```
User → Frontend (Next.js) → Backend (FastAPI)
                                  ├── BGE-M3 query embed
                                  ├── Qdrant Cloud (429k SC chunks)
                                  ├── BGE reranker
                                  └── Gemini Flash via OpenRouter
```

---

## Prerequisites

| Tool | Version | Install (Linux) |
|------|---------|-----------------|
| Python | 3.11+ | `sudo apt install python3.11 python3-pip` |
| Node.js | 18+ | `sudo apt install nodejs npm` |
| PostgreSQL | 15+ | `sudo apt install postgresql` |
| cloudflared | latest | see Step 5 |

---

## 1. Get the Data (from Parth)

Download `legal_data_for_server.zip` from Google Drive (link from Parth) and extract:

```bash
unzip legal_data_for_server.zip
# Creates: processed/  and  catalog.db
```

Place them wherever you like — you'll point `.env` at them.

---

## 2. Download SC PDFs

PDFs are served from disk for the in-app viewer. Download from public S3:

```bash
chmod +x setup_server.sh
./setup_server.sh
```

Or manually for specific years:

```bash
PDF_DIR="./pdfs"
for year in 2006 2007 2008 2009 2010 2011 2012 2013 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024; do
    mkdir -p "$PDF_DIR/$year"
    curl -L "https://indian-supreme-court-judgments.s3.amazonaws.com/data/tar/year=$year/english/english.tar" \
         -o "$PDF_DIR/$year/english.tar"
    tar -xf "$PDF_DIR/$year/english.tar" -C "$PDF_DIR/$year/"
    rm "$PDF_DIR/$year/english.tar"
done
```

> 2025/2026 not on public S3 (~988 cases). Those cases return "PDF unavailable" — everything else works.

---

## 3. Backend Setup

### Install dependencies

```bash
cd backend
pip3 install -r requirements.txt
```

> First install is heavy (~3GB): BGE-M3, reranker, torch, qdrant-client.

### Download ML models

```bash
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('BAAI/bge-m3')
snapshot_download('BAAI/bge-reranker-v2-m3')
"
```

### Configure `.env`

```bash
cp .env.example .env   # if exists, else create manually
```

Fill `backend/.env`:

```env
# Qdrant Cloud — get from Parth
QDRANT_URL=https://YOUR_CLUSTER.qdrant.io:6333
QDRANT_API_KEY=YOUR_QDRANT_API_KEY

# OpenRouter — get from Parth
OPENROUTER_API_KEY=YOUR_OPENROUTER_API_KEY
OPENROUTER_BREAKDOWN_MODEL=google/gemini-2.5-pro
OPENROUTER_SUMMARY_MODEL=google/gemini-2.5-pro
OPENROUTER_EXPANSION_MODEL=google/gemini-2.0-flash-001

# Data paths — adjust to where you extracted the zip
PDF_BASE_PATH=/path/to/pdfs
PROCESSED_DATA_PATH=/path/to/processed
CATALOG_DB_PATH=/path/to/catalog.db
LEGAL_DATA_PATH=/path/to/legal-data

# Database
DATABASE_URL=postgresql+asyncpg://localhost/legalai

TOP_K_FINAL=5
```

### Create database

```bash
createdb legalai
# Tables auto-create on first backend start
```

### Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Expected startup output:

```
[startup] Initialising database...
[setup] Loading BGE-M3...
[setup] Qdrant connected: https://...qdrant.io:6333
[search_service] BGE-M3 + Qdrant ready.
INFO: Uvicorn running on http://0.0.0.0:8000
```

BGE-M3 loads in ~20–30s on first start.

### Verify

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "bail in PMLA twin conditions"}'
```

---

## 4. Frontend Setup

```bash
cd frontend
npm install
```

Fill `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000   # change to your domain in production
```

Run:

```bash
npm run dev       # development
npm run build && npm start   # production
```

---

## 5. Cloudflare Tunnel (Expose to Internet)

Get tunnel token from Parth (created in Cloudflare Zero Trust dashboard).

### Install cloudflared (Linux)

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
     -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

### Run tunnel

```bash
cloudflared tunnel run --token YOUR_TOKEN_FROM_PARTH
```

### Run as service (stays up after logout/reboot)

```bash
sudo cloudflared service install YOUR_TOKEN_FROM_PARTH
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

Update frontend `.env.local` with the public domain:

```env
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
```

---

## 6. Keep Services Running

```bash
# Backend (nohup)
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > ~/backend.log 2>&1 &

# Frontend (nohup)
cd frontend
npm run build
nohup npm start > ~/frontend.log 2>&1 &

# Check logs
tail -f ~/backend.log
tail -f ~/frontend.log
```

---

## Port Map

| Service | Port |
|---------|------|
| Next.js frontend | 3000 |
| FastAPI backend | 8000 |
| PostgreSQL | 5432 |

---

## What Parth Sends You

| Item | How |
|------|-----|
| `legal_data_for_server.zip` | Google Drive (processed JSONs + catalog.db) |
| Qdrant URL + API key | WhatsApp/Signal |
| OpenRouter API key | WhatsApp/Signal |
| Cloudflare tunnel token | WhatsApp/Signal |

---

## Troubleshooting

**"BGE-M3 model not found"**
→ Run the snapshot_download step above. Set `TRANSFORMERS_OFFLINE=0` if behind a proxy.

**"Qdrant connection refused"**
→ Check `QDRANT_URL` and `QDRANT_API_KEY` in `.env`. URL must include `:6333`.

**"PDF missing on disk"**
→ Run the PDF download script. Check `PDF_BASE_PATH` in `.env` matches where you downloaded.

**"Case not found" on breakdown**
→ `processed/` folder not found or wrong path in `PROCESSED_DATA_PATH`.

**Search returns no results**
→ Qdrant credentials wrong, or BGE-M3 not loaded. Check backend startup logs.

**Cloudflare tunnel won't start**
→ Token expired — ask Parth for a new one from Zero Trust dashboard.
