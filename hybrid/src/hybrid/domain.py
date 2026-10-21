"""Domain types shared across modules: IDs, closed sets, and value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final, NewType

from pydantic import BaseModel, Field

DocId = NewType("DocId", str)
ChunkId = NewType("ChunkId", str)
QueryId = NewType("QueryId", str)

REFUSAL_TEXT: Final = "I can't find this in the approved dispute policy sources."
VERIFY_NOTICE: Final = (
    "Decision support only. Verify against the cited source before acting on a dispute."
)
# Far-future sentinel; Weaviate DATE is int64 nanoseconds (max year 2262), so not 9999.
NOT_SUPERSEDED: Final = date(2199, 12, 31)


class CardNetwork(StrEnum):
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    DISCOVER = "discover"
    ALL = "all"


class SourceType(StrEnum):
    NETWORK_RULE = "network_rule"
    INTERNAL_SOP = "internal_sop"
    PLAYBOOK = "playbook"


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A loaded, normalized (but not yet scrubbed) policy document."""

    doc_id: DocId
    doc_title: str
    version: str
    effective_date: date
    source_type: SourceType
    card_network: CardNetwork
    jurisdiction: str
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    """A scrubbed, heading-aware slice of a document, ready to index."""

    chunk_id: ChunkId
    doc_id: DocId
    doc_title: str
    version: str
    section_path: str
    chunk_index: int
    source_type: SourceType
    card_network: CardNetwork
    reason_codes: tuple[str, ...]
    jurisdiction: str
    effective_date: date
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: ChunkId
    doc_id: DocId
    section_path: str
    effective_date: date
    content: str
    score: float


class FactKind(StrEnum):
    """Relationship types from a ReasonCode (closed set; see docs/architecture.md)."""

    DEADLINE = "HAS_DEADLINE"
    REMEDY = "REMEDIED_BY"
    INSUFFICIENT = "NOT_SUFFICIENT"
    CATEGORY = "IN_CATEGORY"


class Category(StrEnum):
    FRAUD = "fraud"
    AUTHORIZATION = "authorization"
    PROCESSING_ERROR = "processing_error"
    CONSUMER_DISPUTE = "consumer_dispute"


class Party(StrEnum):
    MERCHANT = "merchant"
    CARDHOLDER = "cardholder"
    ISSUER = "issuer"


@dataclass(frozen=True, slots=True)
class GraphFact:
    """One current fact from the knowledge graph, with provenance for citation."""

    statement: (
        str  # deterministic rendering, e.g. "Visa 10.4: merchant must respond within 30 days"
    )
    quote: str  # verbatim supporting span from the source chunk
    network: str
    code: str
    kind: FactKind
    doc_id: DocId
    section_path: str
    effective_date: date


class Citation(BaseModel):
    doc_id: str
    section_path: str
    effective_date: date


class GroundedAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    refused: bool
    prompt_version: str
    model: str
