"""FastAPI app: `POST /v1/ask` -> scrub -> AdvancedRag (plan, retrieve, rerank, answer) -> audit."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from advanced.api.schemas import AskRequest, AskResponse
from advanced.config import Settings, get_settings
from advanced.domain import QueryId, Turn
from advanced.errors import AdvancedRagError, GenerationError, RetrievalError
from advanced.generation.llm import OpenAIAnswerer
from advanced.ingestion.scrub import scrub
from advanced.llm import OpenAIStructuredLLM, make_openai_client
from advanced.observability import configure_logging
from advanced.query.planner import LLMQueryPlanner
from advanced.rag import AdvancedRag
from advanced.retrieval.reranker import LLMReranker
from advanced.retrieval.retriever import WeaviateRetriever, WeaviateSectionStore
from advanced.vectordb import make_async

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
    llm = OpenAIStructuredLLM(openai_client, settings)
    app.state.settings = settings
    app.state.rag = AdvancedRag(
        planner=LLMQueryPlanner(llm, settings),
        retriever=WeaviateRetriever(weaviate_client, settings),
        sections=WeaviateSectionStore(weaviate_client, settings),
        reranker=LLMReranker(llm, settings),
        answerer=OpenAIAnswerer(llm, settings),
        settings=settings,
    )
    try:
        yield
    finally:
        await weaviate_client.close()
        await openai_client.close()


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_rag(request: Request) -> AdvancedRag:
    rag: AdvancedRag = request.app.state.rag
    return rag


class Forbidden(AdvancedRagError):
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
    app = FastAPI(
        title="Advanced RAG: Dispute Policy Assistant", version="0.1.0", lifespan=lifespan
    )

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
        rag: Annotated[AdvancedRag, Depends(get_rag)],
    ) -> AskResponse:
        query_id = QueryId(str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(query_id=query_id)
        started = time.perf_counter()
        try:
            question = scrub(body.question).clean_text
            history = [Turn(role=t.role, content=scrub(t.content).clean_text) for t in body.history]
            result = await rag.answer(
                question, history, card_network=body.card_network, as_of=body.as_of
            )
            audit.info(
                "answer",
                user_role=role,
                plan_network=result.plan.card_network,
                plan_codes=result.plan.reason_codes,
                sub_queries=len(result.plan.sub_queries),
                planner_degraded=result.plan.degraded,
                candidate_ids=result.candidate_ids,
                rerank_scores=result.rerank_scores,
                model=result.answer.model,
                prompt_version=result.answer.prompt_version,
                latency_ms=round((time.perf_counter() - started) * 1000),
                refused=result.answer.refused,
                refusal_reason=result.refusal_reason,
            )
            return AskResponse(
                answer=result.answer.answer,
                citations=result.answer.citations,
                refused=result.answer.refused,
                query_id=query_id,
                prompt_version=result.answer.prompt_version,
                standalone_question=result.plan.standalone_question,
            )
        finally:
            structlog.contextvars.unbind_contextvars("query_id")

    return app


app = create_app()
