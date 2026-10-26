"""Hybrid RAG orchestration: (graph plan ‖ vector search) -> graph facts (when the plan
has a signal) -> fused, validated answer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date

import structlog

from hybrid.config import Settings
from hybrid.domain import CardNetwork, GraphFact, GroundedAnswer, RetrievedChunk
from hybrid.generation.llm import Answerer
from hybrid.generation.service import answer_question
from hybrid.graph.planner import GraphPlan, GraphPlanner
from hybrid.graph.retriever import GraphRetriever
from hybrid.retrieval.retriever import RetrievalQuery, Retriever

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class RagResult:
    answer: GroundedAnswer
    plan: GraphPlan
    refusal_reason: str | None = None
    chunk_doc_ids: list[str] = field(default_factory=list)
    fact_doc_ids: list[str] = field(default_factory=list)
    facts: int = 0


class HybridRag:
    def __init__(
        self,
        *,
        planner: GraphPlanner,
        graph: GraphRetriever,
        retriever: Retriever,
        answerer: Answerer,
        settings: Settings,
    ) -> None:
        self._planner = planner
        self._graph = graph
        self._retriever = retriever
        self._answerer = answerer
        self._settings = settings

    async def answer(
        self, question: str, *, card_network: CardNetwork | None = None, as_of: date | None = None
    ) -> RagResult:
        when = as_of or date.today()
        # Independent work runs concurrently: the graph plan does not need vector results.
        plan, chunks = await asyncio.gather(
            self._planner.plan(question, card_network),
            self._retriever.search(
                RetrievalQuery(text=question, card_network=card_network, as_of=when)
            ),
        )
        # `in_scope=False` only means "the graph has nothing to add": skip it. Scope and
        # refusal stay with the grounded answer step (as in basic-rag/), never the graph planner.
        facts: list[GraphFact] = await self._graph.facts(plan, when) if plan.in_scope else []
        result = await answer_question(
            question, chunks, facts, answerer=self._answerer, settings=self._settings
        )
        return RagResult(
            answer=result,
            plan=plan,
            refusal_reason=("no_evidence" if not chunks and not facts else "generation")
            if result.refused
            else None,
            chunk_doc_ids=_doc_ids(chunks),
            fact_doc_ids=list(dict.fromkeys(f.doc_id for f in facts)),
            facts=len(facts),
        )


def _doc_ids(chunks: list[RetrievedChunk]) -> list[str]:
    return [c.doc_id for c in chunks]
