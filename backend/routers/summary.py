from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import AsyncGenerator

from services import search_service, llm_service, db_service

router = APIRouter()


class SummaryRequest(BaseModel):
    case_id: str   # top-level `id` hash
    year: int


async def _replay_cached(text: str) -> AsyncGenerator[str, None]:
    """Yield a cached summary as a single SSE block, then DONE."""
    safe = text.replace("\n", "\\n")
    yield f"data: {safe}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_and_cache(
    case_id: str, year: int, headnote: str, judgment_text: str
) -> AsyncGenerator[str, None]:
    """Stream from LLM, accumulate tokens, persist once [DONE] arrives."""
    accumulated: list[str] = []
    async for line in llm_service.stream_summary(headnote, judgment_text):
        # Sniff tokens for local caching (don't interfere with SSE formatting)
        if line.startswith("data: ") and not line.startswith("data: [DONE]"):
            payload = line[len("data: "):].rstrip("\n")
            accumulated.append(payload.replace("\\n", "\n"))
        yield line

    full_text = "".join(accumulated).strip()
    # Don't cache error fallback payloads
    if full_text and "unavailable" not in full_text.lower()[:60]:
        try:
            await db_service.set_cached_summary(case_id, year, full_text)
        except Exception as e:
            print(f"[summary] cache write failed: {e}")


@router.post("/api/summary")
async def summary(req: SummaryRequest):
    case_data = search_service.load_case_json(req.case_id, req.year)
    if not case_data:
        raise HTTPException(
            status_code=404,
            detail=f"Case not found for id={req.case_id} year={req.year}",
        )

    # Cache hit → replay instantly
    cached = await db_service.get_cached_summary(req.case_id)
    if cached:
        return StreamingResponse(
            _replay_cached(cached),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    headnote = case_data.get("headnotes", "")
    chunks = case_data.get("chunks", []) or []
    judgment_text = " ".join(
        c.get("text", "") for c in chunks[1:3] if isinstance(c, dict)
    )

    return StreamingResponse(
        _stream_and_cache(req.case_id, req.year, headnote, judgment_text),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
