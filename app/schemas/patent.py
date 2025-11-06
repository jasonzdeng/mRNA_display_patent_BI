"""Pydantic schemas for API payloads."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PatentDocumentBase(BaseModel):
    doc_number: str = Field(..., description="Publication or grant identifier.")
    jurisdiction: str = Field(..., description="Issuing authority (US, EP, WO, JP, etc.).")
    kind_code: Optional[str] = Field(None, description="Kind code suffix (A1, B2, etc.).")
    title: Optional[str] = None
    abstract: Optional[str] = None
    claims_text: Optional[str] = Field(
        None, description="Full claim text as ingested from the source document."
    )
    description_text: Optional[str] = None
    pdf_url: Optional[str] = None
    html_url: Optional[str] = None
    family_id: Optional[str] = Field(None, description="DOCDB family identifier if available.")
    priority_numbers: Optional[List[str]] = None
    filing_date: Optional[date] = None
    grant_date: Optional[date] = None
    publication_date: Optional[date] = None
    earliest_priority_date: Optional[date] = None
    estimated_expiration: Optional[date] = Field(
        None, description="Heuristic expiration estimate (flagged as estimate in UI)."
    )
    cpc_codes: Optional[List[str]] = None
    assignees: Optional[List[str]] = None
    inventors: Optional[List[str]] = None
    status: Optional[str] = None
    source: Optional[dict] = Field(None, description="Opaque ingestion metadata blob.")


class PatentDocumentCreate(PatentDocumentBase):
    embedding: Optional[List[float]] = Field(
        None,
        description="Optional vector embedding (stored as pgvector float array).",
    )


class PatentDocumentRead(PatentDocumentBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SnippetRead(BaseModel):
    id: uuid.UUID
    patent_id: uuid.UUID
    section: str
    start_char: int
    end_char: int
    text: str
    hash: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class UpdateLogRead(BaseModel):
    id: uuid.UUID
    patent_id: uuid.UUID
    observed_at: datetime
    field: str
    old_value: Optional[str]
    new_value: Optional[str]
    source_url: Optional[str]
    note: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class AnswerRead(BaseModel):
    id: uuid.UUID
    question: str
    answer_md: str
    cited_doc_ids: Optional[List[uuid.UUID]]
    per_claim_support: Optional[dict]
    latency_ms: Optional[int]
    model: Optional[str]
    cost_usd: Optional[float]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchTargetBase(BaseModel):
    type: str = Field(..., description="Watch target type (assignee, inventor, keyword, family).")
    value: str = Field(..., description="Normalized watch value (e.g., assignee name).")
    active: bool = True


class WatchTargetCreate(WatchTargetBase):
    pass


class WatchTargetRead(WatchTargetBase):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)