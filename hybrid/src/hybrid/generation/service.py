"""`answer_question()`: grounded answer over graph facts + chunks, or the exact refusal."""

from __future__ import annotations

import structlog

from hybrid.config import Settings
from hybrid.domain import REFUSAL_TEXT, Citation, GraphFact, GroundedAnswer, RetrievedChunk
from hybrid.generation.assembler import AssembledPrompt, assemble
from hybrid.generation.llm import Answerer, LLMAnswer, SchemaParseError
from hybrid.generation.validator import evidence_index, validate

log = structlog.get_logger(__name__)


def refusal(*, prompt_version: str, model: str) -> GroundedAnswer:
    return GroundedAnswer(
        answer=REFUSAL_TEXT, citations=[], refused=True, prompt_version=prompt_version, model=model
    )


async def _generate_with_retry(answerer: Answerer, prompt: AssembledPrompt) -> LLMAnswer | None:
    """Retry once on schema-parse failure, then give up (caller refuses)."""
    for attempt in (1, 2):
        try:
            return await answerer.generate(prompt)
        except SchemaParseError:
            log.warning("llm_schema_parse_failed", attempt=attempt)
    return None


async def answer_question(
    question: str,
    chunks: list[RetrievedChunk],
    facts: list[GraphFact],
    *,
    answerer: Answerer,
    settings: Settings,
) -> GroundedAnswer:
    """Never calls the LLM without evidence; never returns an unvalidated answer."""
    version, model = settings.prompt_version, answerer.model
    if not chunks and not facts:
        log.warning("refusal", reason="no_evidence")
        return refusal(prompt_version=version, model=model)

    prompt = assemble(
        question, chunks, facts, prompt_version=version, budget_tokens=settings.source_token_budget
    )
    result = await _generate_with_retry(answerer, prompt)
    if result is None:
        return refusal(prompt_version=version, model=model)
    check = validate(result, prompt, question)
    if not check.ok:
        log.warning("refusal", reason=check.reason)
        return refusal(prompt_version=version, model=model)
    if result.refused:
        log.warning("refusal", reason="model_refused")
        return refusal(prompt_version=version, model=model)

    index = evidence_index(prompt)
    citations: list[Citation] = []
    for cit in result.citations:
        item = index[(cit.doc_id, cit.section_path)]
        entry = Citation(
            doc_id=cit.doc_id, section_path=cit.section_path, effective_date=item.effective_date
        )
        if entry not in citations:
            citations.append(entry)
    return GroundedAnswer(
        answer=result.answer,
        citations=citations,
        refused=False,
        prompt_version=version,
        model=model,
    )
