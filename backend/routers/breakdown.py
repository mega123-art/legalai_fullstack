from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services import search_service, gemini_service, db_service

router = APIRouter()


class BreakdownRequest(BaseModel):
    case_id: str      # top-level `id` hash from Pinecone metadata
    year: int         # needed to scope the folder scan


def _build_meta(case_data: dict, year_fallback: int) -> dict:
    return {
        "case_id":   case_data.get("case_id", ""),
        "id":        case_data.get("id", ""),
        "citation":  case_data.get("citation", ""),
        "title":     case_data.get("title", ""),
        "petitioner": case_data.get("petitioner", ""),
        "respondent": case_data.get("respondent", ""),
        "judges":    case_data.get("judges", ""),
        "date":      case_data.get("date", ""),
        "year":      case_data.get("year", year_fallback),
        "outcome":   case_data.get("outcome", ""),
        "court":     case_data.get("court", "Supreme Court of India"),
    }


def _attach_meta(result: dict, case_data: dict, year_fallback: int) -> dict:
    result["meta"] = _build_meta(case_data, year_fallback)
    return result


# ── Non-streaming (legacy + used by export) ───────────────────

@router.post("/api/breakdown")
async def breakdown(req: BreakdownRequest):
    case_data = search_service.load_case_json(req.case_id, req.year)
    if not case_data:
        raise HTTPException(
            status_code=404,
            detail=f"Case file not found for id={req.case_id} year={req.year}",
        )

    cached = await db_service.get_cached_breakdown(req.case_id)
    if cached:
        cached["_cached"] = True
        return _attach_meta(cached, case_data, req.year)

    full_text = search_service.get_full_text(case_data, max_chars=20_000)
    result = await gemini_service.get_breakdown(full_text)

    is_error = (result.get("facts", "").startswith("Error generating") or
                not result.get("facts"))
    if not is_error:
        try:
            await db_service.set_cached_breakdown(req.case_id, req.year, result)
        except Exception as e:
            print(f"[breakdown] cache write failed: {e}")

    result["_cached"] = False
    return _attach_meta(result, case_data, req.year)


# ── Streaming SSE ─────────────────────────────────────────────

def _sse(event: str | None, data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data)
    # Escape newlines so SSE stays on one data: line
    safe = payload.replace("\r", "").replace("\n", "\\n")
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {safe}\n\n"


async def _stream_breakdown(case_data: dict, case_id: str, year: int) -> AsyncGenerator[str, None]:
    meta = _build_meta(case_data, year)

    # Meta first so UI can paint the header immediately
    yield _sse("meta", {"meta": meta, "cached": False})

    full_text = search_service.get_full_text(case_data, max_chars=20_000)

    accumulated: list[str] = []
    try:
        async for token in gemini_service.stream_breakdown(full_text):
            accumulated.append(token)
            yield _sse("token", token)
    except Exception as e:
        yield _sse("error", {"message": str(e)})
        yield _sse(None, "[DONE]")
        return

    # Parse + cache + emit final normalised object
    raw = "".join(accumulated)
    parsed = gemini_service._extract_json(raw)
    if parsed:
        normalised = gemini_service._normalise(parsed)
        try:
            await db_service.set_cached_breakdown(case_id, year, normalised)
        except Exception as e:
            print(f"[breakdown/stream] cache write failed: {e}")
        yield _sse("final", normalised)
    else:
        yield _sse("error", {"message": "Could not parse breakdown JSON"})

    yield _sse(None, "[DONE]")


async def _replay_cached(cached: dict, case_data: dict, year: int) -> AsyncGenerator[str, None]:
    meta = _build_meta(case_data, year)
    yield _sse("meta", {"meta": meta, "cached": True})
    yield _sse("final", cached)
    yield _sse(None, "[DONE]")


@router.post("/api/breakdown/stream")
async def breakdown_stream(req: BreakdownRequest):
    case_data = search_service.load_case_json(req.case_id, req.year)
    if not case_data:
        raise HTTPException(
            status_code=404,
            detail=f"Case file not found for id={req.case_id} year={req.year}",
        )

    cached = await db_service.get_cached_breakdown(req.case_id)
    if cached:
        return StreamingResponse(
            _replay_cached(cached, case_data, req.year),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return StreamingResponse(
        _stream_breakdown(case_data, req.case_id, req.year),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
