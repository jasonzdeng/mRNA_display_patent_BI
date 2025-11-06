"""Patent metadata endpoints."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.db.session import get_db

router = APIRouter(prefix="/patents", tags=["patents"])


@router.get("/", response_model=List[schemas.PatentDocumentRead])
def list_patents(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Simple search across title and doc number."),
    jurisdiction: Optional[str] = Query(None, description="Filter by issuing jurisdiction."),
    family_id: Optional[str] = Query(None, description="Filter by DOCDB family identifier."),
) -> List[schemas.PatentDocumentRead]:
    """Return a filtered list of patent records."""

    stmt = select(models.PatentDocument)

    if q:
        like_pattern = f"%{q}%"
        stmt = stmt.filter(
            (models.PatentDocument.title.ilike(like_pattern))
            | (models.PatentDocument.doc_number.ilike(like_pattern))
        )
    if jurisdiction:
        stmt = stmt.filter(models.PatentDocument.jurisdiction == jurisdiction.upper())
    if family_id:
        stmt = stmt.filter(models.PatentDocument.family_id == family_id)

    results = db.execute(stmt.order_by(models.PatentDocument.publication_date.desc().nullslast()))
    return results.scalars().all()


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.PatentDocumentRead,
)
def create_patent(
    payload: schemas.PatentDocumentCreate,
    db: Session = Depends(get_db),
) -> schemas.PatentDocumentRead:
    """Persist a new patent document record."""

    document = models.PatentDocument(**payload.dict())
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@router.get("/{patent_id}", response_model=schemas.PatentDocumentRead)
def get_patent(
    patent_id: uuid.UUID, db: Session = Depends(get_db)
) -> schemas.PatentDocumentRead:
    """Fetch a single patent document by UUID."""

    document = db.get(models.PatentDocument, patent_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patent not found")
    return document


@router.get(
    "/{patent_id}/snippets",
    response_model=List[schemas.SnippetRead],
)
def list_snippets(
    patent_id: uuid.UUID, db: Session = Depends(get_db)
) -> List[schemas.SnippetRead]:
    """Return retrieval snippets associated with the patent."""

    stmt = select(models.Snippet).where(models.Snippet.patent_id == patent_id)
    results = db.execute(stmt.order_by(models.Snippet.start_char))
    snippets = results.scalars().all()
    if not snippets:
        # Ensure the parent exists; surface 404 if neither doc nor snippets exist.
        if not db.get(models.PatentDocument, patent_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patent not found")
    return snippets