"""HTTP request/response models for `POST /v1/ask`."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from hybrid.domain import VERIFY_NOTICE, CardNetwork, Citation


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    card_network: CardNetwork | None = None
    as_of: date | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    refused: bool
    query_id: str
    prompt_version: str
    graph_facts_used: int
    notice: str = VERIFY_NOTICE
