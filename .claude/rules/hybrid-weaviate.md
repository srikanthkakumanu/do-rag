---
paths:
  - "hybrid-rag/src/hybrid/ingestion/**"
  - "hybrid-rag/src/hybrid/retrieval/**"
  - "hybrid-rag/src/hybrid/vectordb.py"
  - "hybrid-rag/migrations/**"
---
# Weaviate conventions (hybrid-rag/)

The vector side matches `basic-rag/`. Schema details live in `hybrid-rag/docs/architecture.md`.

## Client
- IMPORTANT: Use only the **v4 client** collections API (`client.collections.use(name)`); never v3 patterns (`client.query.get`, `weaviate.Client`).
- Connect only through `hybrid/vectordb.py`: `connect_sync` for ingestion and migrations, `make_async` for the API. Local ports are 8082 (HTTP) and 50053 (gRPC). It passes the OpenAI key as `X-OpenAI-Api-Key`.
- Close clients with context managers or the app lifespan. For writes, use typed handles (`data_model_properties=PolicyChunkProps`).

## Querying
- One `hybrid` query on the raw (scrubbed) question, run **concurrently** with the graph plan. `alpha`, `top_k`, `min_score`, and `max_vector_distance` come from `Settings`.
- Always use `build_filters` (`effective_date <= as_of < superseded_on`, plus network + `all` when the request sets a network). Reason codes match through BM25 (field tokenization).
- Map results to `RetrievedChunk` inside `retrieval/`; never leak SDK types.

## Writing
- Deterministic IDs: `generate_uuid5(f"{doc_id}:{version}:{chunk_index}")`. The same `chunk_id` keys the graph facts.
- Batch with `fixed_size(100)` and fail the run on any `failed_objects`. Skip unchanged chunks by `content_hash`.
- Keep old versions and set `superseded_on` on them. Use `NOT_SUPERSEDED` = 2199-12-31 (DATE caps at year 2262).
- The pipeline reports which chunks were written, re-superseded, or deleted, so `graph_store` applies the same changes.

## Schema
- Change it only through `hybrid-rag/migrations/NNNN_<name>.py` (idempotent). The same runner creates the Neo4j constraints.
- `text2vec-openai` on `content` and `doc_title`. Changing the embedding model needs a new collection and a full re-index.
