"""`hybrid ingest <paths...> [--dry-run]` entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from hybrid.config import get_settings
from hybrid.graphdb import connect_graph_sync
from hybrid.ingestion.extract import LLMFactExtractor
from hybrid.ingestion.graph_store import Neo4jGraphStore
from hybrid.ingestion.pipeline import GraphSync, ingest
from hybrid.ingestion.store import WeaviateChunkStore
from hybrid.llm import OpenAIStructuredLLM, make_openai_client
from hybrid.observability import configure_logging
from hybrid.vectordb import connect_sync


def main(argv: Sequence[str] | None = None) -> int:
    """Run ingestion; exits non-zero when any file fails."""
    parser = argparse.ArgumentParser(prog="hybrid")
    sub = parser.add_subparsers(dest="command", required=True)
    p_ingest = sub.add_parser("ingest", help="scrub, chunk, and upsert policy documents")
    p_ingest.add_argument("paths", nargs="+", type=Path)
    p_ingest.add_argument("--dry-run", action="store_true")
    p_ingest.add_argument(
        "--reextract",
        action="store_true",
        help="re-run graph extraction for unchanged chunks (after an extraction-prompt change)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    openai_client = make_openai_client(settings)
    with (
        asyncio.Runner() as runner,
        connect_sync(settings) as client,
        connect_graph_sync(settings) as driver,
    ):
        try:
            store = WeaviateChunkStore(client, settings.collection_name)
            graph = GraphSync(
                store=Neo4jGraphStore(driver, settings.neo4j_database),
                extractor=LLMFactExtractor(OpenAIStructuredLLM(openai_client, settings), settings),
                concurrency=settings.extract_concurrency,
                runner=runner,
            )
            report = ingest(
                args.paths, store, graph, dry_run=args.dry_run, reextract=args.reextract
            )
        finally:
            runner.run(openai_client.close())
    print(  # noqa: T201 - CLI summary for operators (counts only, no content)
        f"files={report.files} created={report.created} updated={report.updated} "
        f"skipped={report.skipped} deleted={report.deleted} failed={report.failed} "
        f"redactions={report.redactions} facts={report.facts_written} "
        f"facts_rejected={report.facts_rejected} deferred={report.deferred}"
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
