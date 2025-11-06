"""Integration tests for patent search and QA endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from scripts.ingest_seed import main as seed_main


@pytest.fixture(scope="module", autouse=True)
def seed_database() -> None:
    """Ensure the database contains the seed patents before tests run."""

    seed_main()


client = TestClient(app)


def test_patent_search_returns_seed_records() -> None:
    response = client.get("/api/patents", params={"q": "RaPID"})
    assert response.status_code == 200
    data = response.json()
    assert any(
        "rapid" in ((item.get("source") or {}).get("notes", "").lower())
        for item in data
    )


def test_question_answer_endpoint_returns_citations() -> None:
    response = client.post("/api/questions/ask", json={"question": "RaPID"})
    assert response.status_code == 200
    body = response.json()
    assert "answer_md" in body
    assert "Technical landscaping only – not legal advice." in body["answer_md"]
    assert body["citations"]
    first_doc_id = body["citations"][0]["doc_id"]
    uuid.UUID(first_doc_id)  # validates UUID format


def test_question_answer_returns_404_for_unknown_query() -> None:
    response = client.post("/api/questions/ask", json={"question": "nonexistentterm"})
    assert response.status_code == 404
    body = response.json()
    assert body["detail"] == "No supporting documents found for the query."
