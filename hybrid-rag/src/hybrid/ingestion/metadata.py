"""Reason-code extraction per card network. Drives BM25 matching and audit metadata."""

from __future__ import annotations

import re
from typing import Final

from hybrid.domain import CardNetwork

_PATTERNS: Final[dict[CardNetwork, re.Pattern[str]]] = {
    # Visa: 10.1-10.5 fraud, 11.x authorization, 12.x processing, 13.x consumer.
    CardNetwork.VISA: re.compile(r"(?<![\d.])1[0-3]\.\d{1,2}(?![\d.])"),
    # Mastercard: four-digit 48xx codes (e.g., 4837, 4853).
    CardNetwork.MASTERCARD: re.compile(r"(?<!\d)48\d{2}(?!\d)"),
    # Amex: letter + two digits (e.g., C08, F29, A01, P01, R13, M10).
    CardNetwork.AMEX: re.compile(r"\b[ACFMPR]\d{2}\b"),
    # Discover: UA01/UA02/UA05... plus common two-letter codes.
    CardNetwork.DISCOVER: re.compile(r"\b(?:UA\d{2}|AA|AP|AW|CD|DP|NC|RG|RM)\b"),
}


def extract_reason_codes(text: str, network: CardNetwork) -> tuple[str, ...]:
    """Return sorted unique reason codes for `network` (all networks when `ALL`)."""
    networks = list(_PATTERNS) if network is CardNetwork.ALL else [network]
    codes = {m.group(0) for n in networks for m in _PATTERNS[n].finditer(text)}
    return tuple(sorted(codes))
