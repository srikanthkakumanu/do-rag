from __future__ import annotations

from datetime import date

from hybrid.domain import CardNetwork, Chunk, ChunkId, DocId, FactKind, SourceType
from hybrid.errors import GenerationError
from hybrid.ingestion.extract import LLMExtraction, LLMFact, LLMFactExtractor, extract_all, guard
from tests.fakes import FakeLLM, RegexExtractor, make_settings

TEXT = (
    "Mastercard 4853 Cardholder Dispute > Response window\n\n"
    "The merchant has 45 calendar days from the chargeback date to submit a second presentment.\n"
    "- Proof that a credit was already processed."
)


def _chunk(content: str = TEXT, codes: tuple[str, ...] = ("4853",)) -> Chunk:
    return Chunk(
        chunk_id=ChunkId("c1"),
        doc_id=DocId("mc-4853"),
        doc_title="Mastercard 4853",
        version="1",
        section_path="Mastercard 4853 > Response window",
        chunk_index=0,
        source_type=SourceType.NETWORK_RULE,
        card_network=CardNetwork.MASTERCARD,
        reason_codes=codes,
        jurisdiction="global",
        effective_date=date(2026, 1, 1),
        content=content,
        content_hash="h",
    )


def _fact(**kw: object) -> LLMFact:
    base: dict[str, object] = {
        "reason_code": "4853",
        "kind": "deadline",
        "value": None,
        "days": 45,
        "party": "merchant",
        "action": "Submit a second presentment",
        "quote": "The merchant has 45 calendar days from the chargeback date",
    }
    base.update(kw)
    return LLMFact(**base)


def test_guard_keeps_grounded_deadline_and_normalizes() -> None:
    out = guard(LLMExtraction(facts=[_fact()]), _chunk())
    assert out.rejected == 0
    (f,) = out.facts
    assert (f.kind, f.days, f.action) == (FactKind.DEADLINE, 45, "submit a second presentment")
    assert f.target == "45|merchant|submit a second presentment"


def test_guard_rejects_paraphrased_quote() -> None:
    out = guard(LLMExtraction(facts=[_fact(quote="Merchants get 45 days to respond")]), _chunk())
    assert out.facts == () and out.rejected == 1


def test_guard_rejects_days_not_in_quote() -> None:
    assert guard(LLMExtraction(facts=[_fact(days=30)]), _chunk()).rejected == 1


def test_guard_rejects_code_not_in_chunk() -> None:
    assert guard(LLMExtraction(facts=[_fact(reason_code="10.4")]), _chunk()).rejected == 1


def test_guard_remedy_and_bad_category() -> None:
    remedy = _fact(
        kind="remedy",
        value=" Proof that a credit was already processed. ",
        days=None,
        party=None,
        action=None,
        quote="Proof that a credit was already processed.",
    )
    bad_cat = _fact(kind="category", value="friendly_fraud", days=None, party=None, action=None)
    out = guard(LLMExtraction(facts=[remedy, bad_cat]), _chunk())
    assert [f.target for f in out.facts] == ["proof that a credit was already processed"]
    assert out.rejected == 1


def test_guard_dedupes_identical_facts() -> None:
    out = guard(LLMExtraction(facts=[_fact(), _fact()]), _chunk())
    assert len(out.facts) == 1 and out.rejected == 1


async def test_extractor_skips_chunks_without_codes() -> None:
    llm = FakeLLM()
    out = await LLMFactExtractor(llm, make_settings()).extract(_chunk(codes=()))
    assert out.facts == () and llm.calls == []


async def test_extractor_failure_marks_failed() -> None:
    llm = FakeLLM(extract=[GenerationError("down")])
    out = await LLMFactExtractor(llm, make_settings()).extract(_chunk())
    assert out.failed


async def test_extract_all_keys_by_chunk_id() -> None:
    out = await extract_all(RegexExtractor(), [_chunk()], concurrency=2)
    assert out["c1"].facts[0].days == 45
