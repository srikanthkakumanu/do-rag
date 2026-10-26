from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from basic.api.app import create_app, get_answerer, get_app_settings, get_retriever
from basic.domain import REFUSAL_TEXT, VERIFY_NOTICE
from basic.errors import RetrievalError
from basic.retrieval.retriever import RetrievalQuery
from tests.fakes import FakeAnswerer, FakeRetriever, cited_answer, make_chunk, make_settings

SEC = "Visa 10.4 > Response window"
ROLE = {"X-Auth-Roles": "disputes.read"}


class FailingRetriever:
    async def search(self, q: RetrievalQuery) -> list[object]:
        raise RetrievalError("down")


def _app(retriever: object, answerer: FakeAnswerer) -> FastAPI:
    app = create_app()
    app.router.lifespan_context = _no_lifespan  # no real Weaviate/OpenAI in unit tests
    app.dependency_overrides[get_app_settings] = lambda: make_settings()
    app.dependency_overrides[get_retriever] = lambda: retriever
    app.dependency_overrides[get_answerer] = lambda: answerer
    return app


@asynccontextmanager
async def _no_lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture
def retriever() -> FakeRetriever:
    return FakeRetriever([make_chunk()])


@pytest.fixture
def client(retriever: FakeRetriever) -> Iterator[TestClient]:
    answerer = FakeAnswerer(cited_answer("Respond within 30 days.", ("visa-10-4", SEC)))
    with TestClient(_app(retriever, answerer)) as c:
        yield c


def test_ask_returns_cited_answer(client: TestClient) -> None:
    res = client.post("/v1/ask", json={"question": "Visa 10.4 window?"}, headers=ROLE)
    assert res.status_code == 200
    body = res.json()
    assert body["refused"] is False
    assert body["citations"][0]["doc_id"] == "visa-10-4"
    assert body["notice"] == VERIFY_NOTICE
    assert body["query_id"]


def test_ask_scrubs_pan_before_retrieval(client: TestClient, retriever: FakeRetriever) -> None:
    client.post("/v1/ask", json={"question": "card 4111 1111 1111 1111 10.4?"}, headers=ROLE)
    assert "4111" not in retriever.queries[0].text


def test_ask_without_role_is_403_problem(client: TestClient) -> None:
    res = client.post("/v1/ask", json={"question": "Visa 10.4 window?"})
    assert res.status_code == 403
    assert res.headers["content-type"].startswith("application/problem+json")


def test_ask_no_chunks_refuses() -> None:
    with TestClient(_app(FakeRetriever([]), FakeAnswerer())) as c:
        res = c.post("/v1/ask", json={"question": "weather?"}, headers=ROLE)
    assert res.json()["answer"] == REFUSAL_TEXT


def test_ask_retrieval_down_is_503_without_details() -> None:
    with TestClient(_app(FailingRetriever(), FakeAnswerer())) as c:
        res = c.post("/v1/ask", json={"question": "Visa 10.4?"}, headers=ROLE)
    assert res.status_code == 503
    assert "down" not in res.text


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
