"""Typed test doubles at the Protocol boundaries (no real network calls)."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel

from hybrid.config import ReasoningEffort, Settings
from hybrid.domain import (
    CardNetwork,
    Chunk,
    ChunkId,
    DocId,
    FactKind,
    GraphFact,
    Party,
    RetrievedChunk,
)
from hybrid.generation.assembler import AssembledPrompt
from hybrid.generation.llm import LLMAnswer, LLMCitation
from hybrid.graph.planner import GraphPlan
from hybrid.ingestion.extract import Extraction, Fact, deadline_key
from hybrid.retrieval.retriever import RetrievalQuery

DIMS = 128


def make_settings(**overrides: object) -> Settings:
    """Settings isolated from any real hybrid/.env file."""
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
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=ChunkId(f"{doc_id}-{section}"),
        doc_id=DocId(doc_id),
        section_path=section,
        effective_date=date(2026, 1, 1),
        content=content,
        score=score,
    )


def make_fact(
    code: str = "4853",
    days: int = 45,
    doc_id: str = "mc-4853",
    section: str = "Mastercard 4853 > Response window",
    network: str = "mastercard",
) -> GraphFact:
    return GraphFact(
        statement=f"{network.title()} {code}: merchant must respond within {days} days",
        quote=f"The merchant has {days} calendar days to respond.",
        network=network,
        code=code,
        kind=FactKind.DEADLINE,
        doc_id=DocId(doc_id),
        section_path=section,
        effective_date=date(2026, 1, 1),
    )


def cited_answer(text: str, *pairs: tuple[str, str]) -> LLMAnswer:
    return LLMAnswer(
        answer=text,
        citations=[LLMCitation(doc_id=d, section_path=s) for d, s in pairs],
        refused=False,
    )


class FakeLLM:
    """`StructuredLLM` returning scripted outputs per `purpose`; records calls."""

    def __init__(self, **scripts: list[BaseModel | Exception]) -> None:
        self._scripts = scripts
        self.calls: list[tuple[str, str]] = []

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


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.queries: list[RetrievalQuery] = []

    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]:
        self.queries.append(q)
        return self.chunks


class FakeGraphPlanner:
    def __init__(self, plan: GraphPlan) -> None:
        self.result = plan

    async def plan(self, question: str, card_network: CardNetwork | None) -> GraphPlan:
        return self.result


class FakeGraphRetriever:
    def __init__(self, facts: list[GraphFact]) -> None:
        self._facts = facts
        self.plans: list[GraphPlan] = []

    async def facts(self, plan: GraphPlan, as_of: date) -> list[GraphFact]:
        self.plans.append(plan)
        return self._facts


_DEADLINE = re.compile(
    r"(?P<sent>[^.\n]*?\b(?:within|has)\s+(?P<days>\d+)\s+(?:calendar\s+)?days\b[^.\n]*\.?)",
    re.IGNORECASE,
)


class RegexExtractor:
    """Deterministic extractor: one merchant deadline per 'within/has N days' sentence."""

    def __init__(self, fail_codes: set[str] | None = None) -> None:
        self.calls = 0
        self.fail_codes = fail_codes or set()

    async def extract(self, chunk: Chunk) -> Extraction:
        self.calls += 1
        if self.fail_codes & set(chunk.reason_codes):
            return Extraction(facts=(), rejected=0, failed=True)
        facts = []
        for m in _DEADLINE.finditer(chunk.content):
            days = int(m.group("days"))
            for code in chunk.reason_codes:
                facts.append(
                    Fact(
                        code=code,
                        kind=FactKind.DEADLINE,
                        target=deadline_key(days, Party.MERCHANT, "respond"),
                        quote=m.group("sent").strip(),
                        days=days,
                        party=Party.MERCHANT,
                        action="respond",
                    )
                )
        return Extraction(facts=tuple(facts), rejected=0)


class MemoryGraphStore:
    """In-memory `GraphStore`: chunk_id -> (facts, superseded_on)."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[tuple[Fact, ...], date]] = {}

    def replace_facts(self, chunk: Chunk, facts: Sequence[Fact], superseded_on: date) -> None:
        self.rows[chunk.chunk_id] = (tuple(facts), superseded_on)

    def set_superseded(self, ids: Sequence[ChunkId], superseded_on: date) -> None:
        for cid in ids:
            if cid in self.rows:
                self.rows[cid] = (self.rows[cid][0], superseded_on)

    def delete_facts(self, ids: Sequence[ChunkId]) -> None:
        for cid in ids:
            self.rows.pop(cid, None)
