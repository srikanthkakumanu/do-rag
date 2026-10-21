# retrieval/

## Purpose
Search child chunks, fuse results across sub-queries into parent sections, and rerank them. It returns graded parent sections; it never generates answers.

## Owns
- `retriever.py`: `RetrievalQuery`, the `Retriever` protocol and `WeaviateRetriever` (child hybrid search), and the `SectionStore` protocol and `WeaviateSectionStore` (parent fetch by ID, order kept).
- `filters.py`: `build_filters(card_network, as_of)`.
- `fusion.py`: `rrf_parents(lists, k)`, one vote per parent per list.
- `reranker.py` + `prompts/rerank_v1.md`: the `Reranker` protocol and `LLMReranker` (0–3 grades, short `S{n}` IDs, 250-token excerpts).
- Orchestration (gather, per-doc cap, corrective gate) lives in `src/advanced/rag.py`.

## Interface
```python
class Retriever(Protocol):
    async def search(self, q: RetrievalQuery) -> list[RetrievedChunk]: ...     # children
class SectionStore(Protocol):
    async def fetch(self, ids: list[SectionId]) -> list[RetrievedSection]: ... # parents
class Reranker(Protocol):
    async def rerank(self, question: str, sections: list[RetrievedSection]) -> list[RetrievedSection]: ...
```

## Invariants
- Child search always filters `effective_date <= as_of < superseded_on`, plus network and `all` when set.
- `RetrievedChunk` carries only IDs and score. Text comes from the parent, so the LLM always sees whole sections.
- RRF score = Σ 1/(k + rank) over lists. Ties keep a stable order.
- The reranker returns every input section, sorted by grade. Missing or unknown IDs grade 0. On failure, all get `min_rerank_score` in fused order.
- Infrastructure errors raise `RetrievalError`. An empty result is `[]`, and the caller refuses.

## Don't
- Don't search `PolicySection`, or return Weaviate SDK types beyond this module.
- Don't let the reranker rewrite text or add sections.
- Don't tune `alpha`, limits, caps, or thresholds by eye; use the eval gate.

## Test
- Unit: RRF voting, grade mapping and defaults, excerpt and escaping, reranker degradation.
- Integration: child hit resolves to its full parent; network filter; supersession; multi-query comparison finds both docs; empty collection.
