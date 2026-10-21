"""Fuse graph facts and text chunks into one prompt within a token budget."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Final

import tiktoken

from hybrid.domain import REFUSAL_TEXT, GraphFact, RetrievedChunk

PROMPTS_DIR: Final = Path(__file__).parent / "prompts"


@dataclass(frozen=True, slots=True)
class AssembledPrompt:
    instructions: str  # byte-stable per prompt version -> OpenAI prompt caching
    user_input: str
    chunks: tuple[RetrievedChunk, ...]  # exactly what was sent (for validation)
    facts: tuple[GraphFact, ...]
    prompt_version: str


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def _tokens(text: str) -> int:
    return len(_encoding().encode(text))


@lru_cache(maxsize=8)
def load_prompt(version: str) -> str:
    path = PROMPTS_DIR / f"answer_{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt version not found: {path.name}")
    return path.read_text(encoding="utf-8").format(refusal=REFUSAL_TEXT)


def _attrs(doc_id: str, section: str, effective: str) -> str:
    return f'doc="{escape(doc_id)}" section="{escape(section)}" effective="{effective}"'


def render_fact(i: int, f: GraphFact) -> str:
    attrs = _attrs(f.doc_id, f.section_path, f.effective_date.isoformat())
    return (
        f'<graph_fact id="G{i}" {attrs}>{escape(f.statement)}. '
        f'Quote: "{escape(f.quote)}"</graph_fact>'
    )


def render_source(c: RetrievedChunk) -> str:
    attrs = _attrs(c.doc_id, c.section_path, c.effective_date.isoformat())
    return f"<source {attrs}>\n{c.content}\n</source>"


def assemble(
    question: str,
    chunks: list[RetrievedChunk],
    facts: list[GraphFact],
    *,
    prompt_version: str,
    budget_tokens: int,
) -> AssembledPrompt:
    """Facts are small and exact, so they go in first; chunks fill the rest of the budget
    (lowest score dropped first, never truncated mid-chunk)."""
    fact_lines = [render_fact(i, f) for i, f in enumerate(facts, start=1)]
    remaining = budget_tokens - sum(_tokens(x) for x in fact_lines)
    kept: list[RetrievedChunk] = []
    for c in sorted(chunks, key=lambda c: c.score, reverse=True):
        cost = _tokens(render_source(c))
        if cost <= remaining:
            kept.append(c)
            remaining -= cost
    graph_block = "\n".join(fact_lines) or "(none)"
    source_block = "\n\n".join(render_source(c) for c in kept) or "(none)"
    user_input = (
        f"<graph_facts>\n{graph_block}\n</graph_facts>\n\n"
        f"<sources>\n{source_block}\n</sources>\n\n<question>\n{question}\n</question>"
    )
    return AssembledPrompt(
        instructions=load_prompt(prompt_version),
        user_input=user_input,
        chunks=tuple(kept),
        facts=tuple(facts),
        prompt_version=prompt_version,
    )
