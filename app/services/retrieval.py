"""Hybrid retrieval service abstractions."""

from __future__ import annotations

import uuid
import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from openai import OpenAI
from sqlalchemy import func, literal
from sqlalchemy.orm import Session

from app import models
from app.core.config import get_settings


@dataclass
class Passage:
    """Container for retrieved passages and metadata."""

    doc_id: uuid.UUID
    text: str
    score: float
    metadata: Optional[dict] = None


class HybridRetriever:
    """Placeholder retriever combining sparse and dense search results."""

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self._openai_client: Optional[OpenAI] = None
        if self.settings.openai_api_key:
            self._openai_client = OpenAI(api_key=self.settings.openai_api_key)

    def retrieve(self, query: str, top_k: Optional[int] = None) -> List[Passage]:
        """Return ranked snippets that loosely match the query using Postgres FTS."""

        k = top_k or self.settings.retrieval_top_k
        if not query.strip():
            return []

        ts_query = func.plainto_tsquery("english", query)
        snippet_vector = func.to_tsvector("english", func.coalesce(models.Snippet.text, ""))
        title_vector = func.to_tsvector("english", func.coalesce(models.PatentDocument.title, ""))
        combined_vector = snippet_vector.op("||")(title_vector)
        rank = func.ts_rank_cd(combined_vector, ts_query)

        results = (
            self.db.query(models.Snippet, rank.label("rank"))
            .join(models.PatentDocument, models.Snippet.patent_id == models.PatentDocument.id)
            .filter(combined_vector.op("@@")(ts_query))
            .order_by(rank.desc())
            .limit(k)
            .all()
        )

        if not results:
            results = (
                self.db.query(models.Snippet, literal(0.1).label("rank"))
                .filter(models.Snippet.text.ilike(f"%{query}%"))
                .limit(k)
                .all()
            )

        if len(results) < k:
            vector_passages = self._vector_fallback(query, results, k)
            results.extend(vector_passages)

        # Ensure unique snippets and order by score descending.
        seen = set()
        deduped: List[Tuple[models.Snippet, float]] = []
        for snippet, score in results:
            if snippet.id in seen:
                continue
            seen.add(snippet.id)
            deduped.append((snippet, score))

        deduped.sort(key=lambda item: item[1], reverse=True)

        return [
            Passage(
                doc_id=snippet.patent_id,
                text=snippet.text,
                score=float(score or 0.0),
                metadata={
                    "section": snippet.section,
                    "start_char": snippet.start_char,
                    "end_char": snippet.end_char,
                },
            )
            for snippet, score in deduped[:k]
        ]

    def _vector_fallback(
        self, query: str, existing: Sequence[Tuple[models.Snippet, float]], top_k: int
    ) -> List[Tuple[models.Snippet, float]]:
        if not self._openai_client:
            return []

        query_embedding = self._embed_query(query)
        if not query_embedding:
            return []

        existing_ids = {snippet.id for snippet, _ in existing}
        candidate_limit = max(
            self.settings.retrieval_vector_candidate_limit,
            top_k * 3,
        )

        snippet_query = self.db.query(models.Snippet.id, models.Snippet.embedding).filter(
            models.Snippet.embedding.isnot(None)
        )
        if existing_ids:
            snippet_query = snippet_query.filter(~models.Snippet.id.in_(list(existing_ids)))

        candidate_rows = snippet_query.limit(candidate_limit).all()

        scored: List[Tuple[int, float]] = []
        for snippet_id, embedding in candidate_rows:
            if not embedding:
                continue
            similarity = self._cosine_similarity(query_embedding, embedding)
            if not similarity or similarity <= 0:
                continue
            if similarity < self.settings.retrieval_min_similarity:
                continue
            scored.append((snippet_id, similarity))

        if not scored:
            return []

        scored.sort(key=lambda item: item[1], reverse=True)
        needed = max(0, top_k - len(existing))
        top_pairs = scored[:needed]
        top_ids = [snippet_id for snippet_id, _ in top_pairs]

        snippets = (
            self.db.query(models.Snippet)
            .filter(models.Snippet.id.in_(top_ids))
            .all()
        )
        snippet_lookup = {snippet.id: snippet for snippet in snippets}

        return [
            (snippet_lookup[snippet_id], score)
            for snippet_id, score in top_pairs
            if snippet_id in snippet_lookup
        ]

    def _embed_query(self, query: str) -> Optional[List[float]]:
        if not self._openai_client or not query.strip():
            return None
        response = self._openai_client.embeddings.create(
            model="text-embedding-3-large", input=query
        )
        vector = response.data[0].embedding
        return self._normalize(vector)

    @staticmethod
    def _cosine_similarity(
        query_vec: Sequence[float], doc_vec: Sequence[float]
    ) -> Optional[float]:
        if not query_vec or not doc_vec or len(query_vec) != len(doc_vec):
            return None
        return sum(q * d for q, d in zip(query_vec, doc_vec))

    @staticmethod
    def _normalize(vector: Sequence[float]) -> List[float]:
        norm = math.sqrt(sum(x * x for x in vector))
        if not norm:
            return list(vector)
        return [x / norm for x in vector]