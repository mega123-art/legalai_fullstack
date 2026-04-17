"""
Async PostgreSQL operations via SQLAlchemy.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from config import DATABASE_URL
from models.database import Base, User, Session as ChatSession, Message, SavedCase, CaseCache

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


# ── Users ─────────────────────────────────────────────────────

async def upsert_user(clerk_id: str, email: str, name: str) -> User:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.clerk_id == clerk_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(clerk_id=clerk_id, email=email, name=name)
            db.add(user)
        else:
            user.email = email
            user.name = name
        await db.commit()
        await db.refresh(user)
        return user


async def get_user_by_clerk_id(clerk_id: str) -> Optional[User]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.clerk_id == clerk_id))
        return result.scalar_one_or_none()


# ── Sessions ──────────────────────────────────────────────────

async def create_session(user_id: str, title: str = "New Search") -> ChatSession:
    async with AsyncSessionLocal() as db:
        # Auto-sync user if they don't exist (using user_id as email/name placeholders if missing)
        result = await db.execute(select(User).where(User.clerk_id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(clerk_id=user_id, email=f"{user_id}@clerk.user", name="Clerk User")
            db.add(user)
            await db.flush()

        session = ChatSession(user_id=user_id, title=title)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session


async def get_sessions_for_user(user_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(desc(ChatSession.updated_at))
        )
        sessions = result.scalars().all()
        out = []
        for s in sessions:
            # Fetch last message for preview
            msg_result = await db.execute(
                select(Message)
                .where(Message.session_id == s.id)
                .order_by(desc(Message.created_at))
                .limit(1)
            )
            last_msg = msg_result.scalar_one_or_none()
            last_text = ""
            if last_msg and isinstance(last_msg.content, dict):
                last_text = last_msg.content.get("text", "")[:60]
            out.append({
                "id": str(s.id),
                "title": s.title,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat() if s.updated_at else s.created_at.isoformat(),
                "last_message": last_text,
            })
        return out


async def update_session_title(session_id: str, title: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(title=title, updated_at=datetime.utcnow())
        )
        await db.commit()


async def delete_session(session_id: str, user_id: str) -> bool:
    """Delete a session (and its messages via cascade). Returns True if deleted."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            return False
        await db.delete(session)
        await db.commit()
        return True


async def touch_session(session_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(updated_at=datetime.utcnow())
        )
        await db.commit()


# ── Messages ──────────────────────────────────────────────────

async def save_message(session_id: str, role: str, content: dict) -> Message:
    async with AsyncSessionLocal() as db:
        msg = Message(session_id=session_id, role=role, content=content)
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        await touch_session(session_id)
        return msg


async def get_messages_for_session(session_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        return [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]


# ── Saved cases ───────────────────────────────────────────────

async def save_case(user_id: str, citation: str, case_id: str, title: str) -> SavedCase:
    async with AsyncSessionLocal() as db:
        # Auto-sync user
        result = await db.execute(select(User).where(User.clerk_id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(clerk_id=user_id, email=f"{user_id}@clerk.user", name="Clerk User")
            db.add(user)
            await db.flush()

        sc = SavedCase(user_id=user_id, citation=citation, case_id=case_id, title=title)
        db.add(sc)
        await db.commit()
        await db.refresh(sc)
        return sc


# ── Case cache (summary + breakdown) ──────────────────────────

async def get_cached_breakdown(case_id: str) -> Optional[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(CaseCache).where(CaseCache.case_id == case_id))
        row = result.scalar_one_or_none()
        return row.breakdown if row and row.breakdown else None


async def set_cached_breakdown(case_id: str, year: int, breakdown: dict) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(CaseCache).where(CaseCache.case_id == case_id))
        row = result.scalar_one_or_none()
        if row is None:
            row = CaseCache(case_id=case_id, year=year, breakdown=breakdown)
            db.add(row)
        else:
            row.breakdown = breakdown
            row.year = year
        await db.commit()


async def get_cached_summary(case_id: str) -> Optional[str]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(CaseCache).where(CaseCache.case_id == case_id))
        row = result.scalar_one_or_none()
        return row.summary if row and row.summary else None


async def set_cached_summary(case_id: str, year: int, summary: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(CaseCache).where(CaseCache.case_id == case_id))
        row = result.scalar_one_or_none()
        if row is None:
            row = CaseCache(case_id=case_id, year=year, summary=summary)
            db.add(row)
        else:
            row.summary = summary
            row.year = year
        await db.commit()


async def unsave_case(user_id: str, case_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SavedCase).where(
                SavedCase.user_id == user_id,
                SavedCase.case_id == case_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
        return True


async def get_saved_cases(user_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SavedCase)
            .where(SavedCase.user_id == user_id)
            .order_by(desc(SavedCase.saved_at))
        )
        cases = result.scalars().all()
        return [
            {"id": str(c.id), "citation": c.citation, "case_id": c.case_id,
             "title": c.title, "saved_at": c.saved_at.isoformat()}
            for c in cases
        ]
