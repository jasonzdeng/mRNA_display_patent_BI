"""Unit tests for service-layer helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.db.session import SessionLocal
from app.models import PatentDocument, Snippet
from app.services.llm import DISCLAIMER, LLMClient, Passage
from app.services.retrieval import HybridRetriever


class _StubResponses:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def create(self, **_: object) -> SimpleNamespace:
        output = [SimpleNamespace(content=[SimpleNamespace(text=json.dumps(self.payload))])]
        usage = SimpleNamespace(total_cost=0.123)
        return SimpleNamespace(output=output, usage=usage)


class _StubChat:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def completions(self) -> None:  # pragma: no cover - placeholder for attribute inspection
        raise NotImplementedError

    def _create(self, **_: object) -> SimpleNamespace:
        message = SimpleNamespace(content=json.dumps(self.payload))
        choice = SimpleNamespace(message=message)
        usage = SimpleNamespace(total_cost=0.456)
        return SimpleNamespace(choices=[choice], usage=usage)


def test_llm_generate_answer_uses_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(openai_api_key=None)
    client = LLMClient(settings=settings)
    payload = {
        "answer_md": "Result",
        "citations": [{"sent_idx": 0, "doc_id": str(uuid4()), "offsets": [[0, 5]]}],
        "followups": ["Question"],
        "red_flags": [],
    }
    stub = SimpleNamespace(responses=_StubResponses(payload))
    client._client = stub  # type: ignore[attr-defined]
    monkeypatch.setattr(client, "load_system_prompt", lambda: "system")

    passages = [Passage(doc_id=uuid4(), text="context", score=1.0, metadata={})]

    answer = client.generate_answer("What?", passages)

    assert DISCLAIMER in answer.answer_md
    assert answer.citations
    assert answer.cost_usd == pytest.approx(0.123)


def test_llm_generate_answer_falls_back_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(openai_api_key=None)
    client = LLMClient(settings=settings)

    payload = {
        "answer_md": "Another",
        "citations": [{"sent_idx": 0, "doc_id": str(uuid4()), "offsets": [[0, 5]]}],
        "followups": [],
        "red_flags": [],
    }

    chat_impl = _StubChat(payload)

    def create_completion(**kwargs: object) -> SimpleNamespace:
        return chat_impl._create(**kwargs)

    completions = SimpleNamespace(create=create_completion)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[attr-defined]
    monkeypatch.setattr(client, "load_system_prompt", lambda: "system")

    passages = [Passage(doc_id=uuid4(), text="context", score=1.0, metadata={})]
    answer = client.generate_answer("What?", passages)

    assert answer.answer_md.endswith(DISCLAIMER)
    assert answer.cost_usd == pytest.approx(0.456)


def test_vector_fallback_respects_candidate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    with SessionLocal() as session:
        doc = PatentDocument(
            doc_number="TEST-DOC",
            jurisdiction="US",
            kind_code="A1",
            title="Title",
        )
        session.add(doc)
        session.flush()

        embeddings = [
            [1.0, 0.0, 0.0],
            [0.8, 0.1, 0.0],
            [0.2, 0.5, 0.0],
        ]
        for idx, vector in enumerate(embeddings):
            snippet = Snippet(
                patent_id=doc.id,
                section="abstract",
                start_char=0,
                end_char=10,
                text=f"Snippet {idx}",
                embedding=vector,
            )
            session.add(snippet)
        session.flush()

        retriever = HybridRetriever(session)
        retriever._openai_client = object()  # type: ignore[attr-defined]
        original_limit = retriever.settings.retrieval_vector_candidate_limit
        retriever.settings.retrieval_vector_candidate_limit = 2
        monkeypatch.setattr(retriever, "_embed_query", lambda _: [1.0, 0.0, 0.0])

        results = retriever._vector_fallback("query", [], top_k=5)

        assert len(results) <= retriever.settings.retrieval_vector_candidate_limit
        assert all(result[0].text in {"Snippet 0", "Snippet 1"} for result in results)
        session.rollback()
        retriever.settings.retrieval_vector_candidate_limit = original_limit