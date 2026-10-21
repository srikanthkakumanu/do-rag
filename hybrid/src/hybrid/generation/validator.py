"""Post-generation checks over BOTH evidence kinds: citations must point at a sent graph
fact or chunk, and numbers/codes must appear in a cited item (or the user's question)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Final

from hybrid.generation.assembler import AssembledPrompt
from hybrid.generation.llm import LLMAnswer

_CITATION_MARK: Final = re.compile(r"\[[^\[\]]*§[^\[\]]*\]")
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


@dataclass(frozen=True, slots=True)
class CitedItem:
    text: str
    effective_date: date


def evidence_index(prompt: AssembledPrompt) -> dict[tuple[str, str], CitedItem]:
    """(doc_id, section_path) -> all text sent under that citation key."""
    index: dict[tuple[str, str], CitedItem] = {}
    pieces = [(c.doc_id, c.section_path, c.content, c.effective_date) for c in prompt.chunks]
    pieces += [
        (f.doc_id, f.section_path, f"{f.statement}\n{f.quote}", f.effective_date)
        for f in prompt.facts
    ]
    for doc, section, text, eff in pieces:
        prev = index.get((doc, section))
        index[(doc, section)] = CitedItem(f"{prev.text}\n{text}" if prev else text, eff)
    return index


def validate(answer: LLMAnswer, prompt: AssembledPrompt, question: str = "") -> ValidationResult:
    if answer.refused:
        return ValidationResult(ok=True)
    if not answer.citations:
        return ValidationResult(ok=False, reason="no_citations")
    index = evidence_index(prompt)
    cited: list[str] = []
    for cit in answer.citations:
        item = index.get((cit.doc_id, cit.section_path))
        if item is None:
            return ValidationResult(ok=False, reason="citation_mismatch")
        cited.append(item.text)
    allowed = with_number_words("\n".join([question, *cited]))
    for token in _FACT_TOKEN.findall(_CITATION_MARK.sub(" ", answer.answer)):
        if not re.search(rf"(?<![\w.]){re.escape(token)}(?![\w])", allowed):
            return ValidationResult(ok=False, reason="unsupported_fact")
    return ValidationResult(ok=True)
