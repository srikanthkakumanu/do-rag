---
paths:
  - "basic-rag/src/basic/ingestion/**"
  - "basic-rag/src/basic/retrieval/**"
  - "basic-rag/migrations/**"
---
# Weaviate conventions (basic-rag/)

The schema and chunking design live in `basic-rag/docs/architecture.md`. Read it before changing either.

## Client
- IMPORTANT: Use only the **v4 Python client** collections API. Never use v3 patterns (`client.query.get`, `client.schema`, `weaviate.Client(...)`).
- Connect only through `basic/vectordb.py` (`connect_sync` for batch jobs, `make_async` for the API). It passes the OpenAI key as the `X-OpenAI-Api-Key` header.
- Always close the client: use a context manager in scripts and the app lifespan in FastAPI.
- Get handles with `client.collections.use(name)` (`.get` is deprecated). For writes, pass `data_model_properties=PolicyChunkProps`.

## Querying
```python
res = await chunks.query.hybrid(
    query=q, alpha=settings.hybrid_alpha, limit=settings.top_k,
    vector=None,  # Weaviate vectorizes; tests pass fake_embed(q)
    max_vector_distance=settings.max_vector_distance,
    filters=build_filters(card_network, as_of),
    return_metadata=MetadataQuery(score=True),
)
```
- Always use `build_filters` (`effective_date <= as_of < superseded_on`, plus network + `all`). Reason codes are matched by BM25, not filters.
- Read `alpha` and `limit` from config. Never inline magic numbers.

## Writing
- Use deterministic IDs: `generate_uuid5(f"{doc_id}:{version}:{chunk_index}")`. Re-ingesting the same input must be a no-op.
- Write with `collection.batch.fixed_size(batch_size=100)`. After the batch, check `collection.batch.failed_objects`, and fail the run if it's non-empty.
- Skip unchanged chunks by comparing `content_hash`. Keep old versions; set their `superseded_on` to the next version's `effective_date`. Delete only stale chunk indices of the same version.
- DATE values are int64 nanoseconds (max year 2262). Use `NOT_SUPERSEDED` (2199-12-31), never 9999.

## Schema
- Schema changes go only through versioned scripts in `basic-rag/migrations/NNNN_<name>.py`. Never create collections ad hoc in app code.
- The vectorizer is `text2vec-openai`, and its model comes from `OPENAI_EMBED_MODEL`. Changing the model, dimensions, or vectorized properties requires a new collection and a full re-index. Never mutate it in place.
- Only `content` and `doc_title` are vectorized (`source_properties`). Tests use `Configure.Vectors.self_provided()` (`WEAVIATE_VECTORIZER=none`).
- Keep keyword tokenization on `reason_codes` and `doc_id`, so BM25 matches exact codes like `10.4` and `4853`.
