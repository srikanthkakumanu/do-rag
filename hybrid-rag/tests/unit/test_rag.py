from __future__ import annotations

from hybrid.domain import CardNetwork
from hybrid.graph.planner import GraphPlan
from hybrid.rag import HybridRag
from tests.fakes import (
    FakeAnswerer,
    FakeGraphPlanner,
    FakeGraphRetriever,
    FakeRetriever,
    cited_answer,
    make_chunk,
    make_fact,
    make_settings,
)

FACT_SEC = "Mastercard 4853 > Response window"
SEC = "Visa 10.4 > Response window"


def _rag(
    plan: GraphPlan,
    *,
    chunks: bool = True,
    facts: bool = True,
    answerer: FakeAnswerer | None = None,
) -> tuple[HybridRag, FakeRetriever, FakeGraphRetriever, FakeAnswerer]:
    retriever = FakeRetriever([make_chunk()] if chunks else [])
    graph = FakeGraphRetriever([make_fact()] if facts else [])
    answerer = answerer or FakeAnswerer(
        cited_answer("Mastercard 4853: 45 days.", ("mc-4853", FACT_SEC))
    )
    rag = HybridRag(
        planner=FakeGraphPlanner(plan),
        graph=graph,
        retriever=retriever,
        answerer=answerer,
        settings=make_settings(),
    )
    return rag, retriever, graph, answerer


async def test_planner_out_of_scope_only_skips_graph_answer_step_decides() -> None:
    rag, _, graph, answerer = _rag(
        GraphPlan(in_scope=False),
        answerer=FakeAnswerer(cited_answer("Respond within 30 days.", ("visa-10-4", SEC))),
    )
    result = await rag.answer("What is the maximum PDF size?")
    assert graph.plans == []  # graph skipped
    assert len(answerer.prompts) == 1 and answerer.prompts[0].facts == ()
    assert not result.answer.refused


async def test_fuses_graph_facts_and_chunks_into_one_prompt() -> None:
    rag, retriever, _, answerer = _rag(GraphPlan(deadline_days=45))
    result = await rag.answer("Which codes give 45 days?", card_network=CardNetwork.MASTERCARD)
    sent = answerer.prompts[0]
    assert len(sent.facts) == 1 and len(sent.chunks) == 1
    assert result.facts == 1 and result.fact_doc_ids == ["mc-4853"]
    assert retriever.queries[0].card_network is CardNetwork.MASTERCARD
    assert not result.answer.refused


async def test_graph_only_evidence_still_answers() -> None:
    rag, _, _, _ = _rag(GraphPlan(deadline_days=45), chunks=False)
    assert not (await rag.answer("Which codes give 45 days?")).answer.refused


async def test_no_evidence_refuses() -> None:
    rag, _, _, answerer = _rag(GraphPlan(), chunks=False, facts=False)
    result = await rag.answer("q?")
    assert result.refusal_reason == "no_evidence" and answerer.prompts == []
