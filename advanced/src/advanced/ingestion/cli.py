"""`advanced ingest <paths...> [--dry-run]` entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from advanced.config import get_settings
from advanced.ingestion.chunker import ChunkSizes
from advanced.ingestion.pipeline import ingest
from advanced.ingestion.store import WeaviateChunkStore
from advanced.observability import configure_logging
from advanced.vectordb import connect_sync


def main(argv: Sequence[str] | None = None) -> int:
    """Run ingestion; exits non-zero when any file fails."""
    parser = argparse.ArgumentParser(prog="advanced")
    sub = parser.add_subparsers(dest="command", required=True)
    p_ingest = sub.add_parser("ingest", help="scrub, chunk, and upsert policy documents")
    p_ingest.add_argument("paths", nargs="+", type=Path)
    p_ingest.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    with connect_sync(settings) as client:
        store = WeaviateChunkStore(client, settings.collection_name, settings.section_collection)
        sizes = ChunkSizes(
            settings.parent_max_tokens, settings.child_max_tokens, settings.child_overlap_tokens
        )
        report = ingest(args.paths, store, sizes=sizes, dry_run=args.dry_run)
    print(  # noqa: T201 - CLI summary for operators (counts only, no content)
        f"files={report.files} created={report.created} updated={report.updated} "
        f"skipped={report.skipped} deleted={report.deleted} sections={report.sections_written} "
        f"failed={report.failed} "
        f"redactions={report.redactions}"
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
