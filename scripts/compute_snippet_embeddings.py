"""Compute embeddings for snippets using OpenAI."""

from __future__ import annotations

import math
from itertools import islice
from typing import Iterable, List

from openai import OpenAI

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Snippet

MODEL_NAME = "text-embedding-3-large"
BATCH_SIZE = 16


def chunked(iterable: Iterable[str], size: int) -> Iterable[List[str]]:
    iterator = iter(iterable)
    while True:
        batch = list(islice(iterator, size))
        if not batch:
            break
        yield batch


def normalize(vector: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if not norm:
        return vector
    return [x / norm for x in vector]


def main() -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to compute embeddings.")

    client = OpenAI(api_key=settings.openai_api_key)

    with SessionLocal() as session:
        snippets = (
            session.query(Snippet)
            .filter(Snippet.embedding.is_(None))
            .all()
        )

        if not snippets:
            print("No snippets require embeddings.")
            return

        texts = [snippet.text for snippet in snippets]

        cursor = 0
        for batch in chunked(texts, BATCH_SIZE):
            response = client.embeddings.create(model=MODEL_NAME, input=batch)
            vectors = [normalize(item.embedding) for item in response.data]

            for i, vector in enumerate(vectors):
                snippet = snippets[cursor + i]
                snippet.embedding = vector

            cursor += len(batch)
            session.commit()
            print(f"Embedded {cursor}/{len(snippets)} snippets")


if __name__ == "__main__":
    main()
