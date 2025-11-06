"""Generate coverage report against canonical mRNA-display patent list."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import PatentDocument
from app.services.ingestion.mrna_pipeline import summarise_coverage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare ingested patents to a canonical mRNA-display list")
    parser.add_argument("--canonical", type=Path, required=True, help="Path to canonical doc number list (JSON/JSONL/TXT)")
    parser.add_argument("--output", type=Path, help="Optional path to persist the coverage report as JSON")
    return parser.parse_args()


def load_canonical(path: Path) -> List[str]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    try:
        payload = json.loads(content)
        if isinstance(payload, list):
            if payload and isinstance(payload[0], dict):
                return [str(item.get("doc_number") or item.get("publication_number") or "").strip() for item in payload if item]
            return [str(item).strip() for item in payload if item]
        if isinstance(payload, dict):
            return [str(value).strip() for value in payload.values() if value]
    except json.JSONDecodeError:
        pass

    # Treat as newline-separated text
    doc_numbers = [line.strip() for line in content.splitlines() if line.strip()]
    return doc_numbers


def fetch_existing_doc_numbers() -> List[str]:
    with SessionLocal() as session:
        rows = session.execute(select(PatentDocument.doc_number)).scalars().all()
    return [row.strip() for row in rows if row]


def main() -> None:
    args = parse_args()
    canonical = load_canonical(args.canonical)
    existing = fetch_existing_doc_numbers()
    report = summarise_coverage(canonical, existing)

    print("Canonical patents:", report.canonical)
    print("Present in corpus:", report.present)
    print("Coverage ratio:", f"{report.coverage_ratio:0.2%}")
    if report.missing:
        print("Missing doc numbers:")
        for doc_number in report.missing:
            print(" -", doc_number)

    if args.output:
        payload = {
            "canonical": report.canonical,
            "present": report.present,
            "coverage_ratio": report.coverage_ratio,
            "missing": report.missing,
        }
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
