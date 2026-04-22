from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services import search_service
from services import db_service

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    filter_year: Optional[int] = None       # legacy single-year (kept for compat)
    year_from: Optional[int] = None         # range start (inclusive)
    year_to: Optional[int] = None           # range end (inclusive)
    outcome_filter: Optional[str] = None    # "allowed" | "dismissed"
    historical: bool = False


class SearchResponse(BaseModel):
    understood_as: str
    cases: list[dict]


@router.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Offload sync search (InLegalBERT + Pinecone + reranker) to thread pool
    # so FastAPI event loop is not blocked for concurrent requests
    # Resolve year range: prefer explicit range, fall back to legacy single-year ±2
    year_from = req.year_from
    year_to = req.year_to
    if year_from is None and year_to is None and req.filter_year:
        year_from = req.filter_year - 2
        year_to = req.filter_year + 2

    cases, understood_as = await asyncio.to_thread(
        search_service.run_search,
        query=req.query,
        year_from=year_from,
        year_to=year_to,
        historical=req.historical,
        outcome_filter=req.outcome_filter,
    )

    if req.session_id:
        try:
            title = req.query.strip()[:40]
            await asyncio.gather(
                db_service.save_message(
                    session_id=req.session_id,
                    role="user",
                    content={"text": req.query},
                ),
                db_service.save_message(
                    session_id=req.session_id,
                    role="assistant",
                    content={"understood_as": understood_as, "cases": cases},
                ),
                db_service.update_session_title(req.session_id, title),
            )
        except Exception as e:
            print(f"[search] DB persistence failed: {e}")

    return SearchResponse(understood_as=understood_as, cases=cases)
