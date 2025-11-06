"""Reusable ingestion pipeline helpers for mRNA-display patent retrieval."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

import httpx

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query configuration
# ---------------------------------------------------------------------------


DEFAULT_CONFIG = {
    "keywords": [
        "\"mRNA display\"",
        "\"messenger RNA display\"",
        "\"displayed mRNA-peptide fusion\"",
    ],
    "synonyms": [
        "\"ribosome display\"",
        "\"flexizyme\"",
        "\"mRNA-peptide fusion\"",
        "\"RaPID platform\"",
    ],
    "cpc_prefixes": ["C07K", "C12N", "C12P", "G01N"],
    "ipc_prefixes": ["C12N", "G01N"],
    "applicants": [
        "Moderna",
        "Ra Pharmaceuticals",
        "PeptiDream",
        "Hoffmann-La Roche",
        "Chugai Pharmaceutical",
    ],
    "exclude_applicants": [],
    "per_page": 100,
    "max_pages": 10,
}


@dataclass
class QueryConfig:
    """Search configuration shared by all providers."""

    keywords: List[str]
    synonyms: List[str]
    cpc_prefixes: List[str]
    ipc_prefixes: List[str]
    applicants: List[str]
    exclude_applicants: List[str]
    per_page: int = 100
    max_pages: int = 10

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "QueryConfig":
        """Load configuration from JSON file or fall back to defaults."""

        if path is None:
            data = DEFAULT_CONFIG
        else:
            with Path(path).expanduser().resolve().open("r", encoding="utf-8") as handle:
                user_config = json.load(handle)
            data = {**DEFAULT_CONFIG, **user_config}
        return cls(
            keywords=list(dict.fromkeys(data.get("keywords", DEFAULT_CONFIG["keywords"]))),
            synonyms=list(dict.fromkeys(data.get("synonyms", DEFAULT_CONFIG["synonyms"]))),
            cpc_prefixes=list(dict.fromkeys(data.get("cpc_prefixes", DEFAULT_CONFIG["cpc_prefixes"]))),
            ipc_prefixes=list(dict.fromkeys(data.get("ipc_prefixes", DEFAULT_CONFIG["ipc_prefixes"]))),
            applicants=list(dict.fromkeys(data.get("applicants", DEFAULT_CONFIG["applicants"]))),
            exclude_applicants=list(dict.fromkeys(data.get("exclude_applicants", []))),
            per_page=int(data.get("per_page", DEFAULT_CONFIG["per_page"])),
            max_pages=int(data.get("max_pages", DEFAULT_CONFIG["max_pages"])),
        )

    @property
    def phrases(self) -> List[str]:
        """All search phrases (keywords + synonyms)."""

        return list(dict.fromkeys(self.keywords + self.synonyms))


# ---------------------------------------------------------------------------
# Provider payloads and protocols
# ---------------------------------------------------------------------------


@dataclass
class ProviderPatentRaw:
    """Normalized representation of provider responses."""

    doc_number: str
    jurisdiction: str
    kind_code: Optional[str]
    family_id: Optional[str]
    title: Optional[str]
    abstract: Optional[str]
    claims: Optional[str]
    description: Optional[str]
    filing_date: Optional[str]
    publication_date: Optional[str]
    grant_date: Optional[str]
    assignees: List[str] = field(default_factory=list)
    inventors: List[str] = field(default_factory=list)
    cpc_codes: List[str] = field(default_factory=list)
    ipc_codes: List[str] = field(default_factory=list)
    priority_numbers: List[str] = field(default_factory=list)
    source: Dict[str, Any] = field(default_factory=dict)
    provider: str = ""


class PatentProvider(Protocol):
    """Interface for upstream patent data sources."""

    name: str

    def fetch(self, query: QueryConfig) -> List[ProviderPatentRaw]:
        ...


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


class PatentsViewProvider:
    """Client for USPTO PatentsView API."""

    name = "patentsview"
    endpoint = "https://patentsview.org/api/patents/query"

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._client = client or httpx.Client(timeout=60.0)

    def fetch(self, query: QueryConfig) -> List[ProviderPatentRaw]:
        payloads: List[ProviderPatentRaw] = []
        query_body = build_patentsview_query(query)

        for page in range(1, query.max_pages + 1):
            body = {
                "q": query_body,
                "f": PATENTSVIEW_FIELDS,
                "o": {"page": page, "per_page": query.per_page},
            }
            response = self._client.post(self.endpoint, json=body)
            response.raise_for_status()
            data = response.json()
            patents = data.get("patents", [])
            for item in patents:
                payloads.append(parse_patentsview_item(item))
            total = data.get("total_patent_count")
            if not patents or (total is not None and len(payloads) >= total):
                break
            if len(patents) < query.per_page:
                break

        return payloads


PATENTSVIEW_FIELDS = [
    "patent_number",
    "patent_title",
    "patent_abstract",
    "patent_date",
    "patent_application_date",
    "patent_issue_date",
    "patent_kind",
    "patent_type",
    "patent_country",
    "patent_num_claims",
    "patent_family_id",
    "cpcs.cpc_subgroup_id",
    "cpcs.cpc_section_id",
    "ipcs.ipc_subclass",
    "assignees.assignee_organization",
    "assignees.assignee_individual_name",
    "inventors.inventor_full_name",
]


def build_patentsview_query(query: QueryConfig) -> Dict[str, Any]:
    text_clauses = []
    for phrase in query.phrases:
        cleaned = re.sub(r"^\"|\"$", "", phrase)
        text_clauses.append({"_text_phrase": {"patent_title": cleaned}})
        text_clauses.append({"_text_phrase": {"patent_abstract": cleaned}})

    cpc_clauses = [
        {"_begins": {"cpc_subgroup_id": prefix}}
        for prefix in query.cpc_prefixes
    ]
    ipc_clauses = [
        {"_begins": {"ipc_subclass": prefix}}
        for prefix in query.ipc_prefixes
    ]
    applicant_clauses = [
        {"_text_phrase": {"assignee_organization": applicant}}
        for applicant in query.applicants
    ]

    base = {"_or": text_clauses} if text_clauses else {"_text_all": {"patent_title": "mRNA"}}
    augments: List[Dict[str, Any]] = []
    if cpc_clauses:
        augments.append({"_or": cpc_clauses})
    if ipc_clauses:
        augments.append({"_or": ipc_clauses})
    if applicant_clauses:
        augments.append({"_or": applicant_clauses})

    if augments:
        base = {"_and": [base, *augments]}

    if query.exclude_applicants:
        base = {
            "_and": [
                base,
                {
                    "_not": {
                        "_or": [
                            {"_text_phrase": {"assignee_organization": applicant}}
                            for applicant in query.exclude_applicants
                        ]
                    }
                },
            ]
        }

    return base


def parse_patentsview_item(item: Dict[str, Any]) -> ProviderPatentRaw:
    assignees = []
    for assignee in item.get("assignees", []):
        org = assignee.get("assignee_organization")
        individual = assignee.get("assignee_individual_name")
        if org:
            assignees.append(org)
        elif individual:
            assignees.append(individual)

    inventors = [
        inventor.get("inventor_full_name")
        for inventor in item.get("inventors", [])
        if inventor.get("inventor_full_name")
    ]

    cpc_codes = sorted({entry.get("cpc_subgroup_id") for entry in item.get("cpcs", []) if entry.get("cpc_subgroup_id")})
    ipc_codes = sorted({entry.get("ipc_subclass") for entry in item.get("ipcs", []) if entry.get("ipc_subclass")})

    return ProviderPatentRaw(
        doc_number=item.get("patent_number", "").strip(),
        jurisdiction=(item.get("patent_country") or "US").strip().upper() or "US",
        kind_code=item.get("patent_kind"),
        family_id=str(item.get("patent_family_id")) if item.get("patent_family_id") else None,
        title=item.get("patent_title"),
        abstract=item.get("patent_abstract"),
        claims=None,
        description=None,
        filing_date=item.get("patent_application_date"),
        publication_date=item.get("patent_date"),
        grant_date=item.get("patent_issue_date"),
        assignees=assignees,
        inventors=inventors,
        cpc_codes=cpc_codes,
        ipc_codes=ipc_codes,
        priority_numbers=[],
        source={"provider": "patentsview"},
        provider="patentsview",
    )


class WipoPatentScopeProvider:
    """Client for the WIPO PATENTSCOPE API."""

    name = "wipo_patentscope"
    endpoint = "https://patentscope.wipo.int/search/en/api/v3/search"

    def __init__(self, token: Optional[str] = None, client: Optional[httpx.Client] = None) -> None:
        self._token = token or os.getenv("WIPO_PATENTSCOPE_TOKEN")
        self._client = client or httpx.Client(timeout=60.0)

    def fetch(self, query: QueryConfig) -> List[ProviderPatentRaw]:
        if not self._token:
            LOGGER.info("Skipping WIPO PATENTSCOPE fetch: missing API token")
            return []

        payloads: List[ProviderPatentRaw] = []
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

        search_terms = build_wipo_query_terms(query)
        for page in range(0, query.max_pages):
            params = {
                "q": search_terms,
                "rows": query.per_page,
                "start": page * query.per_page,
            }
            response = self._client.get(self.endpoint, params=params, headers=headers)
            if response.status_code == 401:
                LOGGER.warning("WIPO PATENTSCOPE token rejected; skipping provider")
                break
            response.raise_for_status()
            data = response.json()
            docs = data.get("patents", data.get("results", []))
            for item in docs:
                payloads.append(parse_wipo_item(item))
            if not docs or len(docs) < query.per_page:
                break

        return payloads


def build_wipo_query_terms(query: QueryConfig) -> str:
    phrases = []
    for phrase in query.phrases:
        cleaned = phrase.strip('"')
        phrases.append(f'TTL:"{cleaned}"')
        phrases.append(f'AB:"{cleaned}"')
    cpc_terms = [f'CPC:{prefix}*' for prefix in query.cpc_prefixes]
    ipc_terms = [f'IPC:{prefix}*' for prefix in query.ipc_prefixes]
    applicant_terms = [f'PA:"{applicant}"' for applicant in query.applicants]
    include = " OR ".join(phrases + cpc_terms + ipc_terms + applicant_terms)
    exclude_terms = [f'NOT PA:"{applicant}"' for applicant in query.exclude_applicants]
    query_string = include
    if exclude_terms:
        query_string = f"({include}) {' '.join(exclude_terms)}"
    return query_string


def parse_wipo_item(item: Dict[str, Any]) -> ProviderPatentRaw:
    # WIPO payload structure varies; defensively access keys.
    doc_number = (item.get("publicationNumber") or item.get("DocNumber") or "").strip()
    family_id = item.get("familyId") or item.get("familyID")
    jurisdiction = (item.get("publicationCountry") or item.get("countryCode") or "WO").upper()
    title = item.get("title") or item.get("inventionTitle")
    abstract = item.get("abstract")
    claims = item.get("claims")
    description = item.get("description")
    assignees = item.get("applicants") or []
    inventors = item.get("inventors") or []
    cpc_codes = item.get("cpc") or []
    ipc_codes = item.get("ipc") or []
    filing_date = item.get("filingDate")
    publication_date = item.get("publicationDate")
    grant_date = item.get("grantDate")
    priority_numbers = item.get("priorityNumbers") or []

    to_list = lambda value: value if isinstance(value, list) else [value] if value else []

    return ProviderPatentRaw(
        doc_number=doc_number,
        jurisdiction=jurisdiction,
        kind_code=item.get("kindCode"),
        family_id=str(family_id) if family_id else None,
        title=title,
        abstract=abstract,
        claims=claims if isinstance(claims, str) else None,
        description=description if isinstance(description, str) else None,
        filing_date=filing_date,
        publication_date=publication_date,
        grant_date=grant_date,
        assignees=to_list(assignees),
        inventors=to_list(inventors),
        cpc_codes=to_list(cpc_codes),
        ipc_codes=to_list(ipc_codes),
        priority_numbers=to_list(priority_numbers),
        source={"provider": "wipo_patentscope"},
        provider="wipo_patentscope",
    )


class EpoOpsProvider:
    """Client for the EPO OPS search API."""

    name = "epo_ops"
    endpoint = "https://ops.epo.org/3.2/rest-services/published-data/search"

    def __init__(self, key: Optional[str] = None, secret: Optional[str] = None, client: Optional[httpx.Client] = None) -> None:
        self._key = key or os.getenv("EPO_OPS_KEY")
        self._secret = secret or os.getenv("EPO_OPS_SECRET")
        self._client = client or httpx.Client(timeout=60.0)

    def fetch(self, query: QueryConfig) -> List[ProviderPatentRaw]:
        if not (self._key and self._secret):
            LOGGER.info("Skipping EPO OPS fetch: missing credentials")
            return []

        payloads: List[ProviderPatentRaw] = []
        auth = (self._key, self._secret)
        q = build_epo_query_terms(query)

        for page in range(0, query.max_pages):
            params = {
                "q": q,
                "Range": f"{page * query.per_page}-{((page + 1) * query.per_page) - 1}",
            }
            headers = {"Accept": "application/json"}
            response = self._client.get(self.endpoint, params=params, headers=headers, auth=auth)
            if response.status_code in (401, 403):
                LOGGER.warning("EPO OPS credentials rejected; skipping provider")
                break
            response.raise_for_status()
            data = response.json()
            docs = extract_epo_documents(data)
            for item in docs:
                payloads.append(parse_epo_item(item))
            if not docs or len(docs) < query.per_page:
                break

        return payloads


def build_epo_query_terms(query: QueryConfig) -> str:
    cleaned_phrases = [phrase.strip('"') for phrase in query.phrases]
    text_terms = [f'ti="{phrase}"' for phrase in cleaned_phrases]
    abs_terms = [f'ab="{phrase}"' for phrase in cleaned_phrases]
    cpc_terms = [f'cpc={prefix}*' for prefix in query.cpc_prefixes]
    ipc_terms = [f'ipc={prefix}*' for prefix in query.ipc_prefixes]
    applicant_terms = [f'ap="{applicant}"' for applicant in query.applicants]
    include = " OR ".join(text_terms + abs_terms + cpc_terms + ipc_terms + applicant_terms)
    exclude_terms = [f'NOT ap="{applicant}"' for applicant in query.exclude_applicants]
    query_string = include or "ti=mRNA"
    if exclude_terms:
        query_string = f"({query_string}) {' '.join(exclude_terms)}"
    return query_string


def extract_epo_documents(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    # OPS JSON nests results under "ops:world-patent-data"; navigate defensively.
    world_data = payload.get("ops:world-patent-data") or {}
    search_response = world_data.get("ops:search-response") or {}
    results = search_response.get("ops:result")
    if isinstance(results, list):
        return results
    if isinstance(results, dict):
        return [results]
    return []


def parse_epo_item(item: Dict[str, Any]) -> ProviderPatentRaw:
    doc = item.get("document") or {}
    bibliographic_data = doc.get("bibliographic-data") or {}
    publication_reference = bibliographic_data.get("publication-reference") or {}
    document_id = publication_reference.get("document-id") or {}
    doc_number = (document_id.get("doc-number") or "").strip()
    country = (document_id.get("country") or "EP").upper()
    kind = document_id.get("kind")
    family_id = doc.get("@family-id") or doc.get("family-id")

    title = extract_epo_title(bibliographic_data)
    abstract = extract_epo_abstract(bibliographic_data)
    assignees = extract_epo_list(bibliographic_data.get("assignees"))
    inventors = extract_epo_list(bibliographic_data.get("inventors"))
    cpc_codes = extract_epo_classifications(bibliographic_data.get("classifications-cpc"))
    ipc_codes = extract_epo_classifications(bibliographic_data.get("classifications-ipc"))
    priority_numbers = extract_epo_priority_numbers(bibliographic_data.get("priority-claims"))

    filing_date = extract_epo_date(doc, "application-reference")
    publication_date = document_id.get("date")
    grant_date = extract_epo_date(bibliographic_data, "grant-reference")

    return ProviderPatentRaw(
        doc_number=doc_number,
        jurisdiction=country,
        kind_code=kind,
        family_id=str(family_id) if family_id else None,
        title=title,
        abstract=abstract,
        claims=None,
        description=None,
        filing_date=filing_date,
        publication_date=publication_date,
        grant_date=grant_date,
        assignees=assignees,
        inventors=inventors,
        cpc_codes=cpc_codes,
        ipc_codes=ipc_codes,
        priority_numbers=priority_numbers,
        source={"provider": "epo_ops"},
        provider="epo_ops",
    )


def extract_epo_title(bibliographic_data: Dict[str, Any]) -> Optional[str]:
    titles = bibliographic_data.get("invention-title")
    if isinstance(titles, list) and titles:
        primary = titles[0]
        if isinstance(primary, dict):
            return primary.get("$")
        if isinstance(primary, str):
            return primary
    if isinstance(titles, dict):
        return titles.get("$")
    return None


def extract_epo_abstract(bibliographic_data: Dict[str, Any]) -> Optional[str]:
    abstracts = bibliographic_data.get("abstract")
    if isinstance(abstracts, list) and abstracts:
        first = abstracts[0]
        if isinstance(first, dict):
            return first.get("p") or first.get("$")
    if isinstance(abstracts, dict):
        return abstracts.get("p") or abstracts.get("$")
    return None


def extract_epo_list(node: Any) -> List[str]:
    if isinstance(node, dict):
        values = node.get("name") or node.get("applicant") or node.get("inventor")
        if isinstance(values, list):
            return [value.get("name") if isinstance(value, dict) else str(value) for value in values if value]
        if isinstance(values, dict):
            return [values.get("name")]
        if isinstance(values, str):
            return [values]
    if isinstance(node, list):
        extracted: List[str] = []
        for value in node:
            extracted.extend(extract_epo_list(value))
        return extracted
    return []


def extract_epo_classifications(node: Any) -> List[str]:
    if isinstance(node, dict):
        classes = node.get("classification")
        if isinstance(classes, list):
            return [cls.get("text") or cls.get("symbol") for cls in classes if isinstance(cls, dict)]
        if isinstance(classes, dict):
            return [classes.get("text") or classes.get("symbol")]
    return []


def extract_epo_priority_numbers(node: Any) -> List[str]:
    if isinstance(node, dict):
        claims = node.get("priority-claim")
        if isinstance(claims, list):
            return [claim.get("doc-number") for claim in claims if isinstance(claim, dict) and claim.get("doc-number")]
        if isinstance(claims, dict):
            value = claims.get("doc-number")
            return [value] if value else []
    return []


def extract_epo_date(node: Any, reference_key: str) -> Optional[str]:
    ref = node.get(reference_key) if isinstance(node, dict) else None
    if isinstance(ref, dict):
        document_id = ref.get("document-id")
        if isinstance(document_id, dict):
            return document_id.get("date")
    return None


# ---------------------------------------------------------------------------
# Full-text fetchers
# ---------------------------------------------------------------------------


class FullTextFetcher(Protocol):
    name: str

    def fetch(self, doc_number: str, jurisdiction: str) -> Tuple[Optional[str], Optional[str]]:
        ...


class LocalFullTextFetcher:
    """Fetch full text from a local directory of JSON or text files."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser().resolve()

    def fetch(self, doc_number: str, jurisdiction: str) -> Tuple[Optional[str], Optional[str]]:
        json_path = self._root / f"{doc_number}.json"
        txt_path = self._root / f"{doc_number}.txt"
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            claims = data.get("claims") or data.get("claims_text")
            description = data.get("description") or data.get("description_text")
            return claims, description
        if txt_path.exists():
            content = txt_path.read_text(encoding="utf-8")
            return None, content
        return None, None


class GooglePatentsHTMLParser(HTMLParser):
    """Extract claims and description from Google Patents HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._capture: Optional[str] = None
        self.claims_parts: List[str] = []
        self.description_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)
        if attrs_dict.get("itemprop") == "claims" or attrs_dict.get("data-section") == "claims":
            self._capture = "claims"
        elif attrs_dict.get("itemprop") == "description" or attrs_dict.get("data-section") == "description":
            self._capture = "description"

    def handle_endtag(self, tag: str) -> None:
        if tag in {"section", "div"} and self._capture:
            self._capture = None

    def handle_data(self, data: str) -> None:
        if not self._capture:
            return
        text = data.strip()
        if not text:
            return
        if self._capture == "claims":
            self.claims_parts.append(text)
        elif self._capture == "description":
            self.description_parts.append(text)


class GooglePatentsFetcher:
    """Scrape claims/description via Google Patents HTML."""

    name = "google_patents"
    endpoint_template = "https://patents.google.com/patent/{doc}/en"

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._client = client or httpx.Client(timeout=60.0)

    def fetch(self, doc_number: str, jurisdiction: str) -> Tuple[Optional[str], Optional[str]]:
        try:
            url = self.endpoint_template.format(doc=doc_number)
            response = self._client.get(url)
            if response.status_code >= 400:
                return None, None
            parser = GooglePatentsHTMLParser()
            parser.feed(response.text)
            claims = "\n".join(parser.claims_parts) if parser.claims_parts else None
            description = "\n".join(parser.description_parts) if parser.description_parts else None
            return claims, description
        except Exception as exc:  # pragma: no cover - network failures
            LOGGER.warning("Google Patents scrape failed for %s: %s", doc_number, exc)
            return None, None


# ---------------------------------------------------------------------------
# Record merging and normalisation
# ---------------------------------------------------------------------------


@dataclass
class SnippetPayload:
    section: str
    start_char: int
    end_char: int
    text: str


@dataclass
class PatentRecord:
    doc_number: str
    jurisdiction: str
    kind_code: Optional[str]
    title: Optional[str]
    abstract: Optional[str]
    description: Optional[str]
    claims: Optional[str]
    family_id: Optional[str]
    priority_numbers: List[str]
    cpc_codes: List[str]
    ipc_codes: List[str]
    assignees: List[str]
    inventors: List[str]
    filing_date: Optional[date]
    publication_date: Optional[date]
    grant_date: Optional[date]
    earliest_priority_date: Optional[date]
    estimated_expiration: Optional[date]
    component_tags: List[str]
    source: Dict[str, Any]
    snippets: List[SnippetPayload]


def merge_records_by_family(records: Sequence[ProviderPatentRaw]) -> List[ProviderPatentRaw]:
    merged: Dict[str, ProviderPatentRaw] = {}
    family_metadata: Dict[str, Dict[str, Any]] = {}

    for record in records:
        key = record.doc_number or record.family_id or f"unknown-{record.provider}"
        family_key = record.family_id or record.doc_number

        fam_meta = family_metadata.setdefault(
            family_key,
            {
                "assignees": set(),
                "inventors": set(),
                "cpc_codes": set(),
                "ipc_codes": set(),
                "priority_numbers": set(),
            },
        )
        fam_meta["assignees"].update(record.assignees)
        fam_meta["inventors"].update(record.inventors)
        fam_meta["cpc_codes"].update(record.cpc_codes)
        fam_meta["ipc_codes"].update(record.ipc_codes)
        fam_meta["priority_numbers"].update(record.priority_numbers)

        existing = merged.get(key)
        if existing:
            merged[key] = merge_two_provider_records(existing, record)
        else:
            merged[key] = record

    enhanced: List[ProviderPatentRaw] = []
    for key, record in merged.items():
        family_key = record.family_id or record.doc_number
        fam_meta = family_metadata.get(family_key, {})
        enhanced.append(
            ProviderPatentRaw(
                doc_number=record.doc_number,
                jurisdiction=record.jurisdiction,
                kind_code=record.kind_code,
                family_id=record.family_id,
                title=record.title,
                abstract=record.abstract,
                claims=record.claims,
                description=record.description,
                filing_date=record.filing_date,
                publication_date=record.publication_date,
                grant_date=record.grant_date,
                assignees=sorted({*record.assignees, *fam_meta.get("assignees", set())}),
                inventors=sorted({*record.inventors, *fam_meta.get("inventors", set())}),
                cpc_codes=sorted({*record.cpc_codes, *fam_meta.get("cpc_codes", set())}),
                ipc_codes=sorted({*record.ipc_codes, *fam_meta.get("ipc_codes", set())}),
                priority_numbers=sorted({*record.priority_numbers, *fam_meta.get("priority_numbers", set())}),
                source=record.source,
                provider=record.provider,
            )
        )

    return enhanced


def merge_two_provider_records(left: ProviderPatentRaw, right: ProviderPatentRaw) -> ProviderPatentRaw:
    return ProviderPatentRaw(
        doc_number=left.doc_number or right.doc_number,
        jurisdiction=left.jurisdiction or right.jurisdiction,
        kind_code=left.kind_code or right.kind_code,
        family_id=left.family_id or right.family_id,
        title=left.title if len(left.title or "") >= len(right.title or "") else right.title,
        abstract=left.abstract if len(left.abstract or "") >= len(right.abstract or "") else right.abstract,
        claims=left.claims or right.claims,
        description=left.description or right.description,
        filing_date=left.filing_date or right.filing_date,
        publication_date=left.publication_date or right.publication_date,
        grant_date=left.grant_date or right.grant_date,
        assignees=sorted({*left.assignees, *right.assignees}),
        inventors=sorted({*left.inventors, *right.inventors}),
        cpc_codes=sorted({*left.cpc_codes, *right.cpc_codes}),
        ipc_codes=sorted({*left.ipc_codes, *right.ipc_codes}),
        priority_numbers=sorted({*left.priority_numbers, *right.priority_numbers}),
        source={"providers": sorted({left.provider, right.provider})},
        provider=f"{left.provider}+{right.provider}",
    )


# ---------------------------------------------------------------------------
# Component tagging and normalisation
# ---------------------------------------------------------------------------


DEFAULT_COMPONENT_PATTERNS = {
    "n_methylation": r"\bn-?methyl",
    "non_canonical_amino_acid": r"\bnon[-\s]?canonical amino",
    "cyclization": r"\bcycli[sz]ation",
    "flexizyme": r"\bflexizyme",
    "rapid_platform": r"\brapid platform",
}


def detect_component_tags(text: str, patterns: Dict[str, str]) -> List[str]:
    tags = []
    for name, pattern in patterns.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            tags.append(name)
    return tags


def safe_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def estimate_expiration(filing: Optional[date], priority: Optional[date]) -> Optional[date]:
    anchor = priority or filing
    if not anchor:
        return None
    return anchor + timedelta(days=20 * 365)


def chunk_text(text: Optional[str], section: str, chunk_size: int = 1200, overlap: int = 200) -> List[SnippetPayload]:
    if not text:
        return []
    snippets: List[SnippetPayload] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        snippets.append(SnippetPayload(section=section, start_char=start, end_char=end, text=text[start:end]))
        if end == length:
            break
        start = max(end - overlap, start + 1)
    return snippets


def normalise_to_patent_record(
    raw: ProviderPatentRaw,
    component_patterns: Optional[Dict[str, str]] = None,
    extra_synopsis: Optional[str] = None,
) -> PatentRecord:
    component_patterns = component_patterns or DEFAULT_COMPONENT_PATTERNS
    text_blob_parts = [raw.title or "", raw.abstract or "", raw.claims or "", raw.description or "", extra_synopsis or ""]
    text_blob = "\n".join(part for part in text_blob_parts if part)
    component_tags = detect_component_tags(text_blob, component_patterns)

    filing = safe_date(raw.filing_date)
    publication = safe_date(raw.publication_date)
    grant = safe_date(raw.grant_date)
    priority_candidates = [safe_date(entry) for entry in raw.priority_numbers if entry]
    priority = next((value for value in priority_candidates if value), None) or filing
    estimated_exp = estimate_expiration(filing, priority)

    snippets = []
    snippets.extend(chunk_text(raw.abstract, section="abstract"))
    snippets.extend(chunk_text(raw.claims, section="claims", chunk_size=1500, overlap=250))
    snippets.extend(chunk_text(raw.description, section="description", chunk_size=2000, overlap=400))

    if not snippets and extra_synopsis:
        snippets.extend(chunk_text(extra_synopsis, section="summary"))

    source_payload = dict(raw.source)
    source_payload.setdefault("provider", raw.provider)

    return PatentRecord(
        doc_number=raw.doc_number,
        jurisdiction=raw.jurisdiction,
        kind_code=raw.kind_code,
        title=raw.title,
        abstract=raw.abstract,
        description=raw.description,
        claims=raw.claims,
        family_id=raw.family_id,
        priority_numbers=[entry for entry in raw.priority_numbers if entry],
        cpc_codes=raw.cpc_codes,
        ipc_codes=raw.ipc_codes,
        assignees=raw.assignees,
        inventors=raw.inventors,
        filing_date=filing,
        publication_date=publication,
        grant_date=grant,
        earliest_priority_date=priority,
        estimated_expiration=estimated_exp,
        component_tags=component_tags,
        source=source_payload,
        snippets=snippets,
    )


# ---------------------------------------------------------------------------
# Full-text enrichment
# ---------------------------------------------------------------------------


def enrich_with_full_text(
    records: Sequence[ProviderPatentRaw],
    fetchers: Sequence[FullTextFetcher],
) -> List[ProviderPatentRaw]:
    enriched: List[ProviderPatentRaw] = []
    for record in records:
        claims = record.claims
        description = record.description
        if claims and description:
            enriched.append(record)
            continue
        for fetcher in fetchers:
            fetched_claims, fetched_description = fetcher.fetch(record.doc_number, record.jurisdiction)
            claims = claims or fetched_claims
            description = description or fetched_description
            if claims and description:
                break
        enriched.append(
            ProviderPatentRaw(
                doc_number=record.doc_number,
                jurisdiction=record.jurisdiction,
                kind_code=record.kind_code,
                family_id=record.family_id,
                title=record.title,
                abstract=record.abstract,
                claims=claims,
                description=description,
                filing_date=record.filing_date,
                publication_date=record.publication_date,
                grant_date=record.grant_date,
                assignees=record.assignees,
                inventors=record.inventors,
                cpc_codes=record.cpc_codes,
                ipc_codes=record.ipc_codes,
                priority_numbers=record.priority_numbers,
                source=record.source,
                provider=record.provider,
            )
        )
    return enriched


# ---------------------------------------------------------------------------
# Coverage report computation
# ---------------------------------------------------------------------------


@dataclass
class CoverageReport:
    canonical: int
    present: int
    missing: List[str]

    @property
    def coverage_ratio(self) -> float:
        if not self.canonical:
            return 1.0
        return self.present / self.canonical


def summarise_coverage(canonical_doc_numbers: Sequence[str], present_doc_numbers: Sequence[str]) -> CoverageReport:
    canonical_set = {doc.strip().upper() for doc in canonical_doc_numbers if doc}
    present_set = {doc.strip().upper() for doc in present_doc_numbers if doc}
    missing = sorted(canonical_set - present_set)
    return CoverageReport(
        canonical=len(canonical_set),
        present=len(canonical_set & present_set),
        missing=missing,
    )


# ---------------------------------------------------------------------------
# Provider aggregation helper
# ---------------------------------------------------------------------------


def collect_provider_records(providers: Sequence[PatentProvider], query: QueryConfig) -> List[ProviderPatentRaw]:
    collected: List[ProviderPatentRaw] = []
    for provider in providers:
        try:
            LOGGER.info("Fetching patents via %s", provider.name)
            payloads = provider.fetch(query)
            LOGGER.info("%s returned %s records", provider.name, len(payloads))
            collected.extend(payloads)
        except Exception as exc:  # pragma: no cover - network failure path
            LOGGER.warning("Provider %s failed: %s", provider.name, exc)
    return collected
