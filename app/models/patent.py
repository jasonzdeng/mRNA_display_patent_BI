"""ORM models representing patent-related entities."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import List, Optional

from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PatentDocument(Base):
    """Primary table storing normalized patent metadata and text."""

    __tablename__ = "patent_document"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    doc_number: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    kind_code: Mapped[Optional[str]] = mapped_column(String(8))
    title: Mapped[Optional[str]] = mapped_column(String(512))
    abstract: Mapped[Optional[str]] = mapped_column(Text())
    claims_text: Mapped[Optional[str]] = mapped_column(Text())
    description_text: Mapped[Optional[str]] = mapped_column(Text())
    pdf_url: Mapped[Optional[str]] = mapped_column(String(1024))
    html_url: Mapped[Optional[str]] = mapped_column(String(1024))
    family_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    priority_numbers: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String()))
    filing_date: Mapped[Optional[date]] = mapped_column(Date())
    grant_date: Mapped[Optional[date]] = mapped_column(Date())
    publication_date: Mapped[Optional[date]] = mapped_column(Date())
    earliest_priority_date: Mapped[Optional[date]] = mapped_column(Date())
    estimated_expiration: Mapped[Optional[date]] = mapped_column(Date())
    cpc_codes: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String()))
    assignees: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String()))
    inventors: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String()))
    status: Mapped[Optional[str]] = mapped_column(String(128))
    source: Mapped[Optional[dict]] = mapped_column(JSON)
    embedding: Mapped[Optional[List[float]]] = mapped_column(
        ARRAY(Float), nullable=True, doc="Vector embedding stored via pgvector or float array."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    snippets: Mapped[List[Snippet]] = relationship("Snippet", back_populates="patent")
    update_logs: Mapped[List[UpdateLog]] = relationship("UpdateLog", back_populates="patent")


class Snippet(Base):
    """Indexed textual spans for retrieval."""

    __tablename__ = "snippet"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patent_document.id", ondelete="CASCADE"), nullable=False
    )
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    start_char: Mapped[int] = mapped_column()
    end_char: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    hash: Mapped[Optional[str]] = mapped_column(String(128), unique=True)
    embedding: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float), nullable=True)

    patent: Mapped[PatentDocument] = relationship("PatentDocument", back_populates="snippets")

    __table_args__ = (
        CheckConstraint(
            "section IN ('abstract','claims','description','front')",
            name="snippet_section_check",
        ),
    )


class UpdateLog(Base):
    """Track observed changes for a patent document."""

    __tablename__ = "update_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patent_document.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text())
    new_value: Mapped[Optional[str]] = mapped_column(Text())
    source_url: Mapped[Optional[str]] = mapped_column(String(1024))
    note: Mapped[Optional[str]] = mapped_column(Text())

    patent: Mapped[PatentDocument] = relationship("PatentDocument", back_populates="update_logs")


class Answer(Base):
    """Persist generated answers and their supporting documents."""

    __tablename__ = "answer"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    question: Mapped[str] = mapped_column(Text(), nullable=False)
    answer_md: Mapped[str] = mapped_column(Text(), nullable=False)
    cited_doc_ids: Mapped[Optional[List[uuid.UUID]]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    per_claim_support: Mapped[Optional[dict]] = mapped_column(JSON)
    latency_ms: Mapped[Optional[int]] = mapped_column()
    model: Mapped[Optional[str]] = mapped_column(String(128))
    cost_usd: Mapped[Optional[float]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class WatchTarget(Base):
    """Entities (assignee, keyword, family) to monitor."""

    __tablename__ = "watch_target"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint("type IN ('assignee','inventor','keyword','family')", name="watch_type_check"),
    )