from __future__ import annotations

import re

from hybrid.domain import CardNetwork, Category, FactKind
from hybrid.errors import GenerationError
from hybrid.graph import queries
from hybrid.graph.planner import GraphPlan, LLMGraphPlan, LLMGraphPlanner, guard, regex_plan
from hybrid.graph.retriever import render, select_queries
from hybrid.ingestion import graph_store
from tests.fakes import FakeLLM, make_settings


def _raw(**kw: object) -> LLMGraphPlan:
    base: dict[str, object] = {
        "reason_codes": [],
        "networks": [],
        "kinds": ["deadline"],
        "deadline_days": None,
        "category": None,
        "in_scope": True,
    }
    base.update(kw)
    return LLMGraphPlan(**base)


def test_guard_keeps_days_only_if_in_question() -> None:
    q = "Which reason codes give the merchant 45 days to respond?"
    assert guard(_raw(deadline_days=45), q, None).deadline_days == 45
    assert guard(_raw(deadline_days=30), q, None).deadline_days is None


def test_guard_drops_invented_codes_and_unsupported_networks() -> None:
    q = "What evidence defends a dispute?"
    p = guard(_raw(reason_codes=["10.4"], networks=[CardNetwork.VISA]), q, None)
    assert p.reason_codes == [] and p.networks == []


def test_guard_network_implied_by_code_and_request_network_wins() -> None:
    q = "What is the window for 4853?"
    assert guard(
        _raw(reason_codes=["4853"], networks=[CardNetwork.MASTERCARD]), q, None
    ).networks == [CardNetwork.MASTERCARD]
    assert guard(_raw(networks=[CardNetwork.MASTERCARD]), q, CardNetwork.VISA).networks == [
        CardNetwork.VISA
    ]


def test_regex_plan_fallback() -> None:
    p = regex_plan("Amex C08 window?", None)
    assert p.degraded and p.reason_codes == ["C08"] and p.networks == [CardNetwork.AMEX]
    assert set(p.kinds) == set(FactKind)


async def test_planner_degrades_on_failure() -> None:
    planner = LLMGraphPlanner(FakeLLM(graph_plan=[GenerationError("x")]), make_settings())
    assert (await planner.plan("Visa 10.4?", None)).degraded


def test_select_queries_by_signal() -> None:
    assert select_queries(GraphPlan(), 12) == []
    q = [t for t, _ in select_queries(GraphPlan(reason_codes=["10.4"], deadline_days=30), 12)]
    assert q == [queries.FACTS_FOR_CODES, queries.CODES_BY_DEADLINE]
    ((t, params),) = select_queries(
        GraphPlan(networks=[CardNetwork.VISA], kinds=[FactKind.REMEDY]), 5
    )
    assert t == queries.FACTS_FOR_NETWORKS and params["limit"] == 5
    ((t, params),) = select_queries(GraphPlan(category=Category.FRAUD), 12)
    assert t == queries.CODES_BY_CATEGORY and params["category"] == "fraud"


def test_read_templates_are_read_only_and_time_filtered() -> None:
    for name in ("FACTS_FOR_CODES", "FACTS_FOR_NETWORKS", "CODES_BY_DEADLINE", "CODES_BY_CATEGORY"):
        cypher = getattr(queries, name)
        assert not re.search(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DETACH|CALL)\b", cypher), name
        assert "$as_of" in cypher and "LIMIT $limit" in cypher


def test_write_queries_use_parameters_only() -> None:
    for cypher in [graph_store.DELETE_CHUNK_FACTS, *graph_store.CREATE_FACTS.values()]:
        assert "{" not in cypher.replace("{code: row.code}", "").replace(
            "{key: row.target}", ""
        ).replace("{name: row.target}", "")


def test_render_statements() -> None:
    target = {"days": 45, "party": "merchant", "action": "respond"}
    assert render("mastercard", "4853", FactKind.DEADLINE, target) == (
        "Mastercard 4853: merchant must respond within 45 days"
    )
    assert render("amex", "C08", FactKind.REMEDY, {"name": "proof of delivery"}) == (
        "American Express C08: remedy: proof of delivery"
    )
