from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services import search_service, llm_service
from services import db_service

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    filter_year: Optional[int] = None
    outcome_filter: Optional[str] = None   # "Allowed" | "Dismissed" (from UI pills)
    historical: bool = False


class SearchResponse(BaseModel):
    understood_as: str
    cases: list[dict]


@router.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Run intelligent search (uses the built-in Gemini expansion from legal_queryfier)
    cases, understood_as = search_service.run_search(
        query=req.query,
        filter_year=req.filter_year,
        historical=req.historical,
        outcome_filter=req.outcome_filter,
    )

    # 3. Persist messages to session if session_id provided
    if req.session_id:
        try:
            await db_service.save_message(
                session_id=req.session_id,
                role="user",
                content={"text": req.query},
            )
            await db_service.save_message(
                session_id=req.session_id,
                role="assistant",
                content={"understood_as": understood_as, "cases": cases},
            )
            # Auto-title the session from first query (40 char max)
            title = req.query.strip()[:40]
            await db_service.update_session_title(req.session_id, title)
        except Exception as e:
            # Don't fail the search just because DB write failed
            print(f"[search] DB persistence failed: {e}")

    return SearchResponse(understood_as=understood_as, cases=cases)
