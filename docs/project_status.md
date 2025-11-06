# Patent RAG MVP Status Report

_Last updated: 2025-11-06 (PM)_

## Current Scope

- FastAPI service skeleton with modular layout (API routers, services, schemas, DB models).
- PostgreSQL schema for patents, snippets, answers, and watch targets; SQLAlchemy ORM integrated.
- Seed ingestion script populates starter corpus from curated JSON and ensures tables exist.
- Embedding script computes normalized OpenAI embeddings for snippets (optional, idempotent).
- Hybrid retrieval service combining PostgreSQL FTS results with vector fallback (similarity thresholding and candidate caps).
- LLM orchestration service using OpenAI Responses API with Chat Completions fallback, cost estimation, disclaimer guard, and JSON validation.
- REST endpoints for health, patent search, and question answering with deterministic fallback when no context.
- Pytest suite covering health check, patent search, QA success/404 behavior, LLM service stubs, and vector fallback constraints.
- Repository initialized and published to GitHub (`jasonzdeng/mRNA_display_patent_BI`) with default branch `main` and secrets stripped from history.
- Targeted ingestion script (`scripts/ingest_mrna_display.py`) pulls mRNA-display filings from PatentsView, normalizes metadata, tags component coverage, and stores snippets.
- WIPO PATENTSCOPE and EPO OPS clients integrated into the ingestion pipeline with family-level merging and optional full-text enrichment via Google Patents/local dumps.
- Configurable query templates (`configs/mrna_ingestion.json`) expose synonym, CPC/IPC, and applicant filters; raw payload snapshots saved under `data/raw/mrna_display/`.
- Coverage reporting utility (`scripts/report_mrna_coverage.py`) compares ingested corpus against a canonical list to flag gaps.

## MVP Question Targets

1. Which active patents cover the core mRNA-display service components (N-methylation workflows, incorporation of non-canonical amino acids, cyclization chemistries) that would block competitors?
2. Which patent documents constitute the canonical, must-have set for this technical space, and does our corpus capture them all?
3. What are the expiration dates and patent-family timelines for those key components across jurisdictions?
4. How do these expirations impact competitive freedom-to-operate for other service providers once protections lapse?
5. Are there any blocking continuations, reissues, or litigation outcomes that extend or modify enforceability for those components?
6. What jurisdictions and claim scopes (composition, method, use) are covered vs uncovered for each key patent family?
7. Where are the white-space opportunities or gaps in protection that signal potential for new offerings or filings?

## Technical Highlights

- Configuration via Pydantic v2 `Settings`, centralized in `app/core/config.py`.
- Retrieval safeguards: similarity thresholding, candidate limits, deduping, and synchronous FastAPI endpoints to avoid event-loop blocking.
- LLM client emits structured JSON, estimates cost when usage metadata is missing, guards against invalid JSON, and works even if Responses API is unavailable.
- Tests run cleanly under Python 3.13 (no warnings) after timezone-aware datetime updates.
- Dependencies pinned for compatibility (`openai` Responses support, SQLAlchemy 2.0.36+, Pydantic 2.9+).
- `.gitignore` protects environment files; `.env` is no longer tracked.

## Deployment Notes

- Minimum requirements: Python 3.13, PostgreSQL 15+, and OpenAI API credentials exported in a `.env` file (not checked in).
- Local bootstrap: `python -m uvicorn app.main:app --reload` against a running Postgres instance with `app/db/init_db.py` executed once for schema + seed data.
- Database migrations are manual today; apply schema changes by re-running the seed script or executing DDL statements directly.
- Production ready path: package the FastAPI app behind a process manager (e.g., `gunicorn` with `uvicorn.workers.UvicornWorker`) and point to managed Postgres; set `APP_ENV` to distinguish staging vs production configs.
- Monitoring hooks: enable FastAPI access logs and capture OpenAI usage leveraging the cost estimation helpers for observability until full APM is wired up.

## API Examples

- Health check

```bash
curl http://localhost:8000/health
```

- Patent search (returns top matches with hybrid retrieval)

```bash
curl -X POST http://localhost:8000/api/patents/search \
   -H "Content-Type: application/json" \
   -d '{"query": "macrocyclic peptide patents", "limit": 5}'
```

- Question answering (falls back to deterministic response when no context)

```bash
curl -X POST http://localhost:8000/api/questions/ask \
   -H "Content-Type: application/json" \
   -d '{"question": "What patents cover mRNA display with ncAA cyclization?"}'
```

## Outstanding Gaps vs. Business Needs

1. **Corpus coverage**: No automated ingestion of comprehensive patents for N-methylation, non-canonical amino acids, cyclization chemistry, etc. Current dataset is illustrative only.
2. **Domain tagging**: Patents/snippets lack taxonomy for component mapping, preventing direct answers about key technical areas.
3. **Expiration analytics**: Expiration dates, continuations, and legal status are stored but not analyzed or surfaced.
4. **Landscape completeness**: No tooling to confirm whether the corpus captures the full set of relevant patents.
5. **Competitive implications**: LLM lacks structured context to reason about post-expiration opportunities.
6. **Evaluation framework**: No benchmark or human-in-the-loop review to measure answer quality.

## Next Key Steps

1. **Validate canonical coverage**
   - Populate the canonical doc-number list (and optional curated JSONL) with authoritative mRNA-display families. Ensure any `data/raw/mrna_display/curated.jsonl` file contains one JSON object per line using the schema in `docs/data/curated_samples.md`.
   - Request a PatentsView API key (https://patentsview.org/apis/api-key) and export `PATENTSVIEW_API_KEY` alongside `WIPO_PATENTSCOPE_TOKEN`, `EPO_OPS_KEY`, and `EPO_OPS_SECRET` before running `python -m scripts.ingest_mrna_display --config configs/mrna_ingestion.json --dry-run --save-raw`.
2. **Commit ingestion results**
   - Rerun the ingestion without `--dry-run` once authentication succeeds (403 errors typically indicate missing `PATENTSVIEW_API_KEY`).
   - Execute `python -m scripts.report_mrna_coverage --canonical <path>` and review any missing patents.
3. **Broaden full-text sources**
   - Extend the fetchers in `app/services/ingestion/mrna_pipeline.py` (e.g., Lens.org API or partner datasets) so claims/description coverage keeps up with the expanded corpus.

## Suggested Extensions

- Trend analysis: filing velocity by assignee/inventor and region.
- Pending pipeline: highlight continuations or related applications still in prosecution.
- Competitive mapping: link patents to commercial offerings or academic publications.
- Collaboration support: exportable briefs summarizing key findings and expiration timelines.
- CI/CD pipeline with automated tests and linting on pull requests.
