"""Ingestion orchestration: load -> scrub -> chunk -> idempotent upsert."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import structlog

from advanced.domain import NOT_SUPERSEDED, ChunkId, SectionId
from advanced.errors import AdvancedRagError, IngestionError
from advanced.ingestion.chunker import DEFAULT_SIZES, ChunkSizes, chunk
from advanced.ingestion.loaders import discover, load_document
from advanced.ingestion.scrub import scrub
from advanced.ingestion.store import ChunkStore

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class IngestReport:
    files: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    sections_written: int = 0
    sections_deleted: int = 0
    failed: int = 0
    redactions: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


def superseded_dates(versions: dict[str, date]) -> dict[str, date]:
    """Map each version to the effective date of the next version (or 'never')."""
    ordered = sorted(versions.items(), key=lambda kv: kv[1])
    out: dict[str, date] = {}
    for i, (version, _) in enumerate(ordered):
        out[version] = ordered[i + 1][1] if i + 1 < len(ordered) else NOT_SUPERSEDED
    return out


def ingest_file(
    path: Path, store: ChunkStore, report: IngestReport, *, sizes: ChunkSizes, dry_run: bool
) -> None:
    doc = load_document(path)
    scrubbed = scrub(doc.text)  # before chunking, hashing, or any network call
    report.redactions += scrubbed.redaction_count
    sections, chunks = chunk(replace(doc, text=scrubbed.clean_text), sizes)
    if not chunks:
        raise IngestionError(f"{path.name}: no content after parsing")

    existing = store.existing(doc.doc_id)
    versions = {s.version: s.effective_date for s in existing.values()}
    versions[doc.version] = doc.effective_date
    superseded = superseded_dates(versions)
    mine = superseded[doc.version]

    new_ids = {c.chunk_id for c in chunks}
    to_write = []
    for c in chunks:
        prev = existing.get(c.chunk_id)
        if prev is None:
            report.created += 1
            to_write.append(c)
        elif prev.content_hash != c.content_hash or prev.superseded_on != mine:
            report.updated += 1
            to_write.append(c)
        else:
            report.skipped += 1

    stale: list[ChunkId] = [
        cid for cid, s in existing.items() if s.version == doc.version and cid not in new_ids
    ]
    resupersede: dict[date, list[ChunkId]] = {}
    for cid, s in existing.items():
        target = superseded[s.version]
        if s.version != doc.version and s.superseded_on != target:
            resupersede.setdefault(target, []).append(cid)
            report.updated += 1
    report.deleted += len(stale)

    stored_sections = store.existing_sections(doc.doc_id, doc.version)
    new_sections = [s for s in sections if stored_sections.get(s.section_id) != s.content_hash]
    keep = {s.section_id for s in sections}
    stale_sections: list[SectionId] = [sid for sid in stored_sections if sid not in keep]
    report.sections_written += len(new_sections)
    report.sections_deleted += len(stale_sections)

    if dry_run:
        return
    if new_sections:  # parents first: children reference them
        store.upsert_sections(new_sections)
    if to_write:
        store.upsert(to_write, mine)
    for target, ids in resupersede.items():
        store.set_superseded(ids, target)
    if stale:
        store.delete(stale)
    if stale_sections:
        store.delete_sections(stale_sections)


def ingest(
    paths: Sequence[Path],
    store: ChunkStore,
    *,
    sizes: ChunkSizes = DEFAULT_SIZES,
    dry_run: bool = False,
) -> IngestReport:
    """Ingest files/directories. Re-running on unchanged input is a no-op."""
    report = IngestReport()
    for path in discover(list(paths)):
        report.files += 1
        try:
            ingest_file(path, store, report, sizes=sizes, dry_run=dry_run)
        except AdvancedRagError as e:
            report.failed += 1
            report.errors.append(str(e))
            log.error("ingest_file_failed", file=path.name, error=str(e))
    log.info(
        "ingest_complete",
        files=report.files,
        created=report.created,
        updated=report.updated,
        skipped=report.skipped,
        deleted=report.deleted,
        sections_written=report.sections_written,
        failed=report.failed,
        redactions=report.redactions,
        dry_run=dry_run,
    )
    return report
