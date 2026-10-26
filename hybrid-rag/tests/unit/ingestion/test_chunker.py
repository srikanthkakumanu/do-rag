from __future__ import annotations

from datetime import date

from hybrid.domain import CardNetwork, DocId, SourceDocument, SourceType
from hybrid.ingestion.chunker import (
    OVERLAP_TOKENS,
    TARGET_MAX_TOKENS,
    chunk,
    chunk_uuid,
    count_tokens,
    split_sections,
)


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
    text = "# Visa 10.4\n\nIntro.\n\n## Remedies\n\nA.\n\n### CE 3.0\n\nB.\n\n## Window\n\nC."
    paths = [s.path for s in split_sections("Visa 10.4", text)]
    assert paths == [
        "Visa 10.4",
        "Visa 10.4 > Remedies",
        "Visa 10.4 > Remedies > CE 3.0",
        "Visa 10.4 > Window",
    ]


def test_chunk_prefixes_breadcrumb_and_extracts_codes() -> None:
    chunks = chunk(_doc("## Response window\n\nRespond to 10.4 within 30 days."))
    assert len(chunks) == 1
    assert chunks[0].content.startswith("Visa 10.4 > Response window\n\n")
    assert chunks[0].reason_codes == ("10.4",)


def test_chunk_ids_and_hashes_deterministic() -> None:
    text = "## A\n\nSome text.\n\n## B\n\nMore text."
    first, second = chunk(_doc(text)), chunk(_doc(text))
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [c.content_hash for c in first] == [c.content_hash for c in second]
    assert first[0].chunk_id == chunk_uuid("visa-10-4", "2026.1", 0)


def test_chunk_long_section_splits_with_sentence_overlap_under_max() -> None:
    paragraphs = "\n\n".join(
        " ".join(f"Rule {i}.{j} requires evidence item {j}." for j in range(20)) for i in range(8)
    )
    chunks = chunk(_doc(f"## Long\n\n{paragraphs}"))
    assert len(chunks) > 1
    for c in chunks:
        assert count_tokens(c.content.split("\n\n", 1)[1]) <= TARGET_MAX_TOKENS + OVERLAP_TOKENS
    # Overlap: the final sentence of chunk N reappears at the start of chunk N+1.
    last_sentence = chunks[0].content.rsplit(". ", 1)[1]
    assert last_sentence in chunks[1].content.split("\n\n", 2)[1]


def test_chunk_table_and_list_never_split() -> None:
    table = "\n".join(f"| row {i} | " + "cell " * 30 + "|" for i in range(40))
    chunks = chunk(_doc(f"## Table\n\n{table}"))
    assert len(chunks) == 1
    assert chunks[0].content.endswith(table)


def test_chunk_all_network_doc_extracts_every_network() -> None:
    chunks = chunk(_doc("## Codes\n\nSee 10.4, 4853, C08 and UA02.", CardNetwork.ALL))
    assert chunks[0].reason_codes == ("10.4", "4853", "C08", "UA02")
