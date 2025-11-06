# Patent RAG MVP

This project delivers the foundational Retrieval-Augmented Generation (RAG) service for mRNA-display patent intelligence. It includes the FastAPI application, SQLAlchemy models, ingestion scripts, hybrid retrieval, and OpenAI-backed answer generation needed to stand up an end-to-end MVP.

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

> **Warning:** Do not commit your `.env` file. Sensitive keys are ignored via `.gitignore`.

## Next implementation steps

- Build ingestion workers that populate `patent_document`, `snippet`, and related tables from authoritative sources.
- Expand retrieval with database-backed vector search (e.g., pgvector) and topical filters.
- Persist generated answers and track question history once the LLM flow is production-ready.
- Introduce analytics for key patent components (expiration timelines, coverage gaps, assignee insights).
- Add migrations (e.g., Alembic) and CI/CD automation as the schema stabilises.

## Testing

Run the pytest suite:
```powershell
pytest
```

The suite covers health checks, patent search, hybrid retrieval fallbacks, and LLM orchestration via service stubs.
