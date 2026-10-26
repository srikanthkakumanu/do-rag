"""Hybrid (BM25 + vector) retrieval over `PolicyChunk`."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from opentelemetry import trace
from pydantic import BaseModel, Field
from weaviate import WeaviateAsyncClient
from weaviate.classes.query import MetadataQuery
from weaviate.exceptions import WeaviateBaseError

from basic.config import Settings
from basic.domain import CardNetwork, ChunkId, DocId, RetrievedChunk
from basic.errors import RetrievalError
from basic.retrieval.filters import build_filters
from basic.vectordb import Embedder, as_date

_tracer = trace.get_tracer(__name__)


class RetrievalQuery(BaseModel):
    text: str = Field(min_length=1)
    card_network: CardNetwork | None = None
    as_of: date = Field(default_factory=date.today)


class Retriever(Protocol):
    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]: ...


class WeaviateRetriever:
    """`Retriever` over an async Weaviate client. `embed` is only for self-provided
    vector collections (tests); in production Weaviate vectorizes the query."""

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
                collection = self._client.collections.use(s.collection_name)
                res = await collection.query.hybrid(
                    query=q.text,
                    vector=self._embed(q.text) if self._embed else None,
                    alpha=s.hybrid_alpha,
                    limit=s.top_k,
                    max_vector_distance=s.max_vector_distance,
                    filters=build_filters(q.card_network, q.as_of),
                    return_metadata=MetadataQuery(score=True),
                    return_properties=["doc_id", "section_path", "effective_date", "content"],
                )
            except WeaviateBaseError as e:
                raise RetrievalError(f"hybrid query failed: {type(e).__name__}") from e

        chunks: dict[ChunkId, RetrievedChunk] = {}
        for obj in res.objects:
            score = obj.metadata.score or 0.0
            if score < s.min_score:
                continue
            p = obj.properties
            cid = ChunkId(str(obj.uuid))
            chunks.setdefault(
                cid,
                RetrievedChunk(
                    chunk_id=cid,
                    doc_id=DocId(str(p["doc_id"])),
                    section_path=str(p["section_path"]),
                    effective_date=as_date(p["effective_date"]),
                    content=str(p["content"]),
                    score=score,
                ),
            )
        return sorted(chunks.values(), key=lambda c: c.score, reverse=True)[: s.top_k]
