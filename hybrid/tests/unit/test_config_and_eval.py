from __future__ import annotations

from eval.run import GoldenItem, Outcome, compute_metrics, gate, load_golden
from tests.fakes import make_settings


def test_settings_parse_weaviate_url() -> None:
    s = make_settings(weaviate_url="https://weaviate.internal:9443")
    assert (s.weaviate_host, s.weaviate_http_port, s.weaviate_secure) == (
        "weaviate.internal",
        9443,
        True,
    )


def test_settings_secret_not_in_repr() -> None:
    s = make_settings(openai_api_key="sk-test-123")
    assert "sk-test-123" not in repr(s)


def test_golden_set_size_and_coverage() -> None:
    items = load_golden()
    assert len(items) >= 50
    assert any(i.must_refuse for i in items)
    networks = {i.card_network for i in items if i.card_network}
    assert {n.value for n in networks} >= {"visa", "mastercard", "amex", "discover"}
    assert sum(1 for i in items if len(i.expected_doc_ids) > 1) >= 5  # aggregate questions


def _o(expected: tuple[str, ...], refuse: bool, got: tuple[str, ...], refused: bool) -> Outcome:
    return Outcome(
        item=GoldenItem(question="q", expected_doc_ids=expected, must_refuse=refuse),
        retrieved_doc_ids=got,
        cited_doc_ids=() if refused else got[:1],
        refused=refused,
        latency_ms=100.0,
    )


def test_compute_metrics_and_gate() -> None:
    outcomes = [
        _o(("a",), False, ("a", "b"), False),
        _o(("b",), False, ("c",), False),
        _o((), True, (), True),
    ]
    m = compute_metrics(outcomes)
    assert m["recall_at_5"] == 0.5
    assert m["citation_accuracy"] == 0.5
    assert m["refusal_precision"] == 1.0
    assert m["refusal_recall"] == 1.0
    assert m["coverage"] == 1.0  # no multi-doc items here
    assert "recall_at_5" in gate(m)


def test_coverage_counts_share_of_expected_docs_cited() -> None:
    o = Outcome(
        item=GoldenItem(question="q", expected_doc_ids=("a", "b"), must_refuse=False),
        retrieved_doc_ids=("a", "b"),
        cited_doc_ids=("a",),
        refused=False,
        latency_ms=1.0,
    )
    assert compute_metrics([o])["coverage"] == 0.5


def test_only_api_key_is_required_models_have_defaults() -> None:
    from hybrid.config import Settings

    s = Settings(_env_file=None)
    assert (s.openai_chat_model, s.fast_model) == ("gpt-5.4-mini", "gpt-5.4-nano")
    assert (s.weaviate_http_port, s.neo4j_uri) == (8082, "bolt://localhost:7688")
