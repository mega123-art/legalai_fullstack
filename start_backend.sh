#!/bin/bash
set -e

BACKEND_DIR="$(cd "$(dirname "$0")/backend" && pwd)"
VENV="$BACKEND_DIR/venv"

echo "[*] Clearing Python caches..."
find "$BACKEND_DIR" -name "__pycache__" -not -path "*/venv/*" -type d -exec rm -rf {} + 2>/dev/null || true

echo "[*] Activating venv..."
source "$VENV/bin/activate"

echo "[*] Starting backend..."
cd "$BACKEND_DIR"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
