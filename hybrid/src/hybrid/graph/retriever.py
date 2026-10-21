"""Graph retrieval: map a `GraphPlan` to read-only templates and render facts."""

from __future__ import annotations

from datetime import date
from typing import Any, Final, LiteralString, Protocol

from neo4j import AsyncDriver
from neo4j.exceptions import Neo4jError
from neo4j.time import Date as NeoDate
from opentelemetry import trace

from hybrid.config import Settings
from hybrid.domain import DocId, FactKind, GraphFact
from hybrid.errors import RetrievalError
from hybrid.graph import queries
from hybrid.graph.planner import GraphPlan

_tracer = trace.get_tracer(__name__)
_NETWORK_LABEL: Final = {
    "visa": "Visa",
    "mastercard": "Mastercard",
    "amex": "American Express",
    "discover": "Discover",
}


class GraphRetriever(Protocol):
    async def facts(self, plan: GraphPlan, as_of: date) -> list[GraphFact]: ...


def select_queries(plan: GraphPlan, limit: int) -> list[tuple[LiteralString, dict[str, object]]]:
    """Pick templates for a plan. No signal means no graph lookup."""
    kinds = [k.value for k in (plan.kinds or list(FactKind))]
    nets = [n.value for n in plan.networks]
    chosen: list[tuple[LiteralString, dict[str, object]]] = []
    if plan.reason_codes:
        chosen.append((queries.FACTS_FOR_CODES, {"codes": plan.reason_codes, "kinds": kinds}))
    if plan.deadline_days is not None:
        chosen.append((queries.CODES_BY_DEADLINE, {"days": plan.deadline_days, "networks": nets}))
    if plan.category is not None:
        chosen.append(
            (queries.CODES_BY_CATEGORY, {"category": plan.category.value, "networks": nets})
        )
    if not chosen and nets and plan.kinds:
        chosen.append((queries.FACTS_FOR_NETWORKS, {"networks": nets, "kinds": kinds}))
    for _, params in chosen:
        params["limit"] = limit
    return chosen


def render(network: str, code: str, kind: FactKind, target: dict[str, Any]) -> str:
    """Deterministic statement text; the LLM never phrases graph facts itself."""
    who = f"{_NETWORK_LABEL.get(network, network.title() or 'Card network')} {code}"
    if kind is FactKind.DEADLINE:
        party, action, days = target.get("party"), target.get("action"), target.get("days")
        return f"{who}: {party} must {action} within {days} days"
    if kind is FactKind.REMEDY:
        return f"{who}: remedy: {target.get('name')}"
    if kind is FactKind.INSUFFICIENT:
        return f"{who}: not sufficient on its own: {target.get('name')}"
    return f"{who}: category: {target.get('name')}"


def _to_date(value: object) -> date:
    if isinstance(value, NeoDate):
        return value.to_native()
    if isinstance(value, date):
        return value
    raise RetrievalError(f"unexpected date type from Neo4j: {type(value).__name__}")


class Neo4jGraphRetriever:
    def __init__(self, driver: AsyncDriver, settings: Settings) -> None:
        self._driver = driver
        self._settings = settings

    async def facts(self, plan: GraphPlan, as_of: date) -> list[GraphFact]:
        s = self._settings
        selected = select_queries(plan, s.graph_max_facts)
        if not selected or not plan.in_scope:
            return []
        out: dict[tuple[str, str, str, str], GraphFact] = {}
        with _tracer.start_as_current_span("retrieval.graph"):
            try:
                async with self._driver.session(database=s.neo4j_database) as session:
                    for query, params in selected:
                        result = await session.run(query, {**params, "as_of": as_of})
                        async for rec in result:
                            kind = FactKind(rec["kind"])
                            target: dict[str, Any] = dict(rec["target"])
                            fact = GraphFact(
                                statement=render(rec["network"], rec["code"], kind, target),
                                quote=str(rec["quote"]),
                                network=str(rec["network"]),
                                code=str(rec["code"]),
                                kind=kind,
                                doc_id=DocId(str(rec["doc_id"])),
                                section_path=str(rec["section_path"]),
                                effective_date=_to_date(rec["effective_date"]),
                            )
                            out.setdefault(
                                (fact.code, kind.value, fact.statement, fact.doc_id), fact
                            )
            except Neo4jError as e:
                raise RetrievalError(f"graph query failed: {type(e).__name__}") from e
        return list(out.values())[: s.graph_max_facts]
