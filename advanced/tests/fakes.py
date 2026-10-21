"""Typed test doubles at the Protocol boundaries (no real network calls)."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import date

from pydantic import BaseModel

from advanced.config import ReasoningEffort, Settings
from advanced.domain import (
    CardNetwork,
    ChunkId,
    DocId,
    RetrievedChunk,
    RetrievedSection,
    SectionId,
    Turn,
)
from advanced.generation.assembler import AssembledPrompt
from advanced.generation.llm import LLMAnswer, LLMCitation
from advanced.query.planner import QueryPlan
from advanced.retrieval.retriever import RetrievalQuery

DIMS = 128


def make_settings(**overrides: object) -> Settings:
    """Settings isolated from any real advanced/.env file."""
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


def make_section(
    doc_id: str = "visa-10-4",
    section: str = "Visa 10.4 > Response window",
    content: str = "The merchant must respond within 30 calendar days.",
    score: float = 3.0,
    effective: date = date(2026, 1, 1),
) -> RetrievedSection:
    return RetrievedSection(
        section_id=SectionId(f"{doc_id}|{section}"),
        doc_id=DocId(doc_id),
        section_path=section,
        effective_date=effective,
        content=content,
        score=score,
    )


def hit(parent: str, doc: str = "visa-10-4", score: float = 1.0, n: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=ChunkId(f"{parent}#{n}"),
        parent_id=SectionId(parent),
        doc_id=DocId(doc),
        score=score,
    )


def plan(
    question: str = "What is the Visa 10.4 window?",
    *,
    sub_queries: list[str] | None = None,
    network: CardNetwork | None = None,
    in_scope: bool = True,
) -> QueryPlan:
    return QueryPlan(
        standalone_question=question,
        sub_queries=sub_queries or [question],
        card_network=network,
        in_scope=in_scope,
    )


class FakeLLM:
    """`StructuredLLM` returning scripted outputs per `purpose`; records calls."""

    def __init__(self, **scripts: list[BaseModel | Exception]) -> None:
        self._scripts = scripts
        self.calls: list[tuple[str, str]] = []  # (purpose, user_input)

    async def parse[T: BaseModel](
        self,
        *,
        model: str,
        instructions: str,
        user_input: str,
        schema: type[T],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort | None = None,
        purpose: str,
    ) -> T:
        self.calls.append((purpose, user_input))
        nxt = self._scripts[purpose].pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        assert isinstance(nxt, schema)
        return nxt


class FakeAnswerer:
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


class FakePlanner:
    def __init__(self, result: QueryPlan) -> None:
        self.result = result
        self.calls: list[tuple[str, list[Turn]]] = []

    async def plan(
        self, question: str, history: list[Turn], card_network: CardNetwork | None
    ) -> QueryPlan:
        self.calls.append((question, history))
        return self.result


class FakeRetriever:
    """Returns hits per query text (default list otherwise)."""

    def __init__(self, default: list[RetrievedChunk], **by_text: list[RetrievedChunk]) -> None:
        self.default = default
        self.by_text = by_text
        self.queries: list[RetrievalQuery] = []

    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]:
        self.queries.append(q)
        return self.by_text.get(q.text, self.default)


class FakeSectionStore:
    def __init__(self, *sections: RetrievedSection) -> None:
        self.sections = {s.section_id: s for s in sections}

    async def fetch(self, ids: list[SectionId]) -> list[RetrievedSection]:
        return [self.sections[i] for i in ids if i in self.sections]


class FakeReranker:
    """Assigns fixed grades by section_id (default 3)."""

    def __init__(self, grades: dict[str, float] | None = None) -> None:
        self.grades = grades or {}

    async def rerank(
        self, question: str, sections: list[RetrievedSection]
    ) -> list[RetrievedSection]:
        from dataclasses import replace

        graded = [replace(s, score=self.grades.get(s.section_id, 3.0)) for s in sections]
        return sorted(graded, key=lambda s: s.score, reverse=True)
