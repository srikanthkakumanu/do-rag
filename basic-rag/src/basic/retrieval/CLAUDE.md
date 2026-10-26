# retrieval/

## Purpose
Given a scrubbed question and optional filters, return the top-k relevant, current policy chunks with scores. Retrieval only; no generation.

## Owns
- `retriever.py`: `RetrievalQuery`, the `Retriever` protocol, and `WeaviateRetriever` (async client).
- `filters.py`: builds `Filter` objects from the query fields.
- Client lifecycle lives in `basic/vectordb.py` (`make_async`), opened and closed by the FastAPI lifespan.

## Interface
```python
class Retriever(Protocol):
    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]: ...

class RetrievalQuery(BaseModel):
    text: str
    card_network: CardNetwork | None = None
    as_of: date = Field(default_factory=date.today)
```
`RetrievedChunk` (`basic/domain.py`) carries chunk_id, doc_id, section_path, effective_date, content, and score.

## Invariants
- Always filters `effective_date <= as_of < superseded_on`, so exactly one version per `doc_id` is current for any date.
- When `card_network` is set, the filter also includes `card_network == "all"` (rules shared across networks).
- Results are sorted by score descending, length ≤ `top_k`, with no duplicate `chunk_id`.
- Returns `[]` when there are no matches. Raises `RetrievalError` only on infrastructure failure. The caller decides whether to refuse.
- `alpha`, `top_k`, `min_score`, and `max_vector_distance` come from `Settings`. Thresholding happens here.

## Don't
- Don't rewrite or expand queries, rerank, or make multiple retrieval passes (that's `advanced/`).
- Don't return Weaviate SDK types beyond this module; map them to `RetrievedChunk`.
- Don't catch and hide connection errors. Fail fast with context.

## Test
- Unit: filter building for each combination of `card_network` and `as_of`.
- Integration (testcontainers, `fake_embed` vectors): an exact code (`4853`) ranks first at alpha 0.2; superseded versions are excluded; the network filter holds; an empty collection returns `[]`.
- Tune `min_score`, `max_vector_distance`, and `alpha` with the eval gate only, never by eye.
