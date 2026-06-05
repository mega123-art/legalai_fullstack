#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Legal AI — Server Setup Script
# Run once on school server to download all required data.
#
# Usage:
#   chmod +x setup_server.sh
#   ./setup_server.sh
#
# Requirements: curl, python3, pip3
# ─────────────────────────────────────────────────────────────

set -e

# ── Config — change these if needed ──────────────────────────
PDF_DIR="$(pwd)/pdfs"
PROCESSED_DIR="$(pwd)/processed"   # copy your processed/ JSONs here
CATALOG_DB="$(pwd)/catalog.db"     # copy catalog.db here

echo "================================================"
echo " Legal AI Server Setup"
echo " PDF dir    : $PDF_DIR"
echo " Processed  : $PROCESSED_DIR"
echo "================================================"
echo ""

# ── Step 1: Download SC PDFs from public S3 ──────────────────
echo "[1/4] Downloading Supreme Court PDFs (2006–2024)..."
echo "      This will take 30–60 min depending on connection."
echo ""

SC_S3="https://indian-supreme-court-judgments.s3.amazonaws.com/data/tar/year"
YEARS=(2006 2007 2008 2009 2010 2011 2012 2013 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024)

for year in "${YEARS[@]}"; do
    dest="$PDF_DIR/$year"
    mkdir -p "$dest"

    # Skip if already downloaded (has pdf files)
    if ls "$dest"/*.pdf &>/dev/null 2>&1; then
        echo "  [$year] Already have PDFs — skipping"
        continue
    fi

    echo "  [$year] Downloading..."
    url="$SC_S3=$year/english/english.tar"
    tmp="$dest/english.tar"

    if curl -L --silent --show-error --fail "$url" -o "$tmp"; then
        echo "  [$year] Extracting..."
        tar -xf "$tmp" -C "$dest" --strip-components=0 2>/dev/null || tar -xf "$tmp" -C "$dest"
        rm "$tmp"
        count=$(ls "$dest"/*.pdf 2>/dev/null | wc -l)
        echo "  [$year] Done — $count PDFs"
    else
        echo "  [$year] WARNING: Download failed — skipping (year may not be on S3)"
        rm -f "$tmp"
    fi
done

# 2025/2026 not on S3 tarball — skip (small % of corpus)
echo ""
echo "  Note: 2025/2026 PDFs (~988 cases) not available on public S3."
echo "  Those cases will show 'PDF missing' — everything else works."

# ── Step 2: Python dependencies ──────────────────────────────
echo ""
echo "[2/4] Installing Python dependencies..."
pip3 install -r backend/requirements.txt

# ── Step 3: Download HuggingFace models ──────────────────────
echo ""
echo "[3/4] Downloading BGE-M3 + reranker models (~3GB)..."
pip3 install huggingface_hub -q
python3 - <<'PYEOF'
from huggingface_hub import snapshot_download
print("  Downloading BAAI/bge-m3...")
snapshot_download("BAAI/bge-m3")
print("  Downloading BAAI/bge-reranker-v2-m3...")
snapshot_download("BAAI/bge-reranker-v2-m3")
print("  Models downloaded.")
PYEOF

# ── Step 4: Create .env ───────────────────────────────────────
echo ""
echo "[4/4] Creating backend/.env..."

ENV_FILE="backend/.env"
if [ -f "$ENV_FILE" ]; then
    echo "  .env already exists — skipping (edit manually if needed)"
else
    cat > "$ENV_FILE" <<EOF
# Qdrant Cloud — get from Parth
QDRANT_URL=https://YOUR_QDRANT_CLUSTER_URL:6333
QDRANT_API_KEY=YOUR_QDRANT_API_KEY

# OpenRouter — get from Parth
OPENROUTER_API_KEY=YOUR_OPENROUTER_API_KEY
OPENROUTER_BREAKDOWN_MODEL=google/gemini-2.5-pro
OPENROUTER_SUMMARY_MODEL=google/gemini-2.5-pro
OPENROUTER_EXPANSION_MODEL=google/gemini-2.0-flash-001

# Data paths — update if you put data elsewhere
PDF_BASE_PATH=$(pwd)/pdfs
PROCESSED_DATA_PATH=$(pwd)/processed
CATALOG_DB_PATH=$(pwd)/catalog.db
LEGAL_DATA_PATH=$(pwd)

# DB + misc
DATABASE_URL=postgresql+asyncpg://localhost/legalai
TOP_K_FINAL=5
EOF
    echo "  .env created at $ENV_FILE"
fi

echo ""
echo "================================================"
echo " Setup complete!"
echo ""
echo " Still needed (copy from Parth):"
echo "   processed/   — 1.9GB processed SC JSONs"
echo "   catalog.db   — SQLite BM25 + citation index"
echo ""
echo " Start server:"
echo "   cd backend && uvicorn main:app --host 0.0.0.0 --port 8000"
echo "================================================"
