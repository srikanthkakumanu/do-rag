"""Post-generation checks: citations must point at sent sections, and every number or
reason code in the answer must appear verbatim in a cited chunk."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from advanced.domain import RetrievedSection
from advanced.generation.llm import LLMAnswer

_CITATION_MARK: Final = re.compile(r"\[[^\[\]]*§[^\[\]]*\]")
# Numbers (5, 30, 120, 10.4, 1,000) and alphanumeric codes (C08, UA02).
_FACT_TOKEN: Final = re.compile(r"\b(?:[A-Z]{1,2}\d{2}|\d+(?:[.,]\d+)*)\b")


_NUMBER_WORDS: Final = {
    w: str(i)
    for i, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        ]
    )
} | {"thirty": "30", "forty": "40", "forty-five": "45", "sixty": "60", "ninety": "90"}
_WORD_RX: Final = re.compile(
    r"\b(" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")\b", re.I
)


def with_number_words(text: str) -> str:
    """Append digit forms of spelled-out numbers ("two" also supports "2")."""
    digits = {_NUMBER_WORDS[m.group(1).lower()] for m in _WORD_RX.finditer(text)}
    return f"{text}\n{' '.join(sorted(digits))}" if digits else text


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    reason: str | None = None


def validate(
    answer: LLMAnswer, sent: tuple[RetrievedSection, ...], question: str = ""
) -> ValidationResult:
    """Facts must come from a cited section, or be echoed from the user's own question."""
    if answer.refused:
        return ValidationResult(ok=True)
    if not answer.citations:
        return ValidationResult(ok=False, reason="no_citations")

    by_key: dict[tuple[str, str], RetrievedSection] = {(c.doc_id, c.section_path): c for c in sent}
    cited: list[RetrievedSection] = []
    for cit in answer.citations:
        chunk = by_key.get((cit.doc_id, cit.section_path))
        if chunk is None:
            return ValidationResult(ok=False, reason="citation_mismatch")
        cited.append(chunk)

    body = _CITATION_MARK.sub(" ", answer.answer)
    cited_text = with_number_words("\n".join([question, *(c.content for c in cited)]))
    for token in _FACT_TOKEN.findall(body):
        if not re.search(rf"(?<![\w.]){re.escape(token)}(?![\w])", cited_text):
            return ValidationResult(ok=False, reason="unsupported_fact")
    return ValidationResult(ok=True)
