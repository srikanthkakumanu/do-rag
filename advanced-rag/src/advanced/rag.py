"""Advanced RAG orchestration:
plan -> (out of scope? refuse) -> multi-query hybrid -> RRF to parents -> rerank -> CRAG gate
-> grounded generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date

import structlog
from opentelemetry import trace

from advanced.config import Settings
from advanced.domain import CardNetwork, GroundedAnswer, RetrievedSection, SectionId, Turn
from advanced.generation.llm import Answerer
from advanced.generation.service import answer_question, refusal
from advanced.query.planner import QueryPlan, QueryPlanner
from advanced.retrieval.fusion import rrf_parents
from advanced.retrieval.reranker import Reranker
from advanced.retrieval.retriever import RetrievalQuery, Retriever, SectionStore

log = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)


@dataclass(slots=True)
class RagResult:
    answer: GroundedAnswer
    plan: QueryPlan
    refusal_reason: str | None = None
    candidate_ids: list[str] = field(default_factory=list)
    candidate_doc_ids: list[str] = field(default_factory=list)  # fused order, pre-rerank
    rerank_scores: list[float] = field(default_factory=list)
    retrieved_doc_ids: list[str] = field(default_factory=list)


class AdvancedRag:
    def __init__(
        self,
        *,
        planner: QueryPlanner,
        retriever: Retriever,
        sections: SectionStore,
        reranker: Reranker,
        answerer: Answerer,
        settings: Settings,
    ) -> None:
        self._planner = planner
        self._retriever = retriever
        self._sections = sections
        self._reranker = reranker
        self._answerer = answerer
        self._settings = settings

    def _refuse(
        self,
        plan: QueryPlan,
        reason: str,
        candidate_ids: list[str] | None = None,
        retrieved_doc_ids: list[str] | None = None,
        candidate_doc_ids: list[str] | None = None,
    ) -> RagResult:
        log.warning("refusal", reason=reason)
        answer = refusal(prompt_version=self._settings.prompt_version, model=self._answerer.model)
        return RagResult(
            answer=answer,
            plan=plan,
            refusal_reason=reason,
            candidate_ids=candidate_ids or [],
            retrieved_doc_ids=retrieved_doc_ids or [],
            candidate_doc_ids=candidate_doc_ids or [],
        )

    async def retrieve(self, plan: QueryPlan, as_of: date) -> list[RetrievedSection]:
        """Multi-query hybrid search, fused to parent sections (RRF order)."""
        s = self._settings
        with _tracer.start_as_current_span("retrieval.multi_query"):
            lists = await asyncio.gather(
                *(
                    self._retriever.search(
                        RetrievalQuery(text=q, card_network=plan.card_network, as_of=as_of)
                    )
                    for q in plan.sub_queries
                )
            )
        fused = rrf_parents(lists, s.rrf_k)
        # Doc-diversity cap needs doc_id per parent: take it from the best child hit.
        doc_of = {h.parent_id: h.doc_id for hits in lists for h in reversed(hits)}
        per_doc: dict[str, int] = {}
        picked: list[tuple[SectionId, float]] = []
        for sid, sc in fused:
            doc = doc_of[sid]
            if per_doc.get(doc, 0) < s.max_sections_per_doc:
                per_doc[doc] = per_doc.get(doc, 0) + 1
                picked.append((sid, sc))
            if len(picked) == s.rerank_candidates:
                break
        fused = picked
        sections = await self._sections.fetch([sid for sid, _ in fused])
        score = dict(fused)
        return [
            RetrievedSection(
                section_id=x.section_id,
                doc_id=x.doc_id,
                section_path=x.section_path,
                effective_date=x.effective_date,
                content=x.content,
                score=score[x.section_id],
            )
            for x in sections
        ]

    async def answer(
        self,
        question: str,
        history: list[Turn],
        *,
        card_network: CardNetwork | None = None,
        as_of: date | None = None,
    ) -> RagResult:
        s = self._settings
        plan = await self._planner.plan(question, history, card_network)
        if not plan.in_scope:
            return self._refuse(plan, "out_of_scope")

        candidates = await self.retrieve(plan, as_of or date.today())
        if not candidates:
            return self._refuse(plan, "no_candidates")

        ranked = await self._reranker.rerank(plan.standalone_question, candidates)
        kept = [x for x in ranked if x.score >= s.min_rerank_score][: s.rerank_top_n]
        candidate_ids: list[str] = [x.section_id for x in candidates]
        candidate_docs: list[str] = [x.doc_id for x in candidates]
        doc_ids: list[str] = list(dict.fromkeys(x.doc_id for x in kept))
        if not kept:  # corrective gate: nothing relevant enough to answer from
            return self._refuse(plan, "low_relevance", candidate_ids, None, candidate_docs)

        answer = await answer_question(
            plan.standalone_question, kept, answerer=self._answerer, settings=s
        )
        return RagResult(
            answer=answer,
            plan=plan,
            refusal_reason="generation" if answer.refused else None,
            candidate_ids=candidate_ids,
            candidate_doc_ids=candidate_docs,
            rerank_scores=[x.score for x in kept],
            retrieved_doc_ids=doc_ids,
        )
