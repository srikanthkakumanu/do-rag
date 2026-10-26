from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hybrid.api.app import create_app, get_app_settings, get_rag
from hybrid.domain import VERIFY_NOTICE, CardNetwork
from hybrid.errors import RetrievalError
from hybrid.graph.planner import GraphPlan
from hybrid.rag import HybridRag, RagResult
from tests.fakes import (
    FakeAnswerer,
    FakeGraphPlanner,
    FakeGraphRetriever,
    FakeRetriever,
    cited_answer,
    make_chunk,
    make_fact,
    make_settings,
)

ROLE = {"X-Auth-Roles": "disputes.read"}
FACT_SEC = "Mastercard 4853 > Response window"


class RecordingRag(HybridRag):
    questions: list[str]

    async def answer(
        self, question: str, *, card_network: CardNetwork | None = None, as_of: date | None = None
    ) -> RagResult:
        self.questions.append(question)
        return await super().answer(question, card_network=card_network, as_of=as_of)


class FailingRag(HybridRag):
    async def answer(
        self, question: str, *, card_network: CardNetwork | None = None, as_of: date | None = None
    ) -> RagResult:
        raise RetrievalError("neo4j down")


def _build[T: HybridRag](cls: type[T]) -> T:
    return cls(
        planner=FakeGraphPlanner(GraphPlan(deadline_days=45)),
        graph=FakeGraphRetriever([make_fact()]),
        retriever=FakeRetriever([make_chunk()]),
        answerer=FakeAnswerer(cited_answer("Mastercard 4853: 45 days.", ("mc-4853", FACT_SEC))),
        settings=make_settings(),
    )


@asynccontextmanager
async def _no_lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


def _client(rag: HybridRag) -> TestClient:
    app = create_app()
    app.router.lifespan_context = _no_lifespan
    app.dependency_overrides[get_rag] = lambda: rag
    app.dependency_overrides[get_app_settings] = lambda: make_settings()
    return TestClient(app)


@pytest.fixture
def rag() -> RecordingRag:
    r = _build(RecordingRag)
    r.questions = []
    return r


@pytest.fixture
def client(rag: RecordingRag) -> Iterator[TestClient]:
    with _client(rag) as c:
        yield c


def test_ask_returns_answer_with_graph_fact_count(client: TestClient) -> None:
    res = client.post("/v1/ask", json={"question": "Which codes give 45 days?"}, headers=ROLE)
    assert res.status_code == 200
    body = res.json()
    assert body["graph_facts_used"] == 1
    assert body["citations"][0]["doc_id"] == "mc-4853"
    assert body["notice"] == VERIFY_NOTICE


def test_ask_scrubs_question(client: TestClient, rag: RecordingRag) -> None:
    client.post("/v1/ask", json={"question": "card 4111 1111 1111 1111 45 days?"}, headers=ROLE)
    assert "4111" not in rag.questions[0]


def test_ask_without_role_is_403_problem(client: TestClient) -> None:
    res = client.post("/v1/ask", json={"question": "Which codes give 45 days?"})
    assert res.status_code == 403
    assert res.headers["content-type"].startswith("application/problem+json")


def test_ask_store_down_is_503_without_details() -> None:
    with _client(_build(FailingRag)) as c:
        res = c.post("/v1/ask", json={"question": "Visa 10.4?"}, headers=ROLE)
    assert res.status_code == 503 and "neo4j" not in res.text
