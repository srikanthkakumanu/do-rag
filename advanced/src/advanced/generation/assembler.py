"""Prompt assembly within a token budget. Static prefix first (cache-friendly)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Final

import tiktoken

from advanced.domain import REFUSAL_TEXT, RetrievedSection

PROMPTS_DIR: Final = Path(__file__).parent / "prompts"


@dataclass(frozen=True, slots=True)
class AssembledPrompt:
    instructions: str  # byte-stable per prompt version -> OpenAI prompt caching
    user_input: str
    sections: tuple[RetrievedSection, ...]  # exactly the sections sent (for validation)
    prompt_version: str


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


@lru_cache(maxsize=8)
def load_prompt(version: str) -> str:
    """Load a versioned prompt file; versions are immutable once released."""
    path = PROMPTS_DIR / f"answer_{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt version not found: {path.name}")
    return path.read_text(encoding="utf-8").format(refusal=REFUSAL_TEXT)


def render_source(c: RetrievedSection) -> str:
    return (
        f'<source id="{escape(c.doc_id)}" section="{escape(c.section_path)}" '
        f'effective="{c.effective_date.isoformat()}">\n{c.content}\n</source>'
    )


def fit_budget(sections: list[RetrievedSection], budget_tokens: int) -> list[RetrievedSection]:
    """Drop lowest-score sections (never truncate mid-chunk) until sources fit."""
    kept = sorted(sections, key=lambda c: c.score, reverse=True)
    enc = _encoding()
    while kept and sum(len(enc.encode(render_source(c))) for c in kept) > budget_tokens:
        kept.pop()
    return kept


def assemble(
    question: str, sections: list[RetrievedSection], *, prompt_version: str, budget_tokens: int
) -> AssembledPrompt:
    kept = fit_budget(sections, budget_tokens)
    sources = "\n\n".join(render_source(c) for c in kept)
    user_input = f"<sources>\n{sources}\n</sources>\n\n<question>\n{question}\n</question>"
    return AssembledPrompt(
        instructions=load_prompt(prompt_version),
        user_input=user_input,
        sections=tuple(kept),
        prompt_version=prompt_version,
    )
