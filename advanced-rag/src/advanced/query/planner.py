"""LLM query planner with deterministic guards: codes must appear in the conversation,
the network must be stated or implied by a code, and failures degrade to a regex plan."""

from __future__ import annotations

import re
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Final, Protocol

import structlog
from pydantic import BaseModel, Field

from advanced.config import Settings
from advanced.domain import CardNetwork, Turn
from advanced.errors import GenerationError
from advanced.ingestion.metadata import extract_reason_codes
from advanced.llm import StructuredLLM

log = structlog.get_logger(__name__)
PROMPTS_DIR: Final = Path(__file__).parent / "prompts"

_NETWORK_WORDS: Final[dict[CardNetwork, re.Pattern[str]]] = {
    CardNetwork.VISA: re.compile(r"\bvisa\b", re.IGNORECASE),
    CardNetwork.MASTERCARD: re.compile(r"\b(master\s?card|mc)\b", re.IGNORECASE),
    CardNetwork.AMEX: re.compile(r"\b(amex|american\s+express)\b", re.IGNORECASE),
    CardNetwork.DISCOVER: re.compile(r"\bdiscover\b", re.IGNORECASE),
}
_CODE_NETWORK: Final[tuple[tuple[re.Pattern[str], CardNetwork], ...]] = (
    (re.compile(r"^1[0-3]\.\d{1,2}$"), CardNetwork.VISA),
    (re.compile(r"^48\d{2}$"), CardNetwork.MASTERCARD),
    (re.compile(r"^[ACFMPR]\d{2}$"), CardNetwork.AMEX),
    (re.compile(r"^UA\d{2}$"), CardNetwork.DISCOVER),
)


class LLMQueryPlan(BaseModel):
    """Schema the planner model must return."""

    standalone_question: str
    sub_queries: list[str]
    card_network: CardNetwork | None
    reason_codes: list[str]
    in_scope: bool


class QueryPlan(BaseModel):
    """Validated plan used by retrieval."""

    standalone_question: str
    sub_queries: list[str] = Field(min_length=1)
    card_network: CardNetwork | None = None
    reason_codes: list[str] = Field(default_factory=list)
    in_scope: bool = True
    degraded: bool = False  # True when the LLM planner failed and the regex plan was used


class QueryPlanner(Protocol):
    async def plan(
        self, question: str, history: list[Turn], card_network: CardNetwork | None
    ) -> QueryPlan: ...


@lru_cache(maxsize=4)
def load_plan_prompt(version: str, max_queries: int) -> str:
    text = (PROMPTS_DIR / f"plan_{version}.md").read_text(encoding="utf-8")
    return text.format(max_queries=max_queries)


def mentioned_networks(text: str) -> set[CardNetwork]:
    named = {n for n, rx in _NETWORK_WORDS.items() if rx.search(text)}
    for code in extract_reason_codes(text, CardNetwork.ALL):
        named |= {n for rx, n in _CODE_NETWORK if rx.match(code)}
    return named


def regex_plan(question: str, history: list[Turn], card_network: CardNetwork | None) -> QueryPlan:
    """Fallback plan: no rewriting, filters from regex only."""
    networks = mentioned_networks(question)
    return QueryPlan(
        standalone_question=question,
        sub_queries=[question],
        card_network=card_network or (next(iter(networks)) if len(networks) == 1 else None),
        reason_codes=list(extract_reason_codes(question, CardNetwork.ALL)),
        degraded=True,
    )


def guard(
    raw: LLMQueryPlan,
    question: str,
    history: list[Turn],
    card_network: CardNetwork | None,
    max_queries: int,
) -> QueryPlan:
    """Never trust model-extracted filters that the conversation does not support."""
    convo = "\n".join([*(t.content for t in history), question])
    seen_codes = set(extract_reason_codes(convo, CardNetwork.ALL))
    codes = [c for c in dict.fromkeys(raw.reason_codes) if c in seen_codes]
    networks = mentioned_networks(f"{convo}\n{raw.standalone_question}")
    network = card_network
    if network is None and raw.card_network in networks and len(networks) == 1:
        network = raw.card_network  # a filter only when exactly one network is in play
    standalone = raw.standalone_question.strip() or question
    # The standalone question is always searched; up to `max_queries` sub-queries come on top.
    subs = [q.strip() for q in raw.sub_queries if q.strip() and q.strip() != standalone]
    return QueryPlan(
        standalone_question=standalone,
        sub_queries=[standalone, *list(dict.fromkeys(subs))[:max_queries]],
        card_network=network,
        reason_codes=codes,
        in_scope=raw.in_scope,
    )


def render_history(history: list[Turn]) -> str:
    return "\n".join(f"{t.role}: {escape(t.content)}" for t in history)


class LLMQueryPlanner:
    def __init__(self, llm: StructuredLLM, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def plan(
        self, question: str, history: list[Turn], card_network: CardNetwork | None
    ) -> QueryPlan:
        s = self._settings
        history = history[-s.history_max_turns :] if s.history_max_turns else []
        user_input = (
            f"<history>\n{render_history(history)}\n</history>\n\n"
            f"<question>\n{escape(question)}\n</question>"
        )
        try:
            raw = await self._llm.parse(
                model=s.fast_model,
                instructions=load_plan_prompt("v1", s.multi_query_max),
                user_input=user_input,
                schema=LLMQueryPlan,
                max_output_tokens=500,
                reasoning_effort=s.openai_fast_reasoning_effort,
                purpose="plan",
            )
        except GenerationError as e:
            log.warning("planner_degraded", error=str(e))
            return regex_plan(question, history, card_network)
        return guard(raw, question, history, card_network, s.multi_query_max)
