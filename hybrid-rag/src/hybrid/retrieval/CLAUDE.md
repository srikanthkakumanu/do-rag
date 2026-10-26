# retrieval/

## Purpose
The vector half of hybrid: return the top-k current policy chunks for the scrubbed question from Weaviate. Same contract as `basic-rag/`; graph lookups live in `graph/`.

## Owns
- `retriever.py`: `RetrievalQuery`, the `Retriever` protocol, `WeaviateRetriever` (async hybrid BM25 + vector).
- `filters.py`: `build_filters(card_network, as_of)`.
- Client lifecycle: `hybrid/vectordb.py` (`make_async`), opened and closed by the FastAPI lifespan.

## Interface
```python
class Retriever(Protocol):
    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]: ...

class RetrievalQuery(BaseModel):
    text: str
    card_network: CardNetwork | None = None
    as_of: date = Field(default_factory=date.today)
```

## Invariants
- Runs **concurrently** with the graph plan (`asyncio.gather` in `rag.py`), so it uses only the request's `card_network`, never the planner's.
- Always filters `effective_date <= as_of < superseded_on`, plus network and `all` when set.
- Results are sorted by score, capped at `top_k`, unique `chunk_id`, and thresholded by `min_score` / `max_vector_distance`.
- `[]` on no match. `RetrievalError` only on infrastructure failure.

## Don't
- Don't add query rewriting, reranking, or multi-query here (that's `advanced-rag/`).
- Don't merge graph facts in this module; fusion happens in the prompt (`generation/assembler.py`).
- Don't leak Weaviate SDK types.

## Test
- Unit: filter building.
- Integration: exact code `4853` ranks first; chunk and graph share `chunk_id`s and dates.
- Tune `alpha`, `top_k`, and thresholds only with the eval gate (run twice).
