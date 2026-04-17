import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Integer, DateTime,
    ForeignKey, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(Text, unique=True, nullable=False)
    name = Column(Text)
    clerk_id = Column(Text, unique=True)          # Clerk user id
    plan = Column(String(20), default="free")
    searches_today = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    saved_cases = relationship("SavedCase", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Text, ForeignKey("users.clerk_id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, default="New Search")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan",
                            order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)     # 'user' | 'assistant'
    content = Column(JSONB, nullable=False)        # { text, cases } for assistant; { text } for user
    created_at = Column(DateTime, server_default=func.now())

    session = relationship("Session", back_populates="messages")


class CaseCache(Base):
    """Persistent cache for LLM-generated summaries and breakdowns."""
    __tablename__ = "case_cache"

    case_id = Column(Text, primary_key=True)   # hash id from Pinecone metadata
    year = Column(Integer, nullable=False)
    summary = Column(Text, nullable=True)
    breakdown = Column(JSONB, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SavedCase(Base):
    __tablename__ = "saved_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Text, ForeignKey("users.clerk_id", ondelete="CASCADE"), nullable=False)
    citation = Column(Text)
    case_id = Column(Text)
    title = Column(Text)
    saved_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="saved_cases")
