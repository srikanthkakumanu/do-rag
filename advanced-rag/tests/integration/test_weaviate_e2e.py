"""Real Weaviate (testcontainers), self-provided vectors: no OpenAI calls in CI."""

from __future__ import annotations

import time
import urllib.request
from collections.abc import AsyncIterator, Iterator
from datetime import date
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer
from weaviate import WeaviateAsyncClient, WeaviateClient

from advanced.config import Settings
from advanced.domain import CardNetwork
from advanced.ingestion.pipeline import ingest
from advanced.ingestion.store import WeaviateChunkStore
from advanced.rag import AdvancedRag
from advanced.retrieval.retriever import RetrievalQuery, WeaviateRetriever, WeaviateSectionStore
from advanced.vectordb import connect_sync, make_async
from migrations.apply import apply_all
from tests.fakes import (
    FakeAnswerer,
    FakePlanner,
    FakeReranker,
    fake_embed,
    make_settings,
    plan,
)

pytestmark = pytest.mark.integration

IMAGE = "cr.weaviate.io/semitechnologies/weaviate:1.38.20"
CORPUS = Path(__file__).parents[2] / "data" / "corpus"


def _wait_ready(url: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/v1/.well-known/ready", timeout=2) as r:  # noqa: S310
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise TimeoutError("Weaviate did not become ready")


@pytest.fixture(scope="session")
def settings() -> Iterator[Settings]:
    container = (
        DockerContainer(IMAGE)
        .with_exposed_ports(8080, 50051)
        .with_env("AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED", "true")
        .with_env("PERSISTENCE_DATA_PATH", "/var/lib/weaviate")
        .with_env("DEFAULT_VECTORIZER_MODULE", "none")
        .with_env("CLUSTER_HOSTNAME", "node1")
    )
    with container:
        host = container.get_container_host_ip()
        url = f"http://{host}:{container.get_exposed_port(8080)}"
        _wait_ready(url)
        yield make_settings(
            weaviate_url=url,
            weaviate_grpc_port=int(container.get_exposed_port(50051)),
            weaviate_vectorizer="none",
            max_vector_distance=None,
        )


def _store(client: WeaviateClient, s: Settings) -> WeaviateChunkStore:
    return WeaviateChunkStore(client, s.collection_name, s.section_collection, embed=fake_embed)


@pytest.fixture(scope="session")
def ingested(settings: Settings) -> Iterator[WeaviateClient]:
    with connect_sync(settings) as client:
        apply_all(client, settings)
        report = ingest([CORPUS], _store(client, settings))
        assert report.ok, report.errors
        yield client


@pytest.fixture
async def async_client(settings: Settings) -> AsyncIterator[WeaviateAsyncClient]:
    client = make_async(settings)
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


def test_migrations_create_both_collections_idempotently(
    ingested: WeaviateClient, settings: Settings
) -> None:
    apply_all(ingested, settings)
    assert ingested.collections.exists(settings.collection_name)
    assert ingested.collections.exists(settings.section_collection)


def test_reingest_identical_corpus_is_noop(ingested: WeaviateClient, settings: Settings) -> None:
    report = ingest([CORPUS], _store(ingested, settings))
    assert (report.created, report.updated, report.deleted, report.sections_written) == (0, 0, 0, 0)


async def test_child_hits_resolve_to_full_parent_sections(
    ingested: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    hits = await WeaviateRetriever(async_client, settings, embed=fake_embed).search(
        RetrievalQuery(text="Compelling Evidence 3.0 prior undisputed transactions")
    )
    assert hits and hits[0].doc_id == "visa-10-4"
    sections = await WeaviateSectionStore(async_client, settings).fetch([hits[0].parent_id])
    assert "IP address" in sections[0].content  # the whole section, not just the child window
    assert sections[0].section_path.endswith("Compelling evidence 3.0")


async def test_network_filter_excludes_other_networks(
    ingested: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    s = settings.model_copy(update={"per_query_limit": 30})
    hits = await WeaviateRetriever(async_client, s, embed=fake_embed).search(
        RetrievalQuery(text="evidence response window", card_network=CardNetwork.VISA)
    )
    docs = {h.doc_id for h in hits}
    assert docs & {"visa-10-4", "visa-13-1"}
    assert not docs & {"mc-4853", "mc-4837", "amex-core", "discover-fraud"}


async def test_superseded_version_never_returned(
    ingested: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    retriever = WeaviateRetriever(async_client, settings, embed=fake_embed)
    sections = WeaviateSectionStore(async_client, settings)
    q = "internal submission buffer representment packages"
    for as_of, want, not_want in [
        (date(2026, 10, 1), "7 calendar days", "5 calendar days"),
        (date(2025, 6, 1), "5 calendar days", "7 calendar days"),
    ]:
        hits = await retriever.search(RetrievalQuery(text=q, as_of=as_of))
        parents = await sections.fetch(
            list({h.parent_id for h in hits if h.doc_id == "sop-deadlines"})
        )
        text = " ".join(p.content for p in parents)
        assert want in text and not_want not in text


async def test_multi_query_comparison_end_to_end(
    ingested: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    """Real retrieval + fusion + parent fetch; planner/reranker/answerer are fakes."""
    p = plan(
        "Compare Visa 10.4 and Mastercard 4837 response windows",
        sub_queries=[
            "Compare Visa 10.4 and Mastercard 4837 response windows",
            "Visa 10.4 response window",
            "Mastercard 4837 response window",
        ],
    )
    answerer = FakeAnswerer()  # never reached: we only inspect retrieval
    rag = AdvancedRag(
        planner=FakePlanner(p),
        retriever=WeaviateRetriever(async_client, settings, embed=fake_embed),
        sections=WeaviateSectionStore(async_client, settings),
        reranker=FakeReranker(),
        answerer=answerer,
        settings=settings,
    )
    candidates = await rag.retrieve(p, date(2026, 10, 1))
    docs = [c.doc_id for c in candidates]
    assert {"visa-10-4", "mc-4837"} <= set(docs)
    assert len({c.section_id for c in candidates}) == len(candidates)


async def test_empty_collection_returns_empty(
    ingested: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    empty = settings.model_copy(
        update={"collection_name": "EmptyChunk", "section_collection": "EmptySection"}
    )
    apply_all(ingested, empty)
    hits = await WeaviateRetriever(async_client, empty, embed=fake_embed).search(
        RetrievalQuery(text="anything")
    )
    assert hits == []
