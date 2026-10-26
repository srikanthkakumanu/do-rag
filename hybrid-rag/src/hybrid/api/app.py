"""FastAPI app: `POST /v1/ask` -> scrub -> HybridRag (graph ‖ vector -> answer) -> audit."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from hybrid.api.schemas import AskRequest, AskResponse
from hybrid.config import Settings, get_settings
from hybrid.domain import QueryId
from hybrid.errors import GenerationError, HybridRagError, RetrievalError
from hybrid.generation.llm import OpenAIAnswerer
from hybrid.graph.planner import LLMGraphPlanner
from hybrid.graph.retriever import Neo4jGraphRetriever
from hybrid.graphdb import make_graph_async
from hybrid.ingestion.scrub import scrub
from hybrid.llm import OpenAIStructuredLLM, make_openai_client
from hybrid.observability import configure_logging
from hybrid.rag import HybridRag
from hybrid.retrieval.retriever import WeaviateRetriever
from hybrid.vectordb import make_async

log = structlog.get_logger(__name__)
audit = structlog.get_logger("audit")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create clients once at startup; close them at shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level)
    weaviate_client = make_async(settings)
    await weaviate_client.connect()
    graph_driver = make_graph_async(settings)
    openai_client = make_openai_client(settings)
    llm = OpenAIStructuredLLM(openai_client, settings)
    app.state.settings = settings
    app.state.rag = HybridRag(
        planner=LLMGraphPlanner(llm, settings),
        graph=Neo4jGraphRetriever(graph_driver, settings),
        retriever=WeaviateRetriever(weaviate_client, settings),
        answerer=OpenAIAnswerer(llm, settings),
        settings=settings,
    )
    try:
        yield
    finally:
        await weaviate_client.close()
        await graph_driver.close()
        await openai_client.close()


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_rag(request: Request) -> HybridRag:
    rag: HybridRag = request.app.state.rag
    return rag


class Forbidden(HybridRagError):
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
    app = FastAPI(title="Hybrid RAG: Dispute Policy Assistant", version="0.1.0", lifespan=lifespan)

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
        rag: Annotated[HybridRag, Depends(get_rag)],
    ) -> AskResponse:
        query_id = QueryId(str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(query_id=query_id)
        started = time.perf_counter()
        try:
            question = scrub(body.question).clean_text
            result = await rag.answer(question, card_network=body.card_network, as_of=body.as_of)
            audit.info(
                "answer",
                user_role=role,
                plan_codes=result.plan.reason_codes,
                plan_networks=result.plan.networks,
                plan_kinds=result.plan.kinds,
                planner_degraded=result.plan.degraded,
                graph_facts=result.facts,
                chunk_doc_ids=result.chunk_doc_ids,
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
                graph_facts_used=result.facts,
            )
        finally:
            structlog.contextvars.unbind_contextvars("query_id")

    return app


app = create_app()
