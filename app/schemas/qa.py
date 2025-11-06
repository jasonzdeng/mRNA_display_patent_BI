"""Schemas for question answering endpoints."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., description="User question to be answered by the system.")
    scope: Optional[dict] = Field(
        None,
        description="Optional scope hints such as jurisdictions or topics.",
    )
    recency: bool = Field(
        False,
        description="If true, downstream retrieval may request fresher sources (e.g., Perplexity).",
    )


class Citation(BaseModel):
    sent_idx: int
    doc_id: str
    offsets: List[List[int]]


class AskResponse(BaseModel):
    answer_md: str
    citations: List[Citation]
    followups: List[str]
    red_flags: List[str]
    cost_usd: float
    latency_ms: int