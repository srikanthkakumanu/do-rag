from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

from basic.domain import NOT_SUPERSEDED, CardNetwork, Chunk, ChunkId
from basic.errors import IngestionError
from basic.ingestion.loaders import discover, load_document
from basic.ingestion.pipeline import ingest, superseded_dates
from basic.ingestion.store import StoredChunk

CORPUS = Path(__file__).parents[3] / "data" / "corpus"

MD = """---
doc_id: sop-x
title: SOP X
version: {version}
effective_date: {effective}
source_type: internal_sop
card_network: all
---
# SOP X

## Rule

{body}
"""


class MemoryStore:
    """In-memory `ChunkStore` for pipeline logic tests."""

    def __init__(self) -> None:
        self.rows: dict[ChunkId, tuple[Chunk, date]] = {}

    def existing(self, doc_id: str) -> dict[ChunkId, StoredChunk]:
        return {
            cid: StoredChunk(cid, c.version, c.effective_date, sup, c.content_hash)
            for cid, (c, sup) in self.rows.items()
            if c.doc_id == doc_id
        }

    def upsert(self, chunks: Sequence[Chunk], superseded_on: date) -> None:
        for c in chunks:
            self.rows[c.chunk_id] = (c, superseded_on)

    def set_superseded(self, ids: Sequence[ChunkId], superseded_on: date) -> None:
        for cid in ids:
            self.rows[cid] = (self.rows[cid][0], superseded_on)

    def delete(self, ids: Sequence[ChunkId]) -> None:
        for cid in ids:
            del self.rows[cid]


def _write(tmp: Path, name: str, version: str, effective: str, body: str) -> Path:
    path = tmp / name
    path.write_text(MD.format(version=version, effective=effective, body=body), encoding="utf-8")
    return path


def test_load_markdown_front_matter() -> None:
    doc = load_document(CORPUS / "visa-10-4-fraud-card-absent.md")
    assert doc.doc_id == "visa-10-4"
    assert doc.card_network is CardNetwork.VISA
    assert doc.effective_date == date(2026, 1, 1)


def test_load_html_with_sidecar_keeps_headings() -> None:
    doc = load_document(CORPUS / "playbook-friendly-fraud.html")
    assert doc.doc_id == "playbook-friendly-fraud"
    assert "## Signals" in doc.text
    assert "font:14px" not in doc.text  # <style> dropped


def test_load_missing_metadata_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("---\ntitle: no id\n---\n# Bad\n", encoding="utf-8")
    with pytest.raises(IngestionError, match="missing required metadata"):
        load_document(path)


def test_discover_skips_sidecars() -> None:
    names = {p.name for p in discover([CORPUS])}
    assert "playbook-friendly-fraud.meta" not in names
    assert "playbook-friendly-fraud.html" in names


def test_superseded_dates_chain_versions() -> None:
    out = superseded_dates({"1": date(2025, 1, 1), "2": date(2026, 7, 1)})
    assert out == {"1": date(2026, 7, 1), "2": NOT_SUPERSEDED}


def test_ingest_scrubs_pan_before_indexing() -> None:
    store = MemoryStore()
    report = ingest([CORPUS / "sop-evidence-packaging.md"], store)
    assert report.redactions >= 2
    contents = " ".join(c.content for c, _ in store.rows.values())
    assert "4111" not in contents
    assert "John Smith" not in contents


def test_ingest_identical_input_is_noop(tmp_path: Path) -> None:
    store = MemoryStore()
    path = _write(tmp_path, "x.md", "1", "2025-01-01", "Submit 5 days early.")
    first = ingest([path], store)
    second = ingest([path], store)
    assert first.created == 1
    assert (second.created, second.updated, second.skipped) == (0, 0, 1)


def test_ingest_new_version_supersedes_old(tmp_path: Path) -> None:
    store = MemoryStore()
    ingest([_write(tmp_path, "v1.md", "1", "2025-01-01", "Submit 5 days early.")], store)
    report = ingest([_write(tmp_path, "v2.md", "2", "2026-07-01", "Submit 7 days early.")], store)
    sup = {c.version: s for c, s in store.rows.values()}
    assert sup == {"1": date(2026, 7, 1), "2": NOT_SUPERSEDED}
    assert report.updated == 1  # the v1 chunk got its superseded_on date


def test_ingest_shrinking_document_deletes_stale_chunks(tmp_path: Path) -> None:
    store = MemoryStore()
    long_body = "\n\n## Other\n\n".join(["Text."] * 3)
    ingest([_write(tmp_path, "x.md", "1", "2025-01-01", long_body)], store)
    assert len(store.rows) == 3
    report = ingest([_write(tmp_path, "x.md", "1", "2025-01-01", "Text.")], store)
    assert report.deleted == 2
    assert len(store.rows) == 1


def test_ingest_bad_file_counted_as_failure(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("no front matter", encoding="utf-8")
    report = ingest([bad], MemoryStore())
    assert report.failed == 1
    assert not report.ok


def test_ingest_dry_run_writes_nothing(tmp_path: Path) -> None:
    store = MemoryStore()
    report = ingest([_write(tmp_path, "x.md", "1", "2025-01-01", "T.")], store, dry_run=True)
    assert report.created == 1
    assert store.rows == {}
