"""Listwise LLM reranker: grades each candidate section 0-3 for the question."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Final, Protocol

import structlog
import tiktoken
from pydantic import BaseModel, Field

from advanced.config import Settings
from advanced.domain import RetrievedSection
from advanced.errors import GenerationError
from advanced.llm import StructuredLLM

log = structlog.get_logger(__name__)
PROMPT: Final = Path(__file__).parent / "prompts" / "rerank_v1.md"
EXCERPT_TOKENS: Final = 250


class Grade(BaseModel):
    id: str
    score: int = Field(ge=0, le=3)


class RerankResult(BaseModel):
    grades: list[Grade]


class Reranker(Protocol):
    async def rerank(
        self, question: str, sections: list[RetrievedSection]
    ) -> list[RetrievedSection]: ...


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def excerpt(text: str, max_tokens: int = EXCERPT_TOKENS) -> str:
    tokens = _encoding().encode(text)
    return text if len(tokens) <= max_tokens else _encoding().decode(tokens[:max_tokens]) + " …"


def render_candidates(sections: list[RetrievedSection]) -> str:
    return "\n\n".join(
        f'<candidate id="S{i}">\n{escape(excerpt(s.content))}\n</candidate>'
        for i, s in enumerate(sections, start=1)
    )


def apply_grades(sections: list[RetrievedSection], result: RerankResult) -> list[RetrievedSection]:
    """Map short IDs back; unknown IDs are ignored and ungraded sections score 0."""
    grades = {g.id.strip().upper(): g.score for g in result.grades}
    graded = [replace(s, score=float(grades.get(f"S{i}", 0))) for i, s in enumerate(sections, 1)]
    return sorted(graded, key=lambda s: s.score, reverse=True)  # stable: keeps fused order on ties


class LLMReranker:
    def __init__(self, llm: StructuredLLM, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def rerank(
        self, question: str, sections: list[RetrievedSection]
    ) -> list[RetrievedSection]:
        """Return sections sorted by grade. On LLM failure, keep fused order with
        `min_rerank_score` so a reranker outage degrades quality, not availability."""
        if not sections:
            return []
        s = self._settings
        try:
            result = await self._llm.parse(
                model=s.fast_model,
                instructions=PROMPT.read_text(encoding="utf-8"),
                user_input=(
                    f"<question>\n{escape(question)}\n</question>\n\n{render_candidates(sections)}"
                ),
                schema=RerankResult,
                max_output_tokens=400,
                reasoning_effort=s.openai_fast_reasoning_effort,
                purpose="rerank",
            )
        except GenerationError as e:
            log.warning("reranker_degraded", error=str(e))
            return [replace(x, score=float(s.min_rerank_score)) for x in sections]
        return apply_grades(sections, result)
