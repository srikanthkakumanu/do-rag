from __future__ import annotations

import pytest

from hybrid.ingestion.scrub import (
    ACCOUNT_TOKEN,
    CVV_TOKEN,
    EMAIL_TOKEN,
    NAME_TOKEN,
    PAN_TOKEN,
    PHONE_TOKEN,
    luhn_valid,
    scrub,
)


@pytest.mark.parametrize(
    "pan", ["4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111", "378282246310005"]
)
def test_scrub_luhn_valid_pan_redacted(pan: str) -> None:
    result = scrub(f"card {pan} was used")
    assert result.clean_text == f"card {PAN_TOKEN} was used"
    assert result.redaction_count == 1


def test_scrub_non_luhn_number_kept() -> None:
    text = "order 4111111111111112 and case 1234567890123"
    assert scrub(text).clean_text == text


def test_scrub_reason_codes_and_dates_kept() -> None:
    text = "Visa 10.4 and Mastercard 4853, effective 2026-01-01, respond in 30 days."
    result = scrub(text)
    assert result.clean_text == text
    assert result.redaction_count == 0


def test_scrub_cvv_next_to_label_redacted() -> None:
    assert scrub("CVV2: 123").clean_text == f"CVV2: {CVV_TOKEN}"


def test_scrub_pii_redacted() -> None:
    text = (
        "Contact jane.doe@example.com or (415) 555-0100. "
        "Account number: 12345678. Cardholder name: John Smith."
    )
    out = scrub(text).clean_text
    for token in (EMAIL_TOKEN, PHONE_TOKEN, ACCOUNT_TOKEN, NAME_TOKEN):
        assert token in out
    assert "John Smith" not in out
    assert "12345678" not in out


def test_scrub_account_word_without_digits_kept() -> None:
    text = "Check the account holder status."
    assert scrub(text).clean_text == text


def test_luhn_valid_known_values() -> None:
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


def test_scrub_pan_followed_by_digits_still_redacted() -> None:
    # Regression: a greedy 18-digit run ("... 1111 10") failed Luhn and leaked the PAN.
    out = scrub("card 4111 1111 1111 1111 10.4?").clean_text
    assert out == f"card {PAN_TOKEN} 10.4?"
