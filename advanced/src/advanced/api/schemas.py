"""HTTP request/response models for `POST /v1/ask`."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from advanced.domain import VERIFY_NOTICE, CardNetwork, Citation, Turn


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    card_network: CardNetwork | None = None
    as_of: date | None = None
    history: list[Turn] = Field(default_factory=list, max_length=20)


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    refused: bool
    query_id: str
    prompt_version: str
    standalone_question: str
    notice: str = VERIFY_NOTICE
