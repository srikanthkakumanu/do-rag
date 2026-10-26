"""Neo4j uniqueness constraints and fact-edge indexes (idempotent)."""

from __future__ import annotations

from typing import Final, LiteralString

from neo4j import Driver

from hybrid.config import Settings

STATEMENTS: Final[tuple[LiteralString, ...]] = (
    "CREATE CONSTRAINT network_name IF NOT EXISTS FOR (n:Network) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT reason_code IF NOT EXISTS FOR (n:ReasonCode) REQUIRE n.code IS UNIQUE",
    "CREATE CONSTRAINT deadline_key IF NOT EXISTS FOR (n:Deadline) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT evidence_name IF NOT EXISTS FOR (n:Evidence) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (n:Category) REQUIRE n.name IS UNIQUE",
    "CREATE INDEX has_deadline_chunk IF NOT EXISTS FOR ()-[r:HAS_DEADLINE]-() ON (r.chunk_id)",
    "CREATE INDEX remedied_by_chunk IF NOT EXISTS FOR ()-[r:REMEDIED_BY]-() ON (r.chunk_id)",
    "CREATE INDEX not_sufficient_chunk IF NOT EXISTS FOR ()-[r:NOT_SUFFICIENT]-() ON (r.chunk_id)",
    "CREATE INDEX in_category_chunk IF NOT EXISTS FOR ()-[r:IN_CATEGORY]-() ON (r.chunk_id)",
)


def up_graph(driver: Driver, settings: Settings) -> None:
    with driver.session(database=settings.neo4j_database) as session:
        for statement in STATEMENTS:
            session.run(statement).consume()
