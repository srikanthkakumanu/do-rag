---
paths:
  - "basic/src/basic/ingestion/**"
  - "basic/src/basic/retrieval/**"
  - "basic/migrations/**"
---
# Weaviate conventions (basic/)

The schema and chunking design live in `basic/docs/architecture.md`. Read it before changing either.

## Client
- IMPORTANT: Use only the **v4 Python client** collections API. Never use v3 patterns (`client.query.get`, `client.schema`, `weaviate.Client(...)`).
- Connect with `weaviate.use_async_with_local(...)` or `weaviate.connect_to_custom(...)`, and pass the OpenAI key as a header: `headers={"X-OpenAI-Api-Key": settings.openai_api_key.get_secret_value()}`.
- Always close the client: use a context manager in scripts and the app lifespan in FastAPI.
- Get the collection handle once: `client.collections.get("PolicyChunk")`.

## Querying
```python
res = await chunks.query.hybrid(
    query=q, alpha=settings.hybrid_alpha, limit=settings.top_k,
    filters=Filter.by_property("card_network").equal(net)
        & Filter.by_property("effective_date").less_or_equal(as_of),
    return_metadata=MetadataQuery(score=True),
)
```
- Always filter on `effective_date` so superseded rules are excluded. Add `card_network` and `reason_codes` filters when the query names them.
- Read `alpha` and `limit` from config. Never inline magic numbers.

## Writing
- Use deterministic IDs: `generate_uuid5(f"{doc_id}:{version}:{chunk_index}")`. Re-ingesting the same input must be a no-op.
- Write with `collection.batch.fixed_size(batch_size=100)`. After the batch, check `collection.batch.failed_objects`, and fail the run if it's non-empty.
- Skip unchanged chunks by comparing `content_hash`. When a document gets a new version, delete the old version's chunks with `delete_many` and a filter on `doc_id` + `version`.

## Schema
- Schema changes go only through versioned scripts in `basic/migrations/NNNN_<name>.py`. Never create collections ad hoc in app code.
- The vectorizer is `text2vec-openai`, and its model comes from `OPENAI_EMBED_MODEL`. Changing the model, dimensions, or vectorized properties requires a new collection and a full re-index. Never mutate it in place.
- Only `content` and `doc_title` are vectorized. Metadata uses `skip_vectorization=True`.
- Keep keyword tokenization on `reason_codes` and `doc_id`, so BM25 matches exact codes like `10.4` and `4853`.
