from __future__ import annotations

from advanced.domain import CardNetwork, Turn
from advanced.errors import GenerationError
from advanced.query.planner import (
    LLMQueryPlan,
    LLMQueryPlanner,
    guard,
    load_plan_prompt,
    mentioned_networks,
    regex_plan,
)
from tests.fakes import FakeLLM, make_settings


def _raw(**kw: object) -> LLMQueryPlan:
    base: dict[str, object] = {
        "standalone_question": "What remedies apply to Mastercard 4853?",
        "sub_queries": ["Mastercard 4853 remedies"],
        "card_network": CardNetwork.MASTERCARD,
        "reason_codes": ["4853"],
        "in_scope": True,
    }
    base.update(kw)
    return LLMQueryPlan(**base)


HISTORY = [
    Turn(role="user", content="What is the response window for Mastercard 4853?"),
    Turn(role="assistant", content="45 calendar days."),
]


def test_mentioned_networks_from_names_and_codes() -> None:
    assert mentioned_networks("Visa vs Amex") == {CardNetwork.VISA, CardNetwork.AMEX}
    assert mentioned_networks("window for 4853?") == {CardNetwork.MASTERCARD}
    assert mentioned_networks("what about UA02") == {CardNetwork.DISCOVER}


def test_guard_keeps_supported_codes_and_network() -> None:
    p = guard(_raw(), "And what remedies apply?", HISTORY, None, 3)
    assert p.card_network is CardNetwork.MASTERCARD
    assert p.reason_codes == ["4853"]
    assert p.sub_queries[0] == p.standalone_question


def test_guard_drops_hallucinated_codes_and_unsupported_network() -> None:
    raw = _raw(
        standalone_question="What evidence is needed for disputes?",
        reason_codes=["4853", "10.4"],
        card_network=CardNetwork.VISA,
    )
    p = guard(raw, "What evidence is needed for disputes?", [], None, 3)
    assert p.reason_codes == []
    assert p.card_network is None


def test_guard_no_network_filter_for_comparisons() -> None:
    q = "Compare Visa 10.4 and Mastercard 4837 windows"
    p = guard(_raw(standalone_question=q, card_network=CardNetwork.VISA), q, [], None, 3)
    assert p.card_network is None


def test_guard_request_network_wins_and_queries_capped_deduped() -> None:
    raw = _raw(sub_queries=["a", "a", "b", "c", "d"])
    p = guard(raw, "q", HISTORY, CardNetwork.VISA, 3)
    assert p.card_network is CardNetwork.VISA
    assert len(p.sub_queries) == 4  # standalone + 3 sub-queries
    assert len(set(p.sub_queries)) == 4


def test_regex_plan_fallback() -> None:
    p = regex_plan("Visa 10.4 window?", [], None)
    assert p.degraded
    assert p.card_network is CardNetwork.VISA
    assert p.reason_codes == ["10.4"]
    assert p.sub_queries == ["Visa 10.4 window?"]


async def test_planner_uses_llm_and_wraps_history_as_data() -> None:
    llm = FakeLLM(plan=[_raw()])
    planner = LLMQueryPlanner(llm, make_settings())
    p = await planner.plan("And what remedies apply?", HISTORY, None)
    assert p.standalone_question.startswith("What remedies")
    purpose, user_input = llm.calls[0]
    assert purpose == "plan"
    assert "<history>" in user_input and "<question>" in user_input


async def test_planner_degrades_on_llm_failure() -> None:
    planner = LLMQueryPlanner(FakeLLM(plan=[GenerationError("down")]), make_settings())
    p = await planner.plan("Amex C08 window?", [], None)
    assert p.degraded
    assert p.card_network is CardNetwork.AMEX


async def test_planner_truncates_history_to_max_turns() -> None:
    llm = FakeLLM(plan=[_raw()])
    long_history = [Turn(role="user", content=f"turn {i}") for i in range(10)]
    await LLMQueryPlanner(llm, make_settings(history_max_turns=2)).plan("q", long_history, None)
    assert "turn 9" in llm.calls[0][1] and "turn 7" not in llm.calls[0][1]


def test_plan_prompt_renders_max_queries() -> None:
    assert "1 to 3" in load_plan_prompt("v1", 3)
