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
    assert sum(1 for i in items if i.history) >= 5  # multi-turn coverage
    assert any(len(i.expected_doc_ids) > 1 for i in items)  # cross-network comparisons


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
    assert "recall_at_5" in gate(m)


def test_fast_model_falls_back_to_chat_model() -> None:
    assert make_settings().fast_model == "test-model"
    assert make_settings(openai_fast_model="nano").fast_model == "nano"
