"""Seed ingestion script for patent documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine
from app.db.base import Base
import app.models.patent  # register models
from app.models import PatentDocument, Snippet


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "seed_patents.json"


@dataclass
class SeedPatent:
    doc_number: str
    title: str
    jurisdiction: str
    kind_code: str
    publication_date: Optional[date]
    earliest_priority_date: Optional[date]
    status: str | None
    assignees: List[str]
    cpc_codes: List[str]
    source_urls: List[str]
    notes: str | None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SeedPatent":
        return cls(
            doc_number=data["doc_number"],
            title=data.get("title", ""),
            jurisdiction=data.get("jurisdiction", ""),
            kind_code=data.get("kind_code", ""),
            publication_date=parse_date(data.get("publication_date")),
            earliest_priority_date=parse_date(data.get("earliest_priority_date")),
            status=data.get("status"),
            assignees=data.get("assignees", []),
            cpc_codes=data.get("cpc_codes", []),
            source_urls=data.get("source_urls", []),
            notes=data.get("notes"),
        )


def parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def load_seed_data(path: Path) -> List[SeedPatent]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [SeedPatent.from_dict(item) for item in data]


def upsert_patent(db: Session, seed: SeedPatent) -> PatentDocument:
    existing = db.execute(
        select(PatentDocument).where(PatentDocument.doc_number == seed.doc_number)
    ).scalar_one_or_none()

    if existing:
        existing.title = seed.title or existing.title
        existing.jurisdiction = seed.jurisdiction or existing.jurisdiction
        existing.kind_code = seed.kind_code or existing.kind_code
        if seed.publication_date:
            existing.publication_date = seed.publication_date
        if seed.earliest_priority_date:
            existing.earliest_priority_date = seed.earliest_priority_date
        if seed.status:
            existing.status = seed.status
        if seed.assignees:
            existing.assignees = seed.assignees
        if seed.cpc_codes:
            existing.cpc_codes = seed.cpc_codes
        existing.source = {"source_urls": seed.source_urls, "notes": seed.notes}
        document = existing
    else:
        document = PatentDocument(
            doc_number=seed.doc_number,
            title=seed.title,
            jurisdiction=seed.jurisdiction,
            kind_code=seed.kind_code,
            publication_date=seed.publication_date,
            earliest_priority_date=seed.earliest_priority_date,
            status=seed.status,
            assignees=seed.assignees,
            cpc_codes=seed.cpc_codes,
            source={"source_urls": seed.source_urls, "notes": seed.notes},
        )
        db.add(document)

    db.flush()
    return document


def upsert_snippet(db: Session, document: PatentDocument, seed: SeedPatent) -> None:
    existing = db.execute(
        select(Snippet).where(Snippet.patent_id == document.id, Snippet.section == "abstract")
    ).scalar_one_or_none()

    snippet_text = seed.notes or "Seed note placeholder."
    if existing:
        existing.text = snippet_text
    else:
        snippet = Snippet(
            patent_id=document.id,
            section="abstract",
            start_char=0,
            end_char=len(snippet_text),
            text=snippet_text,
        )
        db.add(snippet)


def main() -> None:
    seeds = load_seed_data(DATA_PATH)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE patent_document ALTER COLUMN status TYPE VARCHAR(128)"))
        except Exception:
            # Ignore if the alteration is unnecessary or already applied.
            pass
        try:
            conn.execute(text("ALTER TABLE snippet ADD COLUMN IF NOT EXISTS embedding float[]"))
        except Exception:
            pass
    with SessionLocal() as session:
        for seed in seeds:
            document = upsert_patent(session, seed)
            upsert_snippet(session, document, seed)
        session.commit()
    print(f"Ingested {len(seeds)} seed patents.")


if __name__ == "__main__":
    main()
