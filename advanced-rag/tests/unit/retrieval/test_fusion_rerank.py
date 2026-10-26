from __future__ import annotations

from advanced.domain import SectionId
from advanced.errors import GenerationError
from advanced.retrieval.fusion import rrf_parents
from advanced.retrieval.reranker import (
    Grade,
    LLMReranker,
    RerankResult,
    apply_grades,
    excerpt,
    render_candidates,
)
from tests.fakes import FakeLLM, hit, make_section, make_settings


def test_rrf_rewards_parents_found_by_multiple_queries() -> None:
    q1 = [hit("A"), hit("B")]
    q2 = [hit("B"), hit("C")]
    fused = rrf_parents([q1, q2], k=60)
    assert [sid for sid, _ in fused] == ["B", "A", "C"]


def test_rrf_counts_one_vote_per_parent_per_list() -> None:
    fused = dict(rrf_parents([[hit("A", n=0), hit("A", n=1), hit("B")]], k=60))
    assert fused[SectionId("A")] == 1 / 61
    assert fused[SectionId("B")] == 1 / 63  # rank is positional: B is the third hit


def test_apply_grades_maps_short_ids_and_defaults_missing_to_zero() -> None:
    a, b, c = make_section(section="a"), make_section(section="b"), make_section(section="c")
    out = apply_grades(
        [a, b, c], RerankResult(grades=[Grade(id="s2", score=3), Grade(id="S9", score=3)])
    )
    assert [(x.section_path, x.score) for x in out] == [("b", 3.0), ("a", 0.0), ("c", 0.0)]


def test_render_candidates_escapes_and_truncates() -> None:
    sec = make_section(content="<b>x</b> " + "word " * 1000)
    rendered = render_candidates([sec])
    assert 'id="S1"' in rendered and "&lt;b&gt;" in rendered
    assert rendered.count("word") < 400
    assert excerpt("short") == "short"


async def test_reranker_degrades_to_fused_order_on_failure() -> None:
    secs = [make_section(section="a"), make_section(section="b")]
    reranker = LLMReranker(FakeLLM(rerank=[GenerationError("down")]), make_settings())
    out = await reranker.rerank("q", secs)
    assert [x.section_path for x in out] == ["a", "b"]
    assert all(x.score == make_settings().min_rerank_score for x in out)


async def test_reranker_sorts_by_grade() -> None:
    secs = [make_section(section="a"), make_section(section="b")]
    llm = FakeLLM(rerank=[RerankResult(grades=[Grade(id="S1", score=1), Grade(id="S2", score=3)])])
    out = await LLMReranker(llm, make_settings()).rerank("q", secs)
    assert [x.section_path for x in out] == ["b", "a"]
