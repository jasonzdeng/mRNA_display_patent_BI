"""FastAPI entrypoint for the patent RAG MVP."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    """Instantiate and configure the FastAPI application."""

    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)

    if settings.frontend_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(settings.frontend_origin)],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    elif settings.allowed_hosts:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_hosts,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/health", tags=["health"])
    async def healthcheck() -> dict[str, str]:
        """Simple health-check endpoint."""

        return {"status": "ok"}

    return app


app = create_app()
