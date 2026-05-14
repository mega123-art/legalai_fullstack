import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API keys ──────────────────────────────────────────────────
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# ── Services ──────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/legalai")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# ── Data paths ────────────────────────────────────────────────
PROCESSED_DATA_PATH = Path(
    os.getenv("PROCESSED_DATA_PATH", "/Users/parthagrawal99/legal-data/processed")
)
CATALOG_DB_PATH = Path(
    os.getenv("CATALOG_DB_PATH", "/Users/parthagrawal99/legal-data/catalog.db")
)
LEGAL_DATA_PATH = Path(
    os.getenv("LEGAL_DATA_PATH", "/Users/parthagrawal99/legal-data")
)

# Make existing search scripts importable
if str(LEGAL_DATA_PATH) not in sys.path:
    sys.path.insert(0, str(LEGAL_DATA_PATH))

# ── Search tuning ─────────────────────────────────────────────
TOP_K_FINAL = int(os.getenv("TOP_K_FINAL", "5"))
