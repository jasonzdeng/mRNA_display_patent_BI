# Patent RAG MVP Status Report

_Last updated: 2025-11-06_

## Current Scope

- FastAPI service skeleton with modular layout (API routers, services, schemas, DB models).
- PostgreSQL schema for patents, snippets, answers, and watch targets; SQLAlchemy ORM integrated.
- Seed ingestion script populates starter corpus from curated JSON and ensures tables exist.
- Embedding script computes normalized OpenAI embeddings for snippets (optional, idempotent).
- Hybrid retrieval service combining PostgreSQL FTS results with vector fallback.
- LLM orchestration service using OpenAI Responses API with Chat Completions fallback and disclaimer guard.
- REST endpoints for health, patent search, and question answering with deterministic fallback when no context.
- Pytest suite covering health check, patent search, QA success/404 behavior, LLM service stubs, and vector fallback constraints.

## Technical Highlights

- Configuration via Pydantic v2 `Settings`, centralized in `app/core/config.py`.
- Retrieval safeguards: similarity thresholding, candidate limits, and result deduping.
- LLM client emits structured JSON, tracks cost/latency, and works even if Responses API is unavailable.
- Tests run cleanly under Python 3.13 (no warnings) after timezone-aware datetime updates.
- Dependencies pinned for compatibility (`openai` Responses support, SQLAlchemy 2.0.36+, Pydantic 2.9+).

## Outstanding Gaps vs. Business Needs

1. **Corpus coverage**: No automated ingestion of comprehensive patents for N-methylation, non-canonical amino acids, cyclization chemistry, etc. Current dataset is illustrative only.
2. **Domain tagging**: Patents/snippets lack taxonomy for component mapping, preventing direct answers about key technical areas.
3. **Expiration analytics**: Expiration dates, continuations, and legal status are stored but not analyzed or surfaced.
4. **Landscape completeness**: No tooling to confirm whether the corpus captures the full set of relevant patents.
5. **Competitive implications**: LLM lacks structured context to reason about post-expiration opportunities.
6. **Evaluation framework**: No benchmark or human-in-the-loop review to measure answer quality.

## Next Key Steps

1. **Data acquisition**
   - Stand up ingestion jobs (public APIs, bulk data, vendor feeds) filtered for mRNA display technologies.
   - Normalize assignees, inventors, CPC codes, and build patent family linkages.
2. **Domain enrichment**
   - Annotate patents/snippets with component labels (N-methylation, ncAAs, cyclization) via rules or ML models.
   - Capture processing chemistry, claim scope, and known competitors as structured fields.
3. **Analytics layer**
   - Implement expiration calculators covering priority, PCT, regional variants, and extensions.
   - Build summaries for key dates, coverage gaps, and family completeness.
4. **Retrieval enhancements**
   - Move vector search into the database (pgvector or external index) for scalability and filtering.
   - Add facet and filter options (component type, assignee, jurisdiction, claim scope).
5. **LLM answer quality**
   - Design prompts combining structured analytics with snippets.
   - Add failure-path handling, grounding checks, and bias mitigation.
6. **Evaluation & UX**
   - Create benchmark question sets with verified answers.
   - Surface results via UI or reporting templates; include confidence and coverage indicators.
7. **Operational readiness**
   - Introduce migrations (Alembic), CI/CD, environment configs, and monitoring hooks.

## Suggested Extensions

- Trend analysis: filing velocity by assignee/inventor and region.
- Pending pipeline: highlight continuations or related applications still in prosecution.
- Competitive mapping: link patents to commercial offerings or academic publications.
- Collaboration support: exportable briefs summarizing key findings and expiration timelines.
