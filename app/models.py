from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class BotAccessStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str] = mapped_column(String(255), default="")
    task_text: Mapped[str] = mapped_column(Text)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.pending, index=True)
    progress_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_text: Mapped[str] = mapped_column(Text, default="")
    result_pdf_path: Mapped[str] = mapped_column(Text, default="")
    result_html_path: Mapped[str] = mapped_column(Text, default="")
    result_markdown_path: Mapped[str] = mapped_column(Text, default="")
    result_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class BotAccessRequest(Base):
    __tablename__ = "bot_access_requests"

    telegram_user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str] = mapped_column(String(255), default="")
    first_name: Mapped[str] = mapped_column(String(255), default="")
    last_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[BotAccessStatus] = mapped_column(
        Enum(BotAccessStatus),
        default=BotAccessStatus.pending,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

