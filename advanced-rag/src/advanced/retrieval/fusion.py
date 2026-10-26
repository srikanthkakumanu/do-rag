"""Reciprocal Rank Fusion of per-sub-query child hits, aggregated to parent sections."""

from __future__ import annotations

from collections.abc import Sequence

from advanced.domain import RetrievedChunk, SectionId


def rrf_parents(
    result_lists: Sequence[Sequence[RetrievedChunk]], k: int
) -> list[tuple[SectionId, float]]:
    """Score each parent by sum(1 / (k + rank)) of its best child in each list (rank from 1)."""
    scores: dict[SectionId, float] = {}
    for hits in result_lists:
        seen: set[SectionId] = set()
        for rank, hit in enumerate(hits, start=1):
            if hit.parent_id in seen:
                continue  # one vote per parent per list: its best-ranked child
            seen.add(hit.parent_id)
            scores[hit.parent_id] = scores.get(hit.parent_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
