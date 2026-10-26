"""Neo4j write side for ingestion. Fact edges are keyed by `chunk_id` and carry the same
provenance and supersession dates as the Weaviate chunk."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Final, LiteralString, Protocol

from neo4j import Driver, ManagedTransaction

from hybrid.domain import CardNetwork, Chunk, ChunkId, FactKind
from hybrid.ingestion.extract import Fact

_FACT_TYPES: Final = "HAS_DEADLINE|REMEDIED_BY|NOT_SUFFICIENT|IN_CATEGORY"

DELETE_CHUNK_FACTS: Final[LiteralString] = (
    f"MATCH (:ReasonCode)-[r:{_FACT_TYPES}]->() WHERE r.chunk_id IN $ids DELETE r"
)
SET_SUPERSEDED: Final[LiteralString] = (
    f"MATCH (:ReasonCode)-[r:{_FACT_TYPES}]->() WHERE r.chunk_id IN $ids "
    "SET r.superseded_on = $superseded_on"
)
MERGE_CODES: Final[LiteralString] = """
UNWIND $codes AS code
MERGE (rc:ReasonCode {code: code})
WITH rc
CALL (rc) {
  WITH rc WHERE $network IS NOT NULL
  MERGE (n:Network {name: $network})
  MERGE (n)-[:DEFINES]->(rc)
  SET rc.network = $network
}
"""
_PROV: Final = (
    "SET r.chunk_id = $p.chunk_id, r.doc_id = $p.doc_id, r.version = $p.version, "
    "r.section_path = $p.section_path, r.effective_date = $p.effective_date, "
    "r.superseded_on = $p.superseded_on, r.quote = row.quote"
)
CREATE_FACTS: Final[dict[FactKind, LiteralString]] = {
    FactKind.DEADLINE: (
        "UNWIND $rows AS row MATCH (rc:ReasonCode {code: row.code}) "
        "MERGE (t:Deadline {key: row.target}) "
        "SET t.days = row.days, t.party = row.party, t.action = row.action "
        "CREATE (rc)-[r:HAS_DEADLINE]->(t) " + _PROV
    ),
    FactKind.REMEDY: (
        "UNWIND $rows AS row MATCH (rc:ReasonCode {code: row.code}) "
        "MERGE (t:Evidence {name: row.target}) CREATE (rc)-[r:REMEDIED_BY]->(t) " + _PROV
    ),
    FactKind.INSUFFICIENT: (
        "UNWIND $rows AS row MATCH (rc:ReasonCode {code: row.code}) "
        "MERGE (t:Evidence {name: row.target}) CREATE (rc)-[r:NOT_SUFFICIENT]->(t) " + _PROV
    ),
    FactKind.CATEGORY: (
        "UNWIND $rows AS row MATCH (rc:ReasonCode {code: row.code}) "
        "MERGE (t:Category {name: row.target}) CREATE (rc)-[r:IN_CATEGORY]->(t) " + _PROV
    ),
}


class GraphStore(Protocol):
    def replace_facts(self, chunk: Chunk, facts: Sequence[Fact], superseded_on: date) -> None: ...
    def set_superseded(self, ids: Sequence[ChunkId], superseded_on: date) -> None: ...
    def delete_facts(self, ids: Sequence[ChunkId]) -> None: ...


def _replace(tx: ManagedTransaction, chunk: Chunk, facts: Sequence[Fact], sup: date) -> None:
    tx.run(DELETE_CHUNK_FACTS, ids=[chunk.chunk_id])
    if chunk.reason_codes:
        network = None if chunk.card_network is CardNetwork.ALL else chunk.card_network.value
        tx.run(MERGE_CODES, codes=list(chunk.reason_codes), network=network)
    prov = {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "version": chunk.version,
        "section_path": chunk.section_path,
        "effective_date": chunk.effective_date,
        "superseded_on": sup,
    }
    for kind, query in CREATE_FACTS.items():
        rows = [
            {
                "code": f.code,
                "target": f.target,
                "quote": f.quote,
                "days": f.days,
                "party": f.party.value if f.party else None,
                "action": f.action,
            }
            for f in facts
            if f.kind is kind
        ]
        if rows:
            tx.run(query, rows=rows, p=prov)


class Neo4jGraphStore:
    """`GraphStore` over a sync Neo4j driver; one transaction per chunk."""

    def __init__(self, driver: Driver, database: str) -> None:
        self._driver = driver
        self._database = database

    def replace_facts(self, chunk: Chunk, facts: Sequence[Fact], superseded_on: date) -> None:
        with self._driver.session(database=self._database) as session:
            session.execute_write(_replace, chunk, facts, superseded_on)

    def set_superseded(self, ids: Sequence[ChunkId], superseded_on: date) -> None:
        with self._driver.session(database=self._database) as session:
            session.execute_write(
                lambda tx: tx.run(
                    SET_SUPERSEDED, ids=list(ids), superseded_on=superseded_on
                ).consume()
            )

    def delete_facts(self, ids: Sequence[ChunkId]) -> None:
        with self._driver.session(database=self._database) as session:
            session.execute_write(lambda tx: tx.run(DELETE_CHUNK_FACTS, ids=list(ids)).consume())
