"""Targeted ingestion pipeline for mRNA-display patent documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import List, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import SessionLocal, engine
import app.models.patent  # noqa: F401
from app.models import PatentDocument, Snippet
from app.services.ingestion.mrna_pipeline import (
    DEFAULT_COMPONENT_PATTERNS,
    EpoOpsProvider,
    GooglePatentsFetcher,
    LocalFullTextFetcher,
    PatentsViewProvider,
    PatentRecord,
    ProviderPatentRaw,
    QueryConfig,
    SnippetPayload,
    WipoPatentScopeProvider,
    collect_provider_records,
    enrich_with_full_text,
    merge_records_by_family,
    normalise_to_patent_record,
)

LOGGER = logging.getLogger("ingest_mrna_display")
RAW_EXPORT_DIR = Path("data") / "raw" / "mrna_display"
RAW_EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest mRNA-display patents into the database")
    parser.add_argument("--config", type=Path, help="Optional JSON config overriding query templates")
    parser.add_argument("--per-page", type=int, help="Override results per page for all providers")
    parser.add_argument("--max-pages", type=int, help="Override page limit for all providers")
    parser.add_argument("--manual", type=Path, help="Path to JSONL/JSON file with supplemental provider payloads")
    parser.add_argument("--full-text-dir", type=Path, help="Directory containing local full-text JSON/TXT dumps")
    parser.add_argument("--disable-google", action="store_true", help="Skip Google Patents scraping fallback")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and normalise without writing to the database")
    parser.add_argument("--save-raw", action="store_true", help="Persist collected provider payloads under data/raw")
    parser.add_argument("--raw-dir", type=Path, default=RAW_EXPORT_DIR, help="Directory for saving raw payload snapshots")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level), format="%(asctime)s %(levelname)s %(message)s")


def load_manual_provider_records(path: Path) -> List[ProviderPatentRaw]:
    if not path.exists():
        raise FileNotFoundError(f"Manual input file not found: {path}")
    content = path.read_text(encoding="utf-8").strip()
    records: List[ProviderPatentRaw] = []
    if not content:
        return records
    try:
        payload = json.loads(content)
        iterable = payload if isinstance(payload, list) else [payload]
        for item in iterable:
            records.append(ProviderPatentRaw(**item))
        LOGGER.info("Loaded %s manual records from %s", len(records), path)
        return records
    except json.JSONDecodeError:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                records.append(ProviderPatentRaw(**json.loads(line)))
        LOGGER.info("Loaded %s manual records from JSONL %s", len(records), path)
        return records


def merge_sources(existing: dict | None, new: dict, component_tags: Sequence[str]) -> dict:
    merged = dict(existing or {})
    history = merged.setdefault("ingestion_events", [])
    history.append({"timestamp": new.get("retrieved_at"), "origin": new.get("origin"), "raw": new.get("raw")})
    merged["component_tags"] = sorted({*(merged.get("component_tags", [])), *component_tags})
    merged["keywords"] = sorted({*(merged.get("keywords", [])), *(new.get("keywords") or [])})
    return merged


def upsert_document(session: Session, record: PatentRecord) -> PatentDocument:
    stmt = select(PatentDocument).where(PatentDocument.doc_number == record.doc_number)
    existing = session.execute(stmt).scalar_one_or_none()

    if existing:
        doc = existing
        doc.title = record.title or doc.title
        doc.abstract = record.abstract or doc.abstract
        doc.description_text = record.description or doc.description_text
        doc.claims_text = record.claims or doc.claims_text
        doc.jurisdiction = record.jurisdiction or doc.jurisdiction
        doc.kind_code = record.kind_code or doc.kind_code
        doc.family_id = record.family_id or doc.family_id
        if record.cpc_codes:
            doc.cpc_codes = list(sorted({*(doc.cpc_codes or []), *record.cpc_codes}))
        if record.assignees:
            doc.assignees = list(sorted({*(doc.assignees or []), *record.assignees}))
        if record.inventors:
            doc.inventors = list(sorted({*(doc.inventors or []), *record.inventors}))
        doc.filing_date = doc.filing_date or record.filing_date
        doc.grant_date = doc.grant_date or record.grant_date
        doc.publication_date = doc.publication_date or record.publication_date
        doc.earliest_priority_date = doc.earliest_priority_date or record.earliest_priority_date
        doc.estimated_expiration = doc.estimated_expiration or record.estimated_expiration
    else:
        doc = PatentDocument(
            doc_number=record.doc_number,
            jurisdiction=record.jurisdiction,
            kind_code=record.kind_code,
            title=record.title,
            abstract=record.abstract,
            description_text=record.description,
            claims_text=record.claims,
            family_id=record.family_id,
            priority_numbers=list(record.priority_numbers),
            cpc_codes=list(record.cpc_codes),
            assignees=list(record.assignees),
            inventors=list(record.inventors),
            filing_date=record.filing_date,
            publication_date=record.publication_date,
            grant_date=record.grant_date,
            earliest_priority_date=record.earliest_priority_date,
            estimated_expiration=record.estimated_expiration,
            source={},
        )
        session.add(doc)
        session.flush()

    doc.source = merge_sources(doc.source, record.source, record.component_tags)
    return doc


def upsert_snippets(session: Session, document: PatentDocument, payloads: Sequence[SnippetPayload]) -> int:
    existing = {snippet.hash: snippet for snippet in document.snippets if snippet.hash}
    created = 0
    for payload in payloads:
        text = payload.text.strip()
        if not text:
            continue
        snippet_hash = hashlib.sha256(f"{payload.section}:{text}".encode("utf-8")).hexdigest()
        if snippet_hash in existing:
            continue
        snippet = Snippet(
            patent_id=document.id,
            section=payload.section,
            start_char=payload.start_char,
            end_char=payload.end_char,
            text=payload.text,
            hash=snippet_hash,
        )
        session.add(snippet)
        created += 1
    return created


def ingest_records(session: Session, records: Sequence[PatentRecord]) -> tuple[int, int]:
    docs = 0
    snippets = 0
    for record in records:
        if not record.doc_number:
            LOGGER.warning("Skipping record without document number: %s", record)
            continue
        doc = upsert_document(session, record)
        snippets += upsert_snippets(session, doc, record.snippets)
        docs += 1
    session.commit()
    return docs, snippets


def persist_raw_snapshot(path: Path, payload: Sequence[ProviderPatentRaw]) -> None:
    serialisable = [
        {
            "doc_number": item.doc_number,
            "jurisdiction": item.jurisdiction,
            "kind_code": item.kind_code,
            "family_id": item.family_id,
            "title": item.title,
            "abstract": item.abstract,
            "claims": item.claims,
            "description": item.description,
            "filing_date": item.filing_date,
            "publication_date": item.publication_date,
            "grant_date": item.grant_date,
            "assignees": item.assignees,
            "inventors": item.inventors,
            "cpc_codes": item.cpc_codes,
            "ipc_codes": item.ipc_codes,
            "priority_numbers": item.priority_numbers,
            "source": item.source,
            "provider": item.provider,
        }
        for item in payload
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialisable, indent=2), encoding="utf-8")
    LOGGER.info("Persisted raw snapshot: %s", path)


def build_fetchers(args: argparse.Namespace) -> List[object]:
    fetchers: List[object] = []
    if args.full_text_dir:
        fetchers.append(LocalFullTextFetcher(args.full_text_dir))
    if not args.disable_google:
        fetchers.append(GooglePatentsFetcher())
    return fetchers


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    query_config = QueryConfig.load(args.config)
    if args.per_page:
        query_config.per_page = args.per_page
    if args.max_pages:
        query_config.max_pages = args.max_pages

    providers = [
        PatentsViewProvider(),
        WipoPatentScopeProvider(),
        EpoOpsProvider(),
    ]

    collected = collect_provider_records(providers, query_config)
    if args.manual:
        collected.extend(load_manual_provider_records(args.manual))

    merged = merge_records_by_family(collected)
    if args.save_raw:
        destination = (args.raw_dir or RAW_EXPORT_DIR) / "payload_snapshot.json"
        persist_raw_snapshot(destination, merged)

    fetchers = build_fetchers(args)
    if fetchers:
        merged = enrich_with_full_text(merged, fetchers)

    patterns = dict(DEFAULT_COMPONENT_PATTERNS)
    manual_patterns = os.environ.get("MRNA_COMPONENT_PATTERNS")
    if manual_patterns:
        try:
            patterns.update(json.loads(manual_patterns))
        except json.JSONDecodeError:
            LOGGER.warning("MRNA_COMPONENT_PATTERNS env var is not valid JSON; ignoring")

    normalised_records: List[PatentRecord] = [normalise_to_patent_record(record, patterns) for record in merged]
    LOGGER.info("Prepared %s normalised records", len(normalised_records))

    if args.dry_run:
        LOGGER.info("Dry run enabled: skipping database writes")
        return

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        docs, snippets = ingest_records(session, normalised_records)
    LOGGER.info("Ingested %s documents and %s snippets", docs, snippets)


if __name__ == "__main__":
    main()
