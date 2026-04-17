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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
    return {"status": "ok"}
