from __future__ import annotations

from datetime import date

from advanced.domain import CardNetwork, DocId, SourceDocument, SourceType
from advanced.ingestion.chunker import (
    ChunkSizes,
    chunk,
    chunk_uuid,
    count_tokens,
    section_uuid,
    split_sections,
)

SMALL = ChunkSizes(parent_max=1200, child_max=60, child_overlap=15)


def _doc(text: str, network: CardNetwork = CardNetwork.VISA) -> SourceDocument:
    return SourceDocument(
        doc_id=DocId("visa-10-4"),
        doc_title="Visa 10.4",
        version="2026.1",
        effective_date=date(2026, 1, 1),
        source_type=SourceType.NETWORK_RULE,
        card_network=network,
        jurisdiction="global",
        text=text,
    )


def test_split_sections_builds_breadcrumbs() -> None:
    text = "# Visa 10.4\n\nIntro.\n\n## Remedies\n\nA.\n\n### CE 3.0\n\nB."
    assert [s.path for s in split_sections("Visa 10.4", text)] == [
        "Visa 10.4",
        "Visa 10.4 > Remedies",
        "Visa 10.4 > Remedies > CE 3.0",
    ]


def test_chunk_one_parent_per_section_and_children_link_to_it() -> None:
    parents, children = chunk(_doc("## Window\n\nRespond to 10.4 in 30 days.\n\n## Other\n\nX."))
    assert [p.section_path for p in parents] == ["Visa 10.4 > Window", "Visa 10.4 > Other"]
    assert {c.parent_id for c in children} == {p.section_id for p in parents}
    assert children[0].reason_codes == ("10.4",)
    assert parents[0].content.startswith("Visa 10.4 > Window\n\n")


def test_children_are_small_with_overlap_parent_keeps_whole_section() -> None:
    body = " ".join(f"Rule {i} requires evidence item {i}." for i in range(40))
    parents, children = chunk(_doc(f"## Long\n\n{body}"), SMALL)
    assert len(parents) == 1
    assert body in parents[0].content
    assert len(children) > 3
    for c in children:
        assert count_tokens(c.content.split("\n\n", 1)[1]) <= SMALL.child_max + SMALL.child_overlap
    first_tail = children[0].content.splitlines()[-1]
    assert first_tail in children[1].content  # overlap carried forward


def test_list_items_split_across_children_but_parent_intact() -> None:
    items = "\n".join(f"- Evidence item number {i} with some detail" for i in range(30))
    parents, children = chunk(_doc(f"## Evidence\n\n{items}"), SMALL)
    assert items in parents[0].content
    assert len(children) > 1


def test_ids_deterministic_and_namespaced() -> None:
    text = "## A\n\nSome text."
    (p1, c1), (p2, c2) = chunk(_doc(text)), chunk(_doc(text))
    assert p1[0].section_id == p2[0].section_id == section_uuid("visa-10-4", "2026.1", 0)
    assert c1[0].chunk_id == c2[0].chunk_id == chunk_uuid("visa-10-4", "2026.1", 0)
    assert str(p1[0].section_id) != str(c1[0].chunk_id)


def test_child_hash_changes_when_parent_changes() -> None:
    _, a = chunk(_doc("## A\n\nSame text."))
    _, b = chunk(_doc("## Z\n\nNew first section.\n\n## A\n\nSame text."))
    same_text = [c for c in b if c.section_path == "Visa 10.4 > A"][0]
    assert same_text.content == a[0].content
    assert same_text.content_hash != a[0].content_hash
