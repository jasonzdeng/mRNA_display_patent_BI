"""Smoke test for the FastAPI healthcheck."""

from fastapi.testclient import TestClient

from app.main import app


def test_healthcheck() -> None:
    """The /health endpoint should return a success payload."""

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
