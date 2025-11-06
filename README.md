# Patent RAG MVP Skeleton

This repository contains a FastAPI skeleton for the mRNA-display patent intelligence MVP. It wires the core project layout, ORM models, API contracts, and prompt assets so the engineering team can start implementing ingestion, retrieval, and LLM orchestration.

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
2. **Set environment variables** (copy `.env.example` when you create one):
   ```powershell
   $env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/patent_rag"
   $env:OPENAI_API_KEY = "sk-..."
   ```
3. **Run the API server** (ensure `.patent-env` is active):
   ```powershell
   uvicorn app.main:app --reload
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

## Next implementation steps

- Implement the ingestion workers that populate `patent_document`, `snippet`, and related tables.
- Replace the placeholder summary in `LLMClient` with OpenAI-backed generation once embeddings & dense retrieval are tuned.
- Persist generated answers inside `/questions/ask` once the LLM flow is operational.
- Add migrations (e.g., Alembic) once the schema stabilises.

## Testing

Run the pytest suite:
```powershell
pytest
```

The included smoke test exercises the `/health` endpoint to verify the FastAPI app boots successfully.
