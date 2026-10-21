"""Neo4j driver factories (sync for ingestion/migrations, async for the API)."""

from __future__ import annotations

from neo4j import AsyncDriver, AsyncGraphDatabase, Driver, GraphDatabase

from hybrid.config import Settings


def _auth(settings: Settings) -> tuple[str, str] | None:
    password = settings.neo4j_password.get_secret_value()
    return (settings.neo4j_user, password) if password else None


def connect_graph_sync(settings: Settings) -> Driver:
    """Sync driver; use as a context manager so it always closes."""
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=_auth(settings),
        connection_timeout=settings.neo4j_timeout_s,
    )


def make_graph_async(settings: Settings) -> AsyncDriver:
    """Async driver for the API; the FastAPI lifespan closes it."""
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=_auth(settings),
        connection_timeout=settings.neo4j_timeout_s,
    )
