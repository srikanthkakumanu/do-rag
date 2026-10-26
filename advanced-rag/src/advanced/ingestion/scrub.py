"""PAN (Luhn) and PII redaction. Shared by ingestion and the query path."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

PAN_TOKEN: Final = "[PAN_REDACTED]"
CVV_TOKEN: Final = "[CVV_REDACTED]"
EMAIL_TOKEN: Final = "[EMAIL_REDACTED]"
PHONE_TOKEN: Final = "[PHONE_REDACTED]"
ACCOUNT_TOKEN: Final = "[ACCOUNT_REDACTED]"
NAME_TOKEN: Final = "[NAME_REDACTED]"

# 13-19 digits, optionally separated by single spaces or dashes.
_PAN_CANDIDATE: Final = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
_CVV: Final = re.compile(
    r"\b(CVV2?|CVC2?|CID|security\s+code)(\s*[:#]?\s*)\d{3,4}\b", re.IGNORECASE
)
_EMAIL: Final = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE: Final = re.compile(r"(?<![\w-])(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w-])")
_ACCOUNT: Final = re.compile(
    r"\b(account|acct|iban)(\s*(?:number|no\.?|#)?\s*[:#]?\s*)(?=[A-Z0-9]*\d)[A-Z0-9]{6,34}\b",
    re.IGNORECASE,
)
_NAME: Final = re.compile(
    r"\b((?i:cardholder(?:\s+name)?|customer\s+name))(\s*[:=]\s*)[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}"
)


@dataclass(frozen=True, slots=True)
class ScrubResult:
    clean_text: str
    redaction_count: int


def luhn_valid(digits: str) -> bool:
    """True when `digits` passes the Luhn checksum used by card PANs."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _digits(text: str) -> str:
    return re.sub(r"[ -]", "", text)


def find_pan_span(candidate: str) -> tuple[int, int] | None:
    """First Luhn-valid 13-19 digit span starting and ending on digit-group boundaries,
    longest first (so "4111 1111 1111 1111 10" still yields the 16-digit PAN)."""
    groups = [(g.start(), g.end()) for g in re.finditer(r"\d+", candidate)]
    for i, (start, _) in enumerate(groups):
        spans = [(start, end) for _, end in groups[i:]]
        for span in reversed(spans):
            digits = _digits(candidate[span[0] : span[1]])
            if 13 <= len(digits) <= 19 and luhn_valid(digits):
                return span
    return None


def redact_pans(candidate: str) -> tuple[str, int]:
    """Redact every PAN inside one candidate digit run."""
    out, found = "", 0
    rest = candidate
    while (span := find_pan_span(rest)) is not None:
        out += rest[: span[0]] + PAN_TOKEN
        rest = rest[span[1] :]
        found += 1
    return out + rest, found


def scrub(text: str) -> ScrubResult:
    """Redact PANs, CVVs, and PII so they never reach the index, logs, or the LLM."""
    count = 0

    def _pan(m: re.Match[str]) -> str:
        nonlocal count
        redacted, found = redact_pans(m.group(0))
        count += found
        return redacted

    def _keep_label(token: str) -> Callable[[re.Match[str]], str]:
        def repl(m: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return f"{m.group(1)}{m.group(2)}{token}"

        return repl

    def _whole(token: str) -> Callable[[re.Match[str]], str]:
        def repl(_: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return token

        return repl

    out = _PAN_CANDIDATE.sub(_pan, text)
    out = _CVV.sub(_keep_label(CVV_TOKEN), out)
    out = _EMAIL.sub(_whole(EMAIL_TOKEN), out)
    out = _PHONE.sub(_whole(PHONE_TOKEN), out)
    out = _ACCOUNT.sub(_keep_label(ACCOUNT_TOKEN), out)
    out = _NAME.sub(_keep_label(NAME_TOKEN), out)
    return ScrubResult(clean_text=out, redaction_count=count)
