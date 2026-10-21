"""Hybrid (BM25 + vector) search over child chunks, plus parent-section fetch by ID."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from opentelemetry import trace
from pydantic import BaseModel, Field
from weaviate import WeaviateAsyncClient
from weaviate.classes.query import Filter, MetadataQuery
from weaviate.exceptions import WeaviateBaseError

from advanced.config import Settings
from advanced.domain import (
    CardNetwork,
    ChunkId,
    DocId,
    RetrievedChunk,
    RetrievedSection,
    SectionId,
)
from advanced.errors import RetrievalError
from advanced.retrieval.filters import build_filters
from advanced.vectordb import Embedder, as_date

_tracer = trace.get_tracer(__name__)


class RetrievalQuery(BaseModel):
    text: str = Field(min_length=1)
    card_network: CardNetwork | None = None
    as_of: date = Field(default_factory=date.today)


class Retriever(Protocol):
    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]: ...


class SectionStore(Protocol):
    async def fetch(self, ids: list[SectionId]) -> list[RetrievedSection]: ...


class WeaviateRetriever:
    """Child-chunk search. `embed` is only for self-provided-vector collections (tests)."""

    def __init__(
        self, client: WeaviateAsyncClient, settings: Settings, embed: Embedder | None = None
    ) -> None:
        self._client = client
        self._settings = settings
        self._embed = embed

    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]:
        s = self._settings
        with _tracer.start_as_current_span("retrieval.hybrid"):
            try:
                res = await self._client.collections.use(s.collection_name).query.hybrid(
                    query=q.text,
                    vector=self._embed(q.text) if self._embed else None,
                    alpha=s.hybrid_alpha,
                    limit=s.per_query_limit,
                    max_vector_distance=s.max_vector_distance,
                    filters=build_filters(q.card_network, q.as_of),
                    return_metadata=MetadataQuery(score=True),
                    return_properties=["doc_id", "parent_id"],
                )
            except WeaviateBaseError as e:
                raise RetrievalError(f"hybrid query failed: {type(e).__name__}") from e
        hits: dict[ChunkId, RetrievedChunk] = {}
        for obj in res.objects:
            score = obj.metadata.score or 0.0
            if score < s.min_score:
                continue
            cid = ChunkId(str(obj.uuid))
            hits.setdefault(
                cid,
                RetrievedChunk(
                    chunk_id=cid,
                    parent_id=SectionId(str(obj.properties["parent_id"])),
                    doc_id=DocId(str(obj.properties["doc_id"])),
                    score=score,
                ),
            )
        return sorted(hits.values(), key=lambda c: c.score, reverse=True)


class WeaviateSectionStore:
    """Fetch parent sections by ID, preserving the requested order."""

    def __init__(self, client: WeaviateAsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def fetch(self, ids: list[SectionId]) -> list[RetrievedSection]:
        if not ids:
            return []
        try:
            res = await self._client.collections.use(
                self._settings.section_collection
            ).query.fetch_objects(
                filters=Filter.by_id().contains_any(list(ids)),
                limit=len(ids),
                return_properties=["doc_id", "section_path", "effective_date", "content"],
            )
        except WeaviateBaseError as e:
            raise RetrievalError(f"section fetch failed: {type(e).__name__}") from e
        by_id = {
            SectionId(str(o.uuid)): RetrievedSection(
                section_id=SectionId(str(o.uuid)),
                doc_id=DocId(str(o.properties["doc_id"])),
                section_path=str(o.properties["section_path"]),
                effective_date=as_date(o.properties["effective_date"]),
                content=str(o.properties["content"]),
                score=0.0,
            )
            for o in res.objects
        }
        return [by_id[i] for i in ids if i in by_id]
