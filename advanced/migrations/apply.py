"""Apply all `NNNN_*.py` migrations in order. Each migration is idempotent."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Protocol

from weaviate import WeaviateClient

from advanced.config import Settings, get_settings
from advanced.vectordb import connect_sync


class Migration(Protocol):
    def up(self, client: WeaviateClient, settings: Settings) -> None: ...


def migration_names() -> list[str]:
    here = Path(__file__).parent
    return sorted(p.stem for p in here.glob("[0-9][0-9][0-9][0-9]_*.py"))


def apply_all(client: WeaviateClient, settings: Settings) -> list[str]:
    """Run every migration; returns the names applied (in order)."""
    names = migration_names()
    for name in names:
        module: Migration = importlib.import_module(f"migrations.{name}")
        module.up(client, settings)
    return names


def main() -> int:
    settings = get_settings()
    with connect_sync(settings) as client:
        applied = apply_all(client, settings)
    print(f"migrations applied: {', '.join(applied)}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
