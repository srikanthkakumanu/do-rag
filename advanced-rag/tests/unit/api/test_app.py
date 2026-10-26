from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advanced.api.app import create_app, get_app_settings, get_rag
from advanced.domain import REFUSAL_TEXT, VERIFY_NOTICE, Turn
from advanced.errors import RetrievalError
from advanced.rag import AdvancedRag, RagResult
from tests.fakes import (
    FakeAnswerer,
    FakePlanner,
    FakeReranker,
    FakeRetriever,
    FakeSectionStore,
    cited_answer,
    hit,
    make_section,
    make_settings,
    plan,
)

ROLE = {"X-Auth-Roles": "disputes.read"}
SEC = make_section()


class RecordingRag(AdvancedRag):
    """Real orchestrator over fakes; records the inputs it receives."""

    seen: list[tuple[str, list[Turn]]]

    async def answer(self, question: str, history: list[Turn], **kw: object) -> RagResult:
        self.seen.append((question, history))
        return await super().answer(question, history, **kw)  # type: ignore[arg-type]


class FailingRag(AdvancedRag):
    async def answer(self, question: str, history: list[Turn], **kw: object) -> RagResult:
        raise RetrievalError("down")


def _build(cls: type[AdvancedRag], *, sections: bool = True) -> AdvancedRag:
    rag = cls(
        planner=FakePlanner(plan()),
        retriever=FakeRetriever([hit(SEC.section_id)] if sections else []),
        sections=FakeSectionStore(SEC),
        reranker=FakeReranker(),
        answerer=FakeAnswerer(
            cited_answer("Respond within 30 days.", (SEC.doc_id, SEC.section_path))
        ),
        settings=make_settings(),
    )
    if isinstance(rag, RecordingRag):
        rag.seen = []
    return rag


@asynccontextmanager
async def _no_lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


def _client(rag: AdvancedRag) -> TestClient:
    app = create_app()
    app.router.lifespan_context = _no_lifespan
    app.dependency_overrides[get_rag] = lambda: rag
    app.dependency_overrides[get_app_settings] = lambda: make_settings()
    return TestClient(app)


@pytest.fixture
def rag() -> AdvancedRag:
    return _build(RecordingRag)


@pytest.fixture
def client(rag: AdvancedRag) -> Iterator[TestClient]:
    with _client(rag) as c:
        yield c


def test_ask_returns_cited_answer_and_standalone_question(client: TestClient) -> None:
    res = client.post("/v1/ask", json={"question": "Visa 10.4 window?"}, headers=ROLE)
    assert res.status_code == 200
    body = res.json()
    assert body["refused"] is False
    assert body["citations"][0]["doc_id"] == "visa-10-4"
    assert body["standalone_question"]
    assert body["notice"] == VERIFY_NOTICE


def test_ask_scrubs_question_and_history(client: TestClient, rag: RecordingRag) -> None:
    payload = {
        "question": "card 4111 1111 1111 1111 window?",
        "history": [{"role": "user", "content": "my card 4111-1111-1111-1111"}],
    }
    client.post("/v1/ask", json=payload, headers=ROLE)
    question, history = rag.seen[0]
    assert "4111" not in question and "4111" not in history[0].content


def test_ask_rejects_bad_history_role(client: TestClient) -> None:
    res = client.post(
        "/v1/ask",
        json={"question": "q?x", "history": [{"role": "system", "content": "x"}]},
        headers=ROLE,
    )
    assert res.status_code == 422


def test_ask_without_role_is_403_problem(client: TestClient) -> None:
    res = client.post("/v1/ask", json={"question": "Visa 10.4 window?"})
    assert res.status_code == 403
    assert res.headers["content-type"].startswith("application/problem+json")


def test_ask_no_candidates_refuses() -> None:
    with _client(_build(AdvancedRag, sections=False)) as c:
        res = c.post("/v1/ask", json={"question": "anything?"}, headers=ROLE)
    assert res.json()["answer"] == REFUSAL_TEXT


def test_ask_retrieval_down_is_503_without_details() -> None:
    with _client(_build(FailingRag)) as c:
        res = c.post("/v1/ask", json={"question": "Visa 10.4?"}, headers=ROLE)
    assert res.status_code == 503
    assert "down" not in res.text
