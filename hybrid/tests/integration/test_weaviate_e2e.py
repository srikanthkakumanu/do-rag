"""Real Weaviate + Neo4j (testcontainers). Fake vectors and a regex extractor:
no OpenAI calls in CI."""

from __future__ import annotations

import asyncio
import time
import urllib.request
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from neo4j import Driver, GraphDatabase
from testcontainers.core.container import DockerContainer
from weaviate import WeaviateAsyncClient, WeaviateClient

from hybrid.config import Settings
from hybrid.domain import CardNetwork, FactKind
from hybrid.graph.planner import GraphPlan
from hybrid.graph.retriever import Neo4jGraphRetriever
from hybrid.graphdb import make_graph_async
from hybrid.ingestion.graph_store import Neo4jGraphStore
from hybrid.ingestion.pipeline import GraphSync, ingest
from hybrid.ingestion.store import WeaviateChunkStore
from hybrid.retrieval.retriever import RetrievalQuery, WeaviateRetriever
from hybrid.vectordb import connect_sync, make_async
from migrations.apply import apply_all
from tests.fakes import RegexExtractor, fake_embed, make_settings

pytestmark = pytest.mark.integration

WEAVIATE = "cr.weaviate.io/semitechnologies/weaviate:1.38.20"
NEO4J = "neo4j:5.26.32-community"
CORPUS = Path(__file__).parents[2] / "data" / "corpus"
VERSIONED = """---
doc_id: visa-x
title: Visa 12.6 Duplicate Processing
version: {version}
effective_date: {effective}
source_type: network_rule
card_network: visa
---
# Visa 12.6 Duplicate Processing

## Response window

The merchant must respond within {days} calendar days.
"""


def _wait_http(url: str, timeout_s: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise TimeoutError(url)


@dataclass
class Stack:
    settings: Settings
    client: WeaviateClient
    driver: Driver
    extractor: RegexExtractor

    def ingest(self, paths: list[Path]) -> object:
        store = WeaviateChunkStore(self.client, self.settings.collection_name, embed=fake_embed)
        graph = GraphSync(Neo4jGraphStore(self.driver, "neo4j"), self.extractor)
        return ingest(paths, store, graph)


@pytest.fixture(scope="session")
def stack() -> Iterator[Stack]:
    weaviate = (
        DockerContainer(WEAVIATE)
        .with_exposed_ports(8080, 50051)
        .with_env("AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED", "true")
        .with_env("PERSISTENCE_DATA_PATH", "/var/lib/weaviate")
        .with_env("DEFAULT_VECTORIZER_MODULE", "none")
        .with_env("CLUSTER_HOSTNAME", "node1")
    )
    neo4j = DockerContainer(NEO4J).with_exposed_ports(7474, 7687).with_env("NEO4J_AUTH", "none")
    with weaviate, neo4j:
        w_host = weaviate.get_container_host_ip()
        w_url = f"http://{w_host}:{weaviate.get_exposed_port(8080)}"
        n_host = neo4j.get_container_host_ip()
        _wait_http(f"{w_url}/v1/.well-known/ready")
        _wait_http(f"http://{n_host}:{neo4j.get_exposed_port(7474)}")
        settings = make_settings(
            weaviate_url=w_url,
            weaviate_grpc_port=int(weaviate.get_exposed_port(50051)),
            weaviate_vectorizer="none",
            max_vector_distance=None,
            neo4j_uri=f"bolt://{n_host}:{neo4j.get_exposed_port(7687)}",
        )
        driver = GraphDatabase.driver(settings.neo4j_uri, auth=None)
        for _ in range(60):  # Bolt can lag behind HTTP readiness
            try:
                driver.verify_connectivity()
                break
            except Exception:  # noqa: BLE001 - readiness probe
                time.sleep(1)
        with connect_sync(settings) as client:
            apply_all(client, driver, settings)
            s = Stack(settings, client, driver, RegexExtractor())
            report = s.ingest([CORPUS])
            assert report.ok, report.errors  # type: ignore[attr-defined]
            yield s
        driver.close()


@pytest.fixture
async def graph(stack: Stack) -> AsyncIterator[Neo4jGraphRetriever]:
    driver = make_graph_async(stack.settings)
    try:
        yield Neo4jGraphRetriever(driver, stack.settings)
    finally:
        await driver.close()


@pytest.fixture
async def wclient(stack: Stack) -> AsyncIterator[WeaviateAsyncClient]:
    client = make_async(stack.settings)
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


def test_migrations_idempotent_on_both_stores(stack: Stack) -> None:
    apply_all(stack.client, stack.driver, stack.settings)
    with stack.driver.session() as s:
        names = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name")}
    assert {"reason_code", "evidence_name", "deadline_key"} <= names


def test_reingest_is_noop_with_zero_extraction_calls(stack: Stack) -> None:
    calls = stack.extractor.calls
    report = stack.ingest([CORPUS])
    assert (report.created, report.updated, report.facts_written) == (0, 0, 0)  # type: ignore[attr-defined]
    assert stack.extractor.calls == calls


async def test_aggregate_deadline_query_finds_every_matching_code(
    stack: Stack, graph: Neo4jGraphRetriever
) -> None:
    facts = await graph.facts(GraphPlan(deadline_days=45), date(2026, 10, 1))
    assert {f.code for f in facts} == {"4853", "4837"}
    assert all(f.kind is FactKind.DEADLINE and "45" in f.quote for f in facts)
    assert {f.doc_id for f in facts} == {"mc-4853", "mc-4837"}


async def test_codes_query_and_network_filter(stack: Stack, graph: Neo4jGraphRetriever) -> None:
    facts = await graph.facts(GraphPlan(reason_codes=["C08"]), date(2026, 10, 1))
    assert facts and all(f.code == "C08" for f in facts)
    visa = await graph.facts(
        GraphPlan(networks=[CardNetwork.VISA], kinds=[FactKind.DEADLINE]), date(2026, 10, 1)
    )
    assert visa and all(f.network == "visa" for f in visa)


async def test_graph_respects_supersession(
    stack: Stack, graph: Neo4jGraphRetriever, tmp_path: Path
) -> None:
    v1 = tmp_path / "v1.md"
    v1.write_text(VERSIONED.format(version="1", effective="2025-01-01", days=11), encoding="utf-8")
    v2 = tmp_path / "v2.md"
    v2.write_text(VERSIONED.format(version="2", effective="2026-07-01", days=13), encoding="utf-8")
    # Ingestion is sync and owns its own event loop: run it off the test's loop.
    await asyncio.to_thread(stack.ingest, [v1])
    await asyncio.to_thread(stack.ingest, [v2])
    old = await graph.facts(GraphPlan(reason_codes=["12.6"]), date(2026, 1, 1))
    new = await graph.facts(GraphPlan(reason_codes=["12.6"]), date(2026, 10, 1))
    assert [f.quote for f in old] == ["The merchant must respond within 11 calendar days."]
    assert [f.quote for f in new] == ["The merchant must respond within 13 calendar days."]


async def test_vector_side_still_works(stack: Stack, wclient: WeaviateAsyncClient) -> None:
    hits = await WeaviateRetriever(wclient, stack.settings, embed=fake_embed).search(
        RetrievalQuery(text="4853", as_of=date(2026, 10, 1))
    )
    assert hits and hits[0].doc_id == "mc-4853"


def test_no_pan_in_either_store(stack: Stack) -> None:
    objs = stack.client.collections.use(stack.settings.collection_name).query.fetch_objects(
        limit=500
    )
    assert "4111" not in " ".join(str(o.properties["content"]) for o in objs.objects)
    with stack.driver.session() as s:
        quotes = " ".join(r["q"] or "" for r in s.run("MATCH ()-[r]->() RETURN r.quote AS q"))
    assert "4111" not in quotes
