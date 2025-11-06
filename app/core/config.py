"""Application configuration via environment variables."""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, HttpUrl

try:  # Pydantic v2
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # Fallback for Pydantic v1
    from pydantic import BaseSettings

    SettingsConfigDict = dict  # type: ignore[assignment]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = Field("Patent RAG MVP", description="Human-readable service name.")
    environment: str = Field("dev", description="Deployment environment tag.")
    debug: bool = Field(False, description="Enable FastAPI debug mode.")

    api_v1_prefix: str = Field("/api", description="Root prefix for versioned API routes.")
    frontend_origin: Optional[HttpUrl] = Field(
        None, description="Optional frontend origin allowed for CORS policies."
    )

    database_url: str = Field(
        "postgresql+psycopg://postgres:postgres@localhost:5432/patent_rag",
        description="SQLAlchemy database URL with credentials and host.",
    )

    openai_api_key: Optional[str] = Field(
        None, description="API key used for OpenAI Chat/Embedding models."
    )
    openai_model: str = Field(
        "gpt-4o-mini",
        description="Default OpenAI model for LLM answer generation.",
    )
    perplexity_api_key: Optional[str] = Field(
        None, description="API key for optional Perplexity lookups."
    )

    retrieval_top_k: int = Field(8, description="Default number of passages to retrieve per query.")
    retrieval_min_score: float = Field(
        0.0, description="Minimum hybrid score threshold before admitting a passage."
    )
    retrieval_min_similarity: float = Field(
        0.3,
        description="Minimum cosine similarity required for vector fallback passages.",
    )
    retrieval_vector_candidate_limit: int = Field(
        512,
        description="Maximum number of vector candidates to score during fallback retrieval.",
    )

    allowed_hosts: List[str] = Field(
        default_factory=lambda: ["*"], description="Hosts allowed to access the service."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache()
def get_settings() -> Settings:
    """Provide a cached Settings instance."""

    return Settings()