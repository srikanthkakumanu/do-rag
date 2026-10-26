from __future__ import annotations

from datetime import date

from advanced.domain import REFUSAL_TEXT, CardNetwork
from advanced.rag import AdvancedRag
from tests.fakes import (
    FakeAnswerer,
    FakePlanner,
    FakeReranker,
    FakeRetriever,
    FakeSectionStore,
    cited_answer,
    hit,
    make_section,
    make_settings,
    plan,
)

SEC_A = make_section(doc_id="mc-4853", section="MC 4853 > Window", content="45 calendar days.")
SEC_B = make_section(doc_id="visa-10-4", section="Visa 10.4 > Window", content="30 calendar days.")
GOOD = cited_answer("45 calendar days.", ("mc-4853", "MC 4853 > Window"))


def _rag(
    *,
    p: object = None,
    retriever: FakeRetriever | None = None,
    reranker: FakeReranker | None = None,
    answerer: FakeAnswerer | None = None,
) -> tuple[AdvancedRag, FakeRetriever, FakeAnswerer]:
    retriever = retriever or FakeRetriever([hit(SEC_A.section_id, "mc-4853")])
    answerer = answerer or FakeAnswerer(GOOD)
    rag = AdvancedRag(
        planner=FakePlanner(p or plan("Mastercard 4853 window?")),  # type: ignore[arg-type]
        retriever=retriever,
        sections=FakeSectionStore(SEC_A, SEC_B),
        reranker=reranker or FakeReranker(),
        answerer=answerer,
        settings=make_settings(),
    )
    return rag, retriever, answerer


async def test_out_of_scope_refuses_without_retrieval() -> None:
    rag, retriever, answerer = _rag(p=plan("weather?", in_scope=False))
    result = await rag.answer("weather?", [])
    assert result.answer.answer == REFUSAL_TEXT
    assert result.refusal_reason == "out_of_scope"
    assert retriever.queries == [] and answerer.prompts == []


async def test_happy_path_returns_cited_answer_with_trace() -> None:
    rag, _, _ = _rag()
    result = await rag.answer("Mastercard 4853 window?", [])
    assert not result.answer.refused
    assert result.retrieved_doc_ids == ["mc-4853"]
    assert result.rerank_scores == [3.0]


async def test_every_sub_query_searched_with_plan_filters() -> None:
    p = plan("Compare", sub_queries=["Compare", "visa 10.4", "mc 4853"], network=CardNetwork.VISA)
    rag, retriever, _ = _rag(p=p)
    await rag.answer("Compare", [])
    assert [q.text for q in retriever.queries] == ["Compare", "visa 10.4", "mc 4853"]
    assert {q.card_network for q in retriever.queries} == {CardNetwork.VISA}


async def test_low_rerank_scores_trigger_corrective_refusal() -> None:
    rag, _, answerer = _rag(reranker=FakeReranker({SEC_A.section_id: 1.0}))
    result = await rag.answer("q", [])
    assert result.refusal_reason == "low_relevance"
    assert answerer.prompts == []


async def test_no_candidates_refuses() -> None:
    rag, _, answerer = _rag(retriever=FakeRetriever([]))
    result = await rag.answer("q", [])
    assert result.refusal_reason == "no_candidates"
    assert answerer.prompts == []


async def test_parents_sent_to_answerer_are_full_sections_ranked_by_rerank() -> None:
    retriever = FakeRetriever(
        [hit(SEC_B.section_id, "visa-10-4"), hit(SEC_A.section_id, "mc-4853")]
    )
    reranker = FakeReranker({SEC_A.section_id: 3.0, SEC_B.section_id: 2.0})
    rag, _, answerer = _rag(retriever=retriever, reranker=reranker)
    await rag.answer("q", [])
    sent = answerer.prompts[0].sections
    assert [s.section_id for s in sent] == [SEC_A.section_id, SEC_B.section_id]
    assert sent[0].content == SEC_A.content


async def test_candidates_capped_per_document_for_diversity() -> None:
    many = [make_section(doc_id="visa-10-4", section=f"V{i}", content="x") for i in range(5)]
    other = make_section(doc_id="amex-core", section="F29", content="y")
    retriever = FakeRetriever(
        [*(hit(s.section_id, "visa-10-4") for s in many), hit(other.section_id, "amex-core")]
    )
    rag = AdvancedRag(
        planner=FakePlanner(plan()),
        retriever=retriever,
        sections=FakeSectionStore(*many, other),
        reranker=FakeReranker(),
        answerer=FakeAnswerer(),
        settings=make_settings(max_sections_per_doc=2),
    )
    cands = await rag.retrieve(plan(), date(2026, 1, 1))
    assert [c.doc_id for c in cands] == ["visa-10-4", "visa-10-4", "amex-core"]
