"""Question answering endpoints."""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.db.session import get_db
from app.services import HybridRetriever, LLMClient

router = APIRouter(prefix="/questions", tags=["qa"])

logger = logging.getLogger(__name__)


@router.post("/ask", response_model=schemas.AskResponse)
def ask_question(
    payload: schemas.AskRequest,
    db: Session = Depends(get_db),
) -> schemas.AskResponse:
    """Answer a question using retrieval augmented generation."""

    retriever = HybridRetriever(db)
    passages = retriever.retrieve(payload.question)

    if not passages:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No supporting documents found for the query.",
        )

    llm_client = LLMClient()
    if llm_client.is_configured:
        try:
            answer = llm_client.generate_answer(payload.question, passages)
            return schemas.AskResponse(**answer.model_dump())
        except Exception as exc:  # pragma: no cover - safeguard for runtime issues
            logger.warning("LLM generation failed, falling back to deterministic summary", exc_info=exc)

    doc_ids = {p.doc_id for p in passages}
    documents = (
        db.query(models.PatentDocument)
        .filter(models.PatentDocument.id.in_(doc_ids))
        .all()
        if doc_ids
        else []
    )
    doc_map = {doc.id: doc for doc in documents}

    lines: List[str] = []
    for passage in passages:
        doc = doc_map.get(passage.doc_id)
        if not doc:
            continue
        title = doc.title or doc.doc_number
        status_note = doc.status or "Status unknown"
        jurisdiction = doc.jurisdiction
        lines.append(
            f"- **{title} ({jurisdiction})** — {status_note}. {passage.text}"
        )

    synthesized_answer = "\n".join(lines)
    citations = [
        schemas.Citation(sent_idx=index, doc_id=str(p.doc_id), offsets=[[0, len(p.text)]])
        for index, p in enumerate(passages)
    ]

    return schemas.AskResponse(
        answer_md=(
            synthesized_answer
            + "\n\nTechnical landscaping only – not legal advice."
        ),
        citations=citations,
        followups=[],
        red_flags=[],
        cost_usd=0.0,
        latency_ms=0,
    )