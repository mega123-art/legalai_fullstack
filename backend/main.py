from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.db_service import init_db
from services.search_service import init_search
from routers import search, breakdown, summary, sessions, pdf, export


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────
    print("[startup] Initialising database...")
    await init_db()

    print("[startup] Loading InLegalBERT + reranker (this takes ~30s first time)...")
    init_search(local_only=True)   # set local_only=False if models not cached

    yield

    # ── Shutdown ──────────────────────────────────────────────
    print("[shutdown] Goodbye.")


app = FastAPI(
    title="LegalAI API",
    description="Indian Supreme Court judgment search and analysis",
    version="1.0.0",
    lifespan=lifespan,
)

origins = [
    "http://localhost:3000",
    "https://legalai-fullstack.vercel.app",
    "https://legal-ai-seven.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(breakdown.router)
app.include_router(summary.router)
app.include_router(sessions.router)
app.include_router(pdf.router)
app.include_router(export.router)


@app.get("/health")
async def health():
    from services import search_service
    return {
        "status": "ok",
        "search_initialized": search_service._initialized,
        "index_loaded": search_service._index is not None,
        "model_loaded": search_service._bi_model is not None,
    }
