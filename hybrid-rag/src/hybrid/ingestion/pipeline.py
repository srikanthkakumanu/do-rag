"""Ingestion orchestration: load -> scrub -> chunk -> extract facts -> graph, then Weaviate.
Graph first: if anything fails, the chunk is not in Weaviate and the next run retries both."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import structlog

from hybrid.domain import NOT_SUPERSEDED, ChunkId
from hybrid.errors import HybridRagError, IngestionError
from hybrid.ingestion.chunker import chunk
from hybrid.ingestion.extract import FactExtractor, extract_all
from hybrid.ingestion.graph_store import GraphStore
from hybrid.ingestion.loaders import discover, load_document
from hybrid.ingestion.scrub import scrub
from hybrid.ingestion.store import ChunkStore

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class IngestReport:
    files: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    failed: int = 0
    redactions: int = 0
    facts_written: int = 0
    facts_rejected: int = 0
    deferred: int = 0  # chunks held back because extraction failed (run exits non-zero)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.deferred == 0


@dataclass(frozen=True, slots=True)
class GraphSync:
    """Everything needed to keep the knowledge graph in step with Weaviate."""

    store: GraphStore
    extractor: FactExtractor
    concurrency: int = 4
    runner: asyncio.Runner | None = None  # one event loop for the whole run (async LLM client)


def superseded_dates(versions: dict[str, date]) -> dict[str, date]:
    """Map each version to the effective date of the next version (or 'never')."""
    ordered = sorted(versions.items(), key=lambda kv: kv[1])
    out: dict[str, date] = {}
    for i, (version, _) in enumerate(ordered):
        out[version] = ordered[i + 1][1] if i + 1 < len(ordered) else NOT_SUPERSEDED
    return out


def ingest_file(
    path: Path,
    store: ChunkStore,
    graph: GraphSync,
    report: IngestReport,
    *,
    dry_run: bool,
    reextract: bool = False,
) -> None:
    doc = load_document(path)
    scrubbed = scrub(doc.text)  # before chunking, hashing, or any network call
    report.redactions += scrubbed.redaction_count
    chunks = chunk(replace(doc, text=scrubbed.clean_text))
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

    if dry_run:
        return
    # --reextract: rebuild graph facts for unchanged chunks too (after an extraction-prompt change).
    write_ids = {c.chunk_id for c in to_write}
    refresh = [c for c in chunks if reextract and c.chunk_id not in write_ids and c.reason_codes]
    targets = [c for c in to_write if c.reason_codes] + refresh
    job = extract_all(graph.extractor, targets, graph.concurrency)
    extractions = graph.runner.run(job) if graph.runner else asyncio.run(job)
    ready = []
    for c in to_write:
        ex = extractions.get(c.chunk_id)
        if ex is not None and ex.failed:
            report.deferred += 1  # retried next run: not written to either store
            continue
        facts = ex.facts if ex else ()
        graph.store.replace_facts(c, facts, mine)  # graph first, then Weaviate
        report.facts_written += len(facts)
        report.facts_rejected += ex.rejected if ex else 0
        ready.append(c)
    for c in refresh:  # graph only: the Weaviate chunk is unchanged
        ex = extractions[c.chunk_id]
        if ex.failed:
            report.deferred += 1
            continue
        graph.store.replace_facts(c, ex.facts, mine)
        report.facts_written += len(ex.facts)
        report.facts_rejected += ex.rejected
    if ready:
        store.upsert(ready, mine)
    for target, ids in resupersede.items():
        graph.store.set_superseded(ids, target)
        store.set_superseded(ids, target)
    if stale:
        graph.store.delete_facts(stale)
        store.delete(stale)


def ingest(
    paths: Sequence[Path],
    store: ChunkStore,
    graph: GraphSync,
    *,
    dry_run: bool = False,
    reextract: bool = False,
) -> IngestReport:
    """Ingest files/directories. Re-running on unchanged input is a no-op."""
    report = IngestReport()
    for path in discover(list(paths)):
        report.files += 1
        try:
            ingest_file(path, store, graph, report, dry_run=dry_run, reextract=reextract)
        except HybridRagError as e:
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
        failed=report.failed,
        redactions=report.redactions,
        facts_written=report.facts_written,
        facts_rejected=report.facts_rejected,
        deferred=report.deferred,
        dry_run=dry_run,
    )
    return report
