"""Typed test doubles at the Protocol boundaries (no real network calls)."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import date

from basic.config import Settings
from basic.domain import ChunkId, DocId, RetrievedChunk
from basic.generation.assembler import AssembledPrompt
from basic.generation.llm import LLMAnswer, LLMCitation, SchemaParseError
from basic.retrieval.retriever import RetrievalQuery

DIMS = 128


def make_settings(**overrides: object) -> Settings:
    """Settings isolated from any real basic-rag/.env file."""
    base: dict[str, object] = {"openai_chat_model": "test-model", "_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]  # reason: dynamic overrides in tests


def fake_embed(text: str) -> list[float]:
    """Deterministic bag-of-words hashing embedder (stands in for OpenAI in tests)."""
    vec = [0.0] * DIMS
    for word in re.findall(r"[a-z0-9.]+", text.lower()):
        idx = int(hashlib.md5(word.encode(), usedforsecurity=False).hexdigest(), 16) % DIMS
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def make_chunk(
    doc_id: str = "visa-10-4",
    section: str = "Visa 10.4 > Response window",
    content: str = "The merchant must respond within 30 calendar days.",
    score: float = 0.9,
    effective: date = date(2026, 1, 1),
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=ChunkId(f"{doc_id}-{section}"),
        doc_id=DocId(doc_id),
        section_path=section,
        effective_date=effective,
        content=content,
        score=score,
    )


class FakeAnswerer:
    """Returns scripted answers; records every prompt it receives."""

    def __init__(self, *answers: LLMAnswer | Exception) -> None:
        self._answers = list(answers)
        self.prompts: list[AssembledPrompt] = []

    @property
    def model(self) -> str:
        return "test-model"

    async def generate(self, prompt: AssembledPrompt) -> LLMAnswer:
        self.prompts.append(prompt)
        nxt = self._answers.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def cited_answer(text: str, *pairs: tuple[str, str]) -> LLMAnswer:
    return LLMAnswer(
        answer=text,
        citations=[LLMCitation(doc_id=d, section_path=s) for d, s in pairs],
        refused=False,
    )


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.queries: list[RetrievalQuery] = []

    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]:
        self.queries.append(q)
        return self.chunks


__all__ = ["SchemaParseError"]
