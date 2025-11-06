"""LLM orchestration helpers for question answering."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from openai import OpenAI

from app.core.config import Settings, get_settings
from app.services.retrieval import Passage


DISCLAIMER = "Technical landscaping only – not legal advice."


@dataclass
class LLMAnswer:
    """Structured LLM answer payload following the JSON contract."""

    answer_md: str
    citations: List[dict]
    followups: List[str]
    red_flags: List[str]
    cost_usd: float
    latency_ms: int

    def model_dump(self) -> dict:
        """Return a dict ready for API responses."""

        return {
            "answer_md": self.answer_md,
            "citations": self.citations,
            "followups": self.followups,
            "red_flags": self.red_flags,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
        }


class LLMClient:
    """Wrapper around the downstream LLM provider."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._client: Optional[OpenAI] = None
        if self.settings.openai_api_key:
            self._client = OpenAI(api_key=self.settings.openai_api_key)

    @property
    def is_configured(self) -> bool:
        """Return True if an OpenAI client is available."""

        return self._client is not None

    @property
    def system_prompt_path(self) -> Path:
        """Location of the canonical system prompt file."""

        return Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.md"

    def load_system_prompt(self) -> str:
        """Read the system prompt template from disk."""

        return self.system_prompt_path.read_text(encoding="utf-8")

    def generate_answer(self, question: str, passages: List[Passage]) -> LLMAnswer:
        """Call the LLM provider and return the structured answer."""

        if not self._client:
            raise RuntimeError("OpenAI client not configured.")

        context_blocks = []
        for idx, passage in enumerate(passages[: self.settings.retrieval_top_k]):
            meta_section = passage.metadata.get("section") if passage.metadata else "unknown"
            context_blocks.append(
                f"Doc {idx+1} | doc_id={passage.doc_id} | section={meta_section}\n{passage.text}"
            )
        context_payload = "\n\n".join(context_blocks)

        schema = {
            "name": "ask_response",
            "schema": {
                "type": "object",
                "properties": {
                    "answer_md": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sent_idx": {"type": "integer"},
                                "doc_id": {"type": "string"},
                                "offsets": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                            },
                            "required": ["sent_idx", "doc_id", "offsets"],
                        },
                    },
                    "followups": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "red_flags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["answer_md", "citations", "followups", "red_flags"],
            },
        }

        start_time = time.perf_counter()
        cost_usd = 0.0
        raw_output = ""

        if hasattr(self._client, "responses"):
            response = self._client.responses.create(  # type: ignore[attr-defined]
                model=self.settings.openai_model,
                temperature=0.0,
                input=[
                    {
                        "role": "system",
                        "content": self.load_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Question: {question}"},
                            {"type": "text", "text": f"Context:\n{context_payload}"},
                        ],
                    },
                ],
                response_format={"type": "json_schema", "json_schema": schema},
            )
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            raw_output = response.output[0].content[0].text  # type: ignore[index]
            cost_usd = float(
                getattr(getattr(response, "usage", None), "total_cost", 0.0) or 0.0
            )
        elif hasattr(getattr(self._client, "chat", None), "completions"):
            completion = self._client.chat.completions.create(  # type: ignore[attr-defined]
                model=self.settings.openai_model,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self.load_system_prompt()},
                    {
                        "role": "user",
                        "content": (
                            "Answer the question using JSON per the schema. "
                            f"Question: {question}\nContext:\n{context_payload}"
                        ),
                    },
                ],
            )
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            raw_output = completion.choices[0].message.content or ""
            usage = getattr(completion, "usage", None)
            if usage and getattr(usage, "total_cost", None) is not None:
                cost_usd = float(usage.total_cost or 0.0)
            elif usage:
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                estimated = self._estimate_cost_from_tokens(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                if estimated is not None:
                    cost_usd = estimated
        else:
            raise RuntimeError(
                "OpenAI client does not expose Responses or Chat Completions APIs; upgrade the SDK."
            )

        if not raw_output:
            raise RuntimeError("LLM response body was empty.")

        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LLM response was not valid JSON.") from exc

        answer_md = payload.get("answer_md", "").strip()
        if DISCLAIMER not in answer_md:
            answer_md = f"{answer_md}\n\n{DISCLAIMER}" if answer_md else DISCLAIMER

        return LLMAnswer(
            answer_md=answer_md,
            citations=payload.get("citations", []),
            followups=payload.get("followups", []),
            red_flags=payload.get("red_flags", []),
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )

    def _estimate_cost_from_tokens(
        self, *, prompt_tokens: int, completion_tokens: int
    ) -> Optional[float]:
        """Estimate cost in USD when usage.total_cost is unavailable."""

        if prompt_tokens <= 0 and completion_tokens <= 0:
            return None

        pricing_table = {
            "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
            "gpt-4o": {"prompt": 0.0025, "completion": 0.01},
            "gpt-4.1-mini": {"prompt": 0.00015, "completion": 0.0006},
        }

        rates = pricing_table.get(self.settings.openai_model)
        if not rates:
            return None

        prompt_rate = rates.get("prompt", 0.0)
        completion_rate = rates.get("completion", 0.0)

        cost = (prompt_tokens / 1000) * prompt_rate
        cost += (completion_tokens / 1000) * completion_rate
        return cost
