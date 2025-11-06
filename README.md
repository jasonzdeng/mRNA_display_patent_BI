# Patent RAG MVP

This project delivers the foundational Retrieval-Augmented Generation (RAG) service for mRNA-display patent intelligence. It includes the FastAPI application, SQLAlchemy models, ingestion scripts, hybrid retrieval, and OpenAI-backed answer generation needed to stand up an end-to-end MVP.

## Current Progress

- FastAPI app, SQLAlchemy models, and retrieval/LLM services ship as a working MVP with pytest coverage.
- Multi-provider ingestion (`scripts/ingest_mrna_display.py`) aggregates USPTO PatentsView, WIPO PATENTSCOPE, and EPO OPS data, merges by family, and tags component coverage.
- Full-text enrichment hooks via Google Patents scraping or local dumps ensure claims/description snippets feed the hybrid retriever.
- Config-driven search templates (`configs/mrna_ingestion.json`) and canonical coverage reporting (`scripts/report_mrna_coverage.py`) give quick leverage to tune scope and validate completeness.

## Project structure

```
app/
  api/            # FastAPI routers and dependencies
  core/           # Configuration helpers
  db/             # SQLAlchemy base and session factories
  models/         # ORM models (patents, snippets, answers, watchlists)
  prompts/        # System prompt and tool schemas
  schemas/        # Pydantic request/response schemas
  services/       # Retrieval and LLM service stubs
  tests/          # Pytest smoke tests
  main.py         # FastAPI application entrypoint
```

## Getting started

1. **Install dependencies** (create a virtualenv first):
   ```powershell
   python -m venv .patent-env
   .\.patent-env\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. **Set environment variables** (copy `.env.example` to `.env` and adjust as needed):
   ```powershell
   $env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/patent_rag"
   $env:OPENAI_API_KEY = "sk-..."
   $env:PERPLEXITY_API_KEY = "px-..."  # optional, placeholder only
   ```
3. **Run the API server** (ensure `.patent-env` is active):
   ```powershell
   python -m uvicorn app.main:app --reload
   ```
4. Open `http://localhost:8000/docs` for interactive docs.
5. **Seed the starter corpus** (safe to rerun as needed):
   ```powershell
   python -m scripts.ingest_seed
   ```
6. **(Optional) Generate snippet embeddings** for hybrid retrieval (requires `OPENAI_API_KEY`):
   ```powershell
   python -m scripts.compute_snippet_embeddings
   ```
7. **Pull focused mRNA-display patents** across USPTO, WIPO, and EPO (use `--dry-run` first to preview):
   ```powershell
   python -m scripts.ingest_mrna_display --config configs\mrna_ingestion.json --max-pages 5 --save-raw
   ```
   Export `PATENTSVIEW_API_KEY` so the USPTO PatentsView client can authenticate (the endpoint now rejects anonymous requests). Set `WIPO_PATENTSCOPE_TOKEN` and `EPO_OPS_KEY`/`EPO_OPS_SECRET` to enable those providers. Add `--manual data\raw\mrna_display\curated.jsonl` to merge hand-picked documents—ensure the file contains one patent JSON object per line or omit the flag once upstream sources respond. Provider payloads are cached under `data/raw/mrna_display/` when `--save-raw` is set.
8. **Check corpus coverage** against your canonical patent list:
   ```powershell
   python -m scripts.report_mrna_coverage --canonical data\canonical_mrna_display.txt --output reports\coverage.json
   ```

> **Warning:** Do not commit your `.env` file. Sensitive keys are ignored via `.gitignore`.

## Next steps

1. Populate the canonical doc-number list with authoritative mRNA-display families (and optional curated JSONL supplements), then run:
   ```powershell
   python -m scripts.ingest_mrna_display --config configs\mrna_ingestion.json --dry-run --save-raw
   ```
   Ensure `PATENTSVIEW_API_KEY`, `WIPO_PATENTSCOPE_TOKEN`, `EPO_OPS_KEY`, and `EPO_OPS_SECRET` are exported so each provider can authenticate. If you rely on `--manual data\raw\mrna_display\curated.jsonl`, make sure that file is populated using the schema in `docs/data/curated_samples.md`.
2. When the dry run looks good, rerun without `--dry-run` to write into Postgres and follow up with:
   ```powershell
   python -m scripts.report_mrna_coverage --canonical <path-to-your-canonical-list>
   ```
   Review the missing list and iterate on filters until coverage is complete.
3. Layer in additional full-text sources (e.g., Lens.org API responses or partner data dumps) by extending the fetchers in `app/services/ingestion/mrna_pipeline.py` so claims/description coverage keeps pace with the expanded corpus.

## Testing

Run the pytest suite:
```powershell
pytest
```

The suite covers health checks, patent search, hybrid retrieval fallbacks, and LLM orchestration via service stubs.
