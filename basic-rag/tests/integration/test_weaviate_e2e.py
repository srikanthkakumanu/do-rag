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

from basic.config import Settings
from basic.domain import CardNetwork
from basic.ingestion.pipeline import ingest
from basic.ingestion.store import WeaviateChunkStore
from basic.retrieval.retriever import RetrievalQuery, WeaviateRetriever
from basic.vectordb import connect_sync, make_async
from migrations.apply import apply_all
from tests.fakes import fake_embed, make_settings

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
            hybrid_alpha=0.5,
            max_vector_distance=None,
        )


@pytest.fixture(scope="session")
def sync_client(settings: Settings) -> Iterator[WeaviateClient]:
    with connect_sync(settings) as client:
        apply_all(client, settings)
        yield client


@pytest.fixture(scope="session")
def ingested(sync_client: WeaviateClient, settings: Settings) -> WeaviateClient:
    store = WeaviateChunkStore(sync_client, settings.collection_name, embed=fake_embed)
    report = ingest([CORPUS], store)
    assert report.ok, report.errors
    return sync_client


@pytest.fixture
async def async_client(settings: Settings) -> AsyncIterator[WeaviateAsyncClient]:
    client = make_async(settings)
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


def _retriever(client: WeaviateAsyncClient, settings: Settings, **kw: object) -> WeaviateRetriever:
    return WeaviateRetriever(client, settings.model_copy(update=kw), embed=fake_embed)


def test_migrations_are_idempotent(sync_client: WeaviateClient, settings: Settings) -> None:
    apply_all(sync_client, settings)
    assert sync_client.collections.exists(settings.collection_name)


def test_reingest_identical_corpus_is_noop(ingested: WeaviateClient, settings: Settings) -> None:
    store = WeaviateChunkStore(ingested, settings.collection_name, embed=fake_embed)
    report = ingest([CORPUS], store)
    assert (report.created, report.updated, report.deleted) == (0, 0, 0)
    assert report.skipped > 0


def test_no_pan_in_index(ingested: WeaviateClient, settings: Settings) -> None:
    objs = ingested.collections.use(settings.collection_name).query.fetch_objects(limit=500)
    text = " ".join(str(o.properties["content"]) for o in objs.objects)
    assert "4111" not in text
    assert "[PAN_REDACTED]" in text


async def test_exact_reason_code_ranks_first(
    ingested: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    retriever = _retriever(async_client, settings, hybrid_alpha=0.2)
    results = await retriever.search(RetrievalQuery(text="4853", as_of=date(2026, 10, 1)))
    assert results
    assert results[0].doc_id == "mc-4853"


async def test_network_filter_includes_all_and_excludes_others(
    ingested: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    retriever = _retriever(async_client, settings, top_k=20)
    results = await retriever.search(
        RetrievalQuery(text="evidence response window", card_network=CardNetwork.VISA)
    )
    docs = {r.doc_id for r in results}
    assert docs & {"visa-10-4", "visa-13-1"}
    assert not docs & {"mc-4853", "mc-4837", "amex-core", "discover-fraud"}


async def test_superseded_version_never_returned(
    ingested: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    retriever = _retriever(async_client, settings, top_k=20)
    q = "internal submission buffer representment packages"
    now = await retriever.search(RetrievalQuery(text=q, as_of=date(2026, 10, 1)))
    before = await retriever.search(RetrievalQuery(text=q, as_of=date(2025, 6, 1)))
    now_text = " ".join(r.content for r in now if r.doc_id == "sop-deadlines")
    before_text = " ".join(r.content for r in before if r.doc_id == "sop-deadlines")
    assert "7 calendar days" in now_text and "5 calendar days" not in now_text
    assert "5 calendar days" in before_text and "7 calendar days" not in before_text


async def test_results_sorted_unique_and_capped(
    ingested: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    retriever = _retriever(async_client, settings, top_k=3)
    results = await retriever.search(RetrievalQuery(text="fraud dispute evidence"))
    assert len(results) <= 3
    assert len({r.chunk_id for r in results}) == len(results)
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)


async def test_empty_collection_returns_empty(
    sync_client: WeaviateClient, async_client: WeaviateAsyncClient, settings: Settings
) -> None:
    empty = settings.model_copy(update={"collection_name": "EmptyPolicyChunk"})
    apply_all(sync_client, empty)
    results = await _retriever(async_client, empty).search(RetrievalQuery(text="anything"))
    assert results == []
