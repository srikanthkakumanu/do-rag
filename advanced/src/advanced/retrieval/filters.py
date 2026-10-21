"""Build Weaviate filters from a `RetrievalQuery`."""

from __future__ import annotations

from datetime import date

from weaviate.classes.query import Filter
from weaviate.collections.classes.filters import _Filters

from advanced.domain import CardNetwork
from advanced.vectordb import to_datetime


def build_filters(card_network: CardNetwork | None, as_of: date) -> _Filters:
    """Current-as-of filter, plus network (+ cross-network 'all') when requested."""
    when = to_datetime(as_of)
    current = Filter.by_property("effective_date").less_or_equal(when) & Filter.by_property(
        "superseded_on"
    ).greater_than(when)
    if card_network is None or card_network is CardNetwork.ALL:
        return current
    network = Filter.by_property("card_network").contains_any(
        [card_network.value, CardNetwork.ALL.value]
    )
    return current & network
