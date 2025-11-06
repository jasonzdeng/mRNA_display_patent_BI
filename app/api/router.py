"""Aggregate API router for the FastAPI application."""

from fastapi import APIRouter

from app.api.routes import patents, questions

api_router = APIRouter()
api_router.include_router(patents.router)
api_router.include_router(questions.router)