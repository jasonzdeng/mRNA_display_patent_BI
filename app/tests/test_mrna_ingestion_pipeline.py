from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.ingestion import (
    QueryConfig,
    collect_provider_records,
    enrich_with_full_text,
    merge_records_by_family,
    normalise_to_patent_record,
    summarise_coverage,
)
from app.services.ingestion.mrna_pipeline import (
    DEFAULT_COMPONENT_PATTERNS,
    GooglePatentsHTMLParser,
    ProviderPatentRaw,
)


class StubProvider:
    name = "stub"

    def __init__(self, payloads):
        self.payloads = payloads

    def fetch(self, query):  # pragma: no cover - simple data return
        return list(self.payloads)


class StubFetcher:
    name = "stub_fetcher"

    def __init__(self, claims: str, description: str):
        self.claims = claims
        self.description = description
        self.calls = []

    def fetch(self, doc_number: str, jurisdiction: str):
        self.calls.append((doc_number, jurisdiction))
        return self.claims, self.description


@pytest.fixture
def sample_provider_payloads():
    return [
        ProviderPatentRaw(
            doc_number="US1234567",
            jurisdiction="US",
            kind_code="A1",
            family_id="FAM-1",
            title="mRNA display platform",
            abstract="Improved cyclization chemistry",
            claims=None,
            description=None,
            filing_date="2020-01-01",
            publication_date="2021-01-01",
            grant_date=None,
            assignees=["Moderna"],
            inventors=["A. Doe"],
            cpc_codes=["C07K"],
            ipc_codes=["C12N"],
            priority_numbers=["2019US123"],
            source={"provider": "patentsview"},
            provider="patentsview",
        ),
        ProviderPatentRaw(
            doc_number="WO2020123456",
            jurisdiction="WO",
            kind_code="A1",
            family_id="FAM-1",
            title="",
            abstract="",
            claims="Peptide cyclization claim",
            description="Detailed ribosome display workflow",
            filing_date="2019-06-01",
            publication_date="2019-12-01",
            grant_date=None,
            assignees=["PeptiDream"],
            inventors=["B. Smith"],
            cpc_codes=["C12P"],
            ipc_codes=["G01N"],
            priority_numbers=["2018JP456"],
            source={"provider": "wipo_patentscope"},
            provider="wipo_patentscope",
        ),
    ]


def test_query_config_customisation(tmp_path: Path):
    cfg_path = tmp_path / "ingestion.json"
    cfg_path.write_text(
        json.dumps(
            {
                "keywords": ['"custom mRNA display"'],
                "synonyms": ['"macrocyclic peptide display"'],
                "per_page": 25,
                "max_pages": 2,
                "applicants": ["Custom Co"],
            }
        ),
        encoding="utf-8",
    )

    cfg = QueryConfig.load(cfg_path)

    assert cfg.keywords == ['"custom mRNA display"']
    assert '"macrocyclic peptide display"' in cfg.phrases
    assert cfg.per_page == 25
    assert cfg.max_pages == 2
    assert "Custom Co" in cfg.applicants


def test_merge_records_by_family(sample_provider_payloads):
    merged = merge_records_by_family(sample_provider_payloads)
    assert len(merged) == 2
    us_record = next(record for record in merged if record.doc_number == "US1234567")
    assert sorted(us_record.assignees) == ["Moderna", "PeptiDream"]
    assert sorted(us_record.cpc_codes) == ["C07K", "C12P"]
    assert sorted(us_record.priority_numbers) == ["2018JP456", "2019US123"]


def test_full_text_enrichment(sample_provider_payloads):
    base = [sample_provider_payloads[0]]
    fetcher = StubFetcher("Claim text", "Description text")
    enriched = enrich_with_full_text(base, [fetcher])
    assert enriched[0].claims == "Claim text"
    assert enriched[0].description == "Description text"
    assert fetcher.calls == [("US1234567", "US")]


def test_normalise_to_patent_record_builds_snippets(sample_provider_payloads):
    record = normalise_to_patent_record(sample_provider_payloads[1], DEFAULT_COMPONENT_PATTERNS)
    sections = {snippet.section for snippet in record.snippets}
    assert sections.issuperset({"claims", "description"})
    assert "cyclization" in record.component_tags


def test_google_patents_html_parser_extracts_text():
    parser = GooglePatentsHTMLParser()
    parser.feed('<section itemprop="claims">First claim</section><section itemprop="description">Desc</section>')
    assert parser.claims_parts == ["First claim"]
    assert parser.description_parts == ["Desc"]


def test_summarise_coverage_identifies_missing_entries():
    report = summarise_coverage(["US1", "WO2"], ["us1"])
    assert report.present == 1
    assert report.missing == ["WO2"]
    assert report.coverage_ratio == pytest.approx(0.5)


def test_collect_provider_records_handles_multiple_sources(sample_provider_payloads):
    provider = StubProvider(sample_provider_payloads)
    cfg = QueryConfig.load(None)
    records = collect_provider_records([provider], cfg)
    assert len(records) == len(sample_provider_payloads)
