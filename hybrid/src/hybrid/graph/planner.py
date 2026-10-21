"""Graph-lookup planner: an LLM proposes, `guard()` keeps only what the question supports."""

from __future__ import annotations

import re
from collections.abc import Sequence
from html import escape
from pathlib import Path
from typing import Final, Literal, Protocol

import structlog
from pydantic import BaseModel, Field

from hybrid.config import Settings
from hybrid.domain import CardNetwork, Category, FactKind
from hybrid.errors import GenerationError
from hybrid.ingestion.metadata import extract_reason_codes
from hybrid.llm import StructuredLLM

log = structlog.get_logger(__name__)
PROMPT: Final = Path(__file__).parent / "prompts" / "plan_v1.md"

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
_KINDS: Final[dict[str, FactKind]] = {
    "deadline": FactKind.DEADLINE,
    "remedy": FactKind.REMEDY,
    "insufficient": FactKind.INSUFFICIENT,
    "category": FactKind.CATEGORY,
}
type KindName = Literal["deadline", "remedy", "insufficient", "category"]


class LLMGraphPlan(BaseModel):
    reason_codes: list[str]
    networks: list[CardNetwork]
    kinds: list[KindName]
    deadline_days: int | None
    category: Category | None
    in_scope: bool


class GraphPlan(BaseModel):
    reason_codes: list[str] = Field(default_factory=list)
    networks: list[CardNetwork] = Field(default_factory=list)
    kinds: list[FactKind] = Field(default_factory=list)
    deadline_days: int | None = None
    category: Category | None = None
    in_scope: bool = True
    degraded: bool = False


class GraphPlanner(Protocol):
    async def plan(self, question: str, card_network: CardNetwork | None) -> GraphPlan: ...


def mentioned_networks(text: str) -> set[CardNetwork]:
    named = {n for n, rx in _NETWORK_WORDS.items() if rx.search(text)}
    for code in extract_reason_codes(text, CardNetwork.ALL):
        named |= {n for rx, n in _CODE_NETWORK if rx.match(code)}
    return named


def _with_request_network(
    nets: Sequence[CardNetwork], card_network: CardNetwork | None
) -> list[CardNetwork]:
    if card_network is None or card_network is CardNetwork.ALL:
        return list(nets)
    return [card_network]


def regex_plan(question: str, card_network: CardNetwork | None) -> GraphPlan:
    """Fallback: codes and networks by regex, all fact kinds."""
    codes = list(extract_reason_codes(question, CardNetwork.ALL))
    nets = sorted(mentioned_networks(question))
    return GraphPlan(
        reason_codes=codes,
        networks=_with_request_network(nets, card_network),
        kinds=list(FactKind) if codes or nets else [],
        degraded=True,
    )


def guard(raw: LLMGraphPlan, question: str, card_network: CardNetwork | None) -> GraphPlan:
    """Codes must appear in the question, networks must be named or implied by a code,
    and `deadline_days` must be a number written in the question."""
    seen_codes = set(extract_reason_codes(question, CardNetwork.ALL))
    supported = mentioned_networks(question)
    days = raw.deadline_days
    if days is not None and not re.search(rf"(?<![\d.]){days}(?![\d.])", question):
        days = None
    nets = [n for n in dict.fromkeys(raw.networks) if n in supported and n is not CardNetwork.ALL]
    return GraphPlan(
        reason_codes=[c for c in dict.fromkeys(raw.reason_codes) if c in seen_codes],
        networks=_with_request_network(nets, card_network),
        kinds=[_KINDS[k] for k in dict.fromkeys(raw.kinds)],
        deadline_days=days,
        category=raw.category,
        in_scope=raw.in_scope,
    )


class LLMGraphPlanner:
    def __init__(self, llm: StructuredLLM, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def plan(self, question: str, card_network: CardNetwork | None) -> GraphPlan:
        try:
            raw = await self._llm.parse(
                model=self._settings.fast_model,
                instructions=PROMPT.read_text(encoding="utf-8"),
                user_input=f"<question>\n{escape(question)}\n</question>",
                schema=LLMGraphPlan,
                max_output_tokens=300,
                reasoning_effort=self._settings.openai_fast_reasoning_effort,
                purpose="graph_plan",
            )
        except GenerationError as e:
            log.warning("graph_planner_degraded", error=str(e))
            return regex_plan(question, card_network)
        return guard(raw, question, card_network)
