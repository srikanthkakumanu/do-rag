"""`answer_question()`: grounded answer or the exact refusal."""

from __future__ import annotations

import structlog

from basic.config import Settings
from basic.domain import REFUSAL_TEXT, Citation, GroundedAnswer, RetrievedChunk
from basic.generation.assembler import AssembledPrompt, assemble
from basic.generation.llm import Answerer, LLMAnswer, SchemaParseError
from basic.generation.validator import validate

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
    question: str, chunks: list[RetrievedChunk], *, answerer: Answerer, settings: Settings
) -> GroundedAnswer:
    """Never calls the LLM without sources; never returns an unvalidated answer."""
    version = settings.prompt_version
    if not chunks:
        log.warning("refusal", reason="no_chunks")
        return refusal(prompt_version=version, model=answerer.model)

    prompt = assemble(
        question, chunks, prompt_version=version, budget_tokens=settings.source_token_budget
    )
    if not prompt.chunks:
        log.warning("refusal", reason="budget_exhausted")
        return refusal(prompt_version=version, model=answerer.model)

    result = await _generate_with_retry(answerer, prompt)
    if result is None:
        return refusal(prompt_version=version, model=answerer.model)

    check = validate(result, prompt.chunks)
    if not check.ok:
        log.warning("refusal", reason=check.reason)
        return refusal(prompt_version=version, model=answerer.model)
    if result.refused:
        log.warning("refusal", reason="model_refused")
        return refusal(prompt_version=version, model=answerer.model)

    by_key: dict[tuple[str, str], RetrievedChunk] = {
        (c.doc_id, c.section_path): c for c in prompt.chunks
    }
    citations: list[Citation] = []
    for cit in result.citations:
        c = by_key[(cit.doc_id, cit.section_path)]
        entry = Citation(
            doc_id=c.doc_id, section_path=c.section_path, effective_date=c.effective_date
        )
        if entry not in citations:
            citations.append(entry)
    return GroundedAnswer(
        answer=result.answer,
        citations=citations,
        refused=False,
        prompt_version=version,
        model=answerer.model,
    )
