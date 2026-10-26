"""FastAPI app: `POST /v1/ask` -> scrub -> retrieve -> generate -> audit."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from basic.api.schemas import AskRequest, AskResponse
from basic.config import Settings, get_settings
from basic.domain import QueryId
from basic.errors import BasicRagError, GenerationError, RetrievalError
from basic.generation.llm import Answerer, OpenAIAnswerer, make_openai_client
from basic.generation.service import answer_question
from basic.ingestion.scrub import scrub
from basic.observability import configure_logging
from basic.retrieval.retriever import RetrievalQuery, Retriever, WeaviateRetriever
from basic.vectordb import make_async

log = structlog.get_logger(__name__)
audit = structlog.get_logger("audit")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create clients once at startup; close them at shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level)
    weaviate_client = make_async(settings)
    await weaviate_client.connect()
    openai_client = make_openai_client(settings)
    app.state.settings = settings
    app.state.retriever = WeaviateRetriever(weaviate_client, settings)
    app.state.answerer = OpenAIAnswerer(openai_client, settings)
    try:
        yield
    finally:
        await weaviate_client.close()
        await openai_client.close()


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_retriever(request: Request) -> Retriever:
    retriever: Retriever = request.app.state.retriever
    return retriever


def get_answerer(request: Request) -> Answerer:
    answerer: Answerer = request.app.state.answerer
    return answerer


class Forbidden(BasicRagError):
    """Caller lacks the required role."""


def require_role(
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_auth_roles: Annotated[str | None, Header()] = None,
) -> str:
    """The gateway verifies the SSO JWT and forwards roles in `X-Auth-Roles`."""
    roles = {r.strip() for r in (x_auth_roles or "").split(",") if r.strip()}
    if settings.required_role not in roles:
        raise Forbidden(f"missing role {settings.required_role}")
    return settings.required_role


def problem(status: int, title: str, detail: str) -> JSONResponse:
    """RFC 9457 problem response; never leaks stack traces or provider bodies."""
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Basic RAG: Dispute Policy Assistant", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(Forbidden)
    async def _forbidden(_: Request, e: Forbidden) -> JSONResponse:
        return problem(403, "Forbidden", str(e))

    @app.exception_handler(RetrievalError)
    async def _retrieval(_: Request, e: RetrievalError) -> JSONResponse:
        log.error("retrieval_failed", error=str(e))
        return problem(503, "Retrieval unavailable", "The policy index is unavailable.")

    @app.exception_handler(GenerationError)
    async def _generation(_: Request, e: GenerationError) -> JSONResponse:
        log.error("generation_failed", error=str(e))
        return problem(502, "Generation failed", "The answer service is unavailable.")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/ask", response_model=AskResponse)
    async def ask(
        body: AskRequest,
        role: Annotated[str, Depends(require_role)],
        settings: Annotated[Settings, Depends(get_app_settings)],
        retriever: Annotated[Retriever, Depends(get_retriever)],
        answerer: Annotated[Answerer, Depends(get_answerer)],
    ) -> AskResponse:
        query_id = QueryId(str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(query_id=query_id)
        started = time.perf_counter()
        try:
            question = scrub(body.question).clean_text
            chunks = await retriever.search(
                RetrievalQuery(
                    text=question, card_network=body.card_network, as_of=body.as_of or date.today()
                )
            )
            result = await answer_question(question, chunks, answerer=answerer, settings=settings)
            audit.info(
                "answer",
                user_role=role,
                chunk_ids=[c.chunk_id for c in chunks],
                model=result.model,
                prompt_version=result.prompt_version,
                latency_ms=round((time.perf_counter() - started) * 1000),
                refused=result.refused,
            )
            return AskResponse(
                answer=result.answer,
                citations=result.citations,
                refused=result.refused,
                query_id=query_id,
                prompt_version=result.prompt_version,
            )
        finally:
            structlog.contextvars.unbind_contextvars("query_id")

    return app


app = create_app()
