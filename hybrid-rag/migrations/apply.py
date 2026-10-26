"""Apply all `NNNN_*.py` migrations in order. Each is idempotent and may define
`up(weaviate_client, settings)` and/or `up_graph(neo4j_driver, settings)`."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from neo4j import Driver
from weaviate import WeaviateClient

from hybrid.config import Settings, get_settings
from hybrid.graphdb import connect_graph_sync
from hybrid.vectordb import connect_sync


def migration_names() -> list[str]:
    here = Path(__file__).parent
    return sorted(p.stem for p in here.glob("[0-9][0-9][0-9][0-9]_*.py"))


def apply_all(
    client: WeaviateClient | None, driver: Driver | None, settings: Settings
) -> list[str]:
    """Run every migration against the stores provided; returns names in order."""
    names = migration_names()
    for name in names:
        module = importlib.import_module(f"migrations.{name}")
        if client is not None and hasattr(module, "up"):
            module.up(client, settings)
        if driver is not None and hasattr(module, "up_graph"):
            module.up_graph(driver, settings)
    return names


def main() -> int:
    settings = get_settings()
    with connect_sync(settings) as client, connect_graph_sync(settings) as driver:
        applied = apply_all(client, driver, settings)
    print(f"migrations applied: {', '.join(applied)}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
