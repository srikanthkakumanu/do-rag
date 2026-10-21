"""LLM fact extraction for the knowledge graph. The model proposes; `guard()` decides."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Final, Literal, Protocol

import structlog
from pydantic import BaseModel

from hybrid.config import Settings
from hybrid.domain import Category, Chunk, FactKind, Party
from hybrid.errors import GenerationError
from hybrid.llm import StructuredLLM

log = structlog.get_logger(__name__)
PROMPT: Final = Path(__file__).parent / "prompts" / "extract_v1.md"
_KIND: Final[dict[str, FactKind]] = {
    "deadline": FactKind.DEADLINE,
    "remedy": FactKind.REMEDY,
    "insufficient": FactKind.INSUFFICIENT,
    "category": FactKind.CATEGORY,
}


class LLMFact(BaseModel):
    reason_code: str
    kind: Literal["deadline", "remedy", "insufficient", "category"]
    value: str | None
    days: int | None
    party: Literal["merchant", "cardholder", "issuer"] | None
    action: str | None
    quote: str


class LLMExtraction(BaseModel):
    facts: list[LLMFact]


@dataclass(frozen=True, slots=True)
class Fact:
    """A guarded fact ready for the graph. `target` is the node key (evidence/category
    name or deadline key)."""

    code: str
    kind: FactKind
    target: str
    quote: str
    days: int | None = None
    party: Party | None = None
    action: str | None = None


@dataclass(frozen=True, slots=True)
class Extraction:
    facts: tuple[Fact, ...]
    rejected: int
    failed: bool = False  # LLM call failed: the chunk must be retried, not indexed


class FactExtractor(Protocol):
    async def extract(self, chunk: Chunk) -> Extraction: ...


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().strip(".").lower()[:80]


def deadline_key(days: int, party: Party, action: str) -> str:
    return f"{days}|{party.value}|{normalize_name(action)}"


def guard(raw: LLMExtraction, chunk: Chunk) -> Extraction:
    """Keep a fact only if it is verifiably grounded in this chunk."""
    body = _norm(chunk.content)
    kept: list[Fact] = []
    rejected = 0
    for f in raw.facts:
        quote = _norm(f.quote)
        if f.reason_code not in chunk.reason_codes or not quote or quote not in body:
            rejected += 1
            continue
        kind = _KIND[f.kind]
        if kind is FactKind.DEADLINE:
            if f.days is None or f.party is None or not f.action:
                rejected += 1
                continue
            if not re.search(rf"(?<!\d){f.days}(?!\d)", quote):
                rejected += 1
                continue
            party = Party(f.party)
            kept.append(
                Fact(
                    code=f.reason_code,
                    kind=kind,
                    target=deadline_key(f.days, party, f.action),
                    quote=f.quote.strip(),
                    days=f.days,
                    party=party,
                    action=normalize_name(f.action),
                )
            )
        elif kind is FactKind.CATEGORY:
            if f.value not in {c.value for c in Category}:
                rejected += 1
                continue
            kept.append(Fact(f.reason_code, kind, f.value, f.quote.strip()))
        else:
            name = normalize_name(f.value or "")
            if not name:
                rejected += 1
                continue
            kept.append(Fact(f.reason_code, kind, name, f.quote.strip()))
    unique = tuple(dict.fromkeys(kept))
    return Extraction(facts=unique, rejected=rejected + len(kept) - len(unique))


class LLMFactExtractor:
    def __init__(self, llm: StructuredLLM, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def extract(self, chunk: Chunk) -> Extraction:
        """A failed call returns `failed=True`; the pipeline defers the chunk (both stores)."""
        if not chunk.reason_codes:
            return Extraction(facts=(), rejected=0)
        try:
            raw = await self._llm.parse(
                model=self._settings.fast_model,
                instructions=PROMPT.read_text(encoding="utf-8"),
                user_input=(
                    f"<codes>{', '.join(chunk.reason_codes)}</codes>\n\n"
                    f"<chunk>\n{escape(chunk.content)}\n</chunk>"
                ),
                schema=LLMExtraction,
                max_output_tokens=1200,
                reasoning_effort=self._settings.openai_fast_reasoning_effort,
                purpose="extract",
            )
        except GenerationError as e:
            log.warning("extract_failed", chunk_id=chunk.chunk_id, error=str(e))
            return Extraction(facts=(), rejected=0, failed=True)
        return guard(raw, chunk)


async def extract_all(
    extractor: FactExtractor, chunks: list[Chunk], concurrency: int
) -> dict[str, Extraction]:
    """Extract for many chunks with bounded concurrency; keyed by chunk_id."""
    sem = asyncio.Semaphore(concurrency)

    async def one(c: Chunk) -> tuple[str, Extraction]:
        async with sem:
            return c.chunk_id, await extractor.extract(c)

    return dict(await asyncio.gather(*(one(c) for c in chunks)))
