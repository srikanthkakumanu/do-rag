from __future__ import annotations

from datetime import date

import pytest
from weaviate.collections.classes.filters import _Filters

from advanced.domain import CardNetwork
from advanced.retrieval.filters import build_filters


def _flatten(f: _Filters) -> str:
    """Render a filter tree (And/Or nodes hold `.filters`) as text."""
    children = getattr(f, "filters", None)
    if isinstance(children, list):
        return " ".join(_flatten(c) for c in children)
    return repr(f)


def test_filters_always_apply_current_as_of() -> None:
    text = _flatten(build_filters(None, date(2026, 3, 1)))
    assert "effective_date" in text
    assert "superseded_on" in text
    assert "card_network" not in text


@pytest.mark.parametrize("network", [CardNetwork.VISA, CardNetwork.MASTERCARD])
def test_filters_network_includes_all(network: CardNetwork) -> None:
    text = _flatten(build_filters(network, date(2026, 3, 1)))
    assert "card_network" in text
    assert network.value in text
    assert "'all'" in text


def test_filters_all_network_means_no_network_filter() -> None:
    assert "card_network" not in _flatten(build_filters(CardNetwork.ALL, date(2026, 3, 1)))
