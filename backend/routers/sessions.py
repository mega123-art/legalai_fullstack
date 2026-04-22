from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services import db_service

router = APIRouter()


# ── Sessions ──────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    user_id: str
    title: Optional[str] = "New Search"


@router.post("/api/sessions")
async def create_session(req: CreateSessionRequest):
    session = await db_service.create_session(req.user_id, req.title)
    return {"session_id": str(session.id), "title": session.title}


@router.get("/api/sessions/{user_id}")
async def get_sessions(user_id: str):
    sessions = await db_service.get_sessions_for_user(user_id)
    return {"sessions": sessions}


class DeleteSessionRequest(BaseModel):
    user_id: str


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, req: DeleteSessionRequest):
    ok = await db_service.delete_session(session_id, req.user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


# ── Messages ──────────────────────────────────────────────────

@router.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str, user_id: str):
    # Verify the session belongs to this user before returning messages
    sessions = await db_service.get_sessions_for_user(user_id)
    owned_ids = {s["id"] for s in sessions}
    if session_id not in owned_ids:
        raise HTTPException(status_code=403, detail="Access denied")
    messages = await db_service.get_messages_for_session(session_id)
    return {"messages": messages}


class SaveMessageRequest(BaseModel):
    role: str        # "user" | "assistant"
    content: dict    # { text } for user; { understood_as, cases } for assistant


@router.post("/api/sessions/{session_id}/messages")
async def save_message(session_id: str, req: SaveMessageRequest):
    if req.role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role must be 'user' or 'assistant'")
    msg = await db_service.save_message(session_id, req.role, req.content)
    return {"id": str(msg.id), "created_at": msg.created_at.isoformat()}


# ── Saved cases ───────────────────────────────────────────────

class SaveCaseRequest(BaseModel):
    user_id: str
    citation: str
    case_id: str
    title: str


@router.post("/api/saved-cases")
async def save_case(req: SaveCaseRequest):
    sc = await db_service.save_case(req.user_id, req.citation, req.case_id, req.title)
    return {"id": str(sc.id)}


@router.get("/api/saved-cases/{user_id}")
async def get_saved_cases(user_id: str):
    cases = await db_service.get_saved_cases(user_id)
    return {"cases": cases}


class UnsaveCaseRequest(BaseModel):
    user_id: str
    case_id: str


@router.delete("/api/saved-cases")
async def unsave_case(req: UnsaveCaseRequest):
    ok = await db_service.unsave_case(req.user_id, req.case_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Saved case not found")
    return {"deleted": True}
