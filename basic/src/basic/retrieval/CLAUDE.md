# retrieval/

## Purpose
Given a scrubbed question and optional filters, return the top-k relevant, current policy chunks with scores. Retrieval only; no generation.

## Owns
- `client.py`: Weaviate client lifecycle (async; opened and closed in the FastAPI lifespan).
- `retriever.py`: the `WeaviateRetriever`, which implements the `Retriever` protocol.
- `filters.py`: builds `Filter` objects from the `RetrievalQuery` fields.

## Interface
```python
class Retriever(Protocol):
    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]: ...

class RetrievalQuery(BaseModel):
    text: str
    card_network: CardNetwork | None = None
    as_of: date = Field(default_factory=date.today)

@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: ChunkId; doc_id: DocId; section_path: str
    effective_date: date; content: str; score: float
```

## Invariants
- Always applies `effective_date <= as_of`. When a `doc_id` has several versions, only the latest one effective as of that date is returned.
- When `card_network` is set, the filter also includes `card_network == "all"` (rules shared across networks).
- Results are sorted by score descending, length ≤ `top_k`, with no duplicate `chunk_id`.
- Returns `[]` when there are no matches. Raises `RetrievalError` only on infrastructure failure. The caller decides whether to refuse.
- `alpha`, `top_k`, and `min_score` come from `Settings`. Thresholding happens here, so callers get only chunks that pass it.

## Don't
- Don't rewrite or expand queries, rerank, or make multiple retrieval passes (that's `advanced/`).
- Don't return Weaviate SDK types beyond this module; map them to `RetrievedChunk`.
- Don't catch and hide connection errors. Fail fast with context.

## Test
- Unit: filter building for each combination of `card_network` and `as_of`.
- Integration (testcontainers, fixed vectors): an exact reason code (`10.4`) ranks first under BM25-heavy alpha; superseded versions are excluded; an empty corpus returns `[]`.
- Tune `min_score` and `alpha` with the eval gate only, never by eye.
