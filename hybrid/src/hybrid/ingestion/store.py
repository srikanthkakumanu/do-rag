"""Weaviate write side for ingestion (sync v4 client; ingestion is an offline batch job)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, TypedDict

from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from hybrid.domain import Chunk, ChunkId
from hybrid.errors import IngestionError
from hybrid.vectordb import Embedder, as_date, to_datetime


class PolicyChunkProps(TypedDict):
    content: str
    doc_title: str
    doc_id: str
    version: str
    section_path: str
    chunk_index: int
    source_type: str
    card_network: str
    reason_codes: list[str]
    jurisdiction: str
    effective_date: datetime
    superseded_on: datetime
    content_hash: str


@dataclass(frozen=True, slots=True)
class StoredChunk:
    chunk_id: ChunkId
    version: str
    effective_date: date
    superseded_on: date
    content_hash: str


class ChunkStore(Protocol):
    def existing(self, doc_id: str) -> dict[ChunkId, StoredChunk]: ...
    def upsert(self, chunks: Sequence[Chunk], superseded_on: date) -> None: ...
    def set_superseded(self, ids: Sequence[ChunkId], superseded_on: date) -> None: ...
    def delete(self, ids: Sequence[ChunkId]) -> None: ...


def to_props(c: Chunk, superseded_on: date) -> PolicyChunkProps:
    return PolicyChunkProps(
        content=c.content,
        doc_title=c.doc_title,
        doc_id=c.doc_id,
        version=c.version,
        section_path=c.section_path,
        chunk_index=c.chunk_index,
        source_type=c.source_type.value,
        card_network=c.card_network.value,
        reason_codes=list(c.reason_codes),
        jurisdiction=c.jurisdiction,
        effective_date=to_datetime(c.effective_date),
        superseded_on=to_datetime(superseded_on),
        content_hash=c.content_hash,
    )


class WeaviateChunkStore:
    """`ChunkStore` backed by a sync Weaviate client. `embed` is set only when the
    collection uses self-provided vectors (tests); production vectorizes server-side."""

    def __init__(
        self, client: WeaviateClient, collection: str, embed: Embedder | None = None
    ) -> None:
        self._collection = client.collections.use(
            collection, data_model_properties=PolicyChunkProps
        )
        self._untyped = client.collections.use(collection)  # partial updates
        self._embed = embed

    def existing(self, doc_id: str) -> dict[ChunkId, StoredChunk]:
        res = self._collection.query.fetch_objects(
            filters=Filter.by_property("doc_id").equal(doc_id),
            limit=10_000,
            return_properties=["version", "effective_date", "superseded_on", "content_hash"],
        )
        out: dict[ChunkId, StoredChunk] = {}
        for obj in res.objects:
            p = obj.properties
            cid = ChunkId(str(obj.uuid))
            out[cid] = StoredChunk(
                chunk_id=cid,
                version=str(p["version"]),
                effective_date=as_date(p["effective_date"]),
                superseded_on=as_date(p["superseded_on"]),
                content_hash=str(p["content_hash"]),
            )
        return out

    def upsert(self, chunks: Sequence[Chunk], superseded_on: date) -> None:
        with self._collection.batch.fixed_size(batch_size=100) as batch:
            for c in chunks:
                batch.add_object(
                    properties=to_props(c, superseded_on),
                    uuid=c.chunk_id,
                    vector=self._embed(c.content) if self._embed else None,
                )
        failed = self._collection.batch.failed_objects
        if failed:
            raise IngestionError(f"{len(failed)} objects failed: {failed[0].message}")

    def set_superseded(self, ids: Sequence[ChunkId], superseded_on: date) -> None:
        for cid in ids:
            self._untyped.data.update(
                uuid=cid, properties={"superseded_on": to_datetime(superseded_on)}
            )

    def delete(self, ids: Sequence[ChunkId]) -> None:
        for cid in ids:
            self._collection.data.delete_by_id(cid)
