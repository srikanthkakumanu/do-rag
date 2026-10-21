---
paths:
  - "advanced/src/advanced/ingestion/**"
  - "advanced/src/advanced/retrieval/**"
  - "advanced/migrations/**"
---
# Weaviate conventions (advanced/)

Schema and chunk sizes live in `advanced/docs/architecture.md`. Read it before changing either.

## Two collections
- `PolicyChunk`: **children** (about 220 tokens), vectorized and hybrid-searched. Each carries `parent_id`.
- `PolicySection`: **parents** (whole heading sections), self-provided vectors that are never searched, fetched by ID only.
- IMPORTANT: Search children, send parents. Never search `PolicySection`, and never send child windows to the answerer.

## Client
- Use only the **v4 client** collections API (`client.collections.use(name)`); never v3 patterns.
- Connect only through `advanced/vectordb.py` (`connect_sync` for ingestion, `make_async` for the API). Local ports are 8081 (HTTP) and 50052 (gRPC), so it runs beside `basic/`.
- For writes, use typed handles: `data_model_properties=PolicyChunkProps` / `PolicySectionProps`.

## Querying
- One hybrid query per sub-query, run concurrently with `asyncio.gather`. Limit, alpha, and `max_vector_distance` come from `Settings`.
- Always use `build_filters` (`effective_date <= as_of < superseded_on`, plus network + `all`). Reason codes match through BM25.
- Fuse with `rrf_parents` (one vote per parent per list), apply the `max_sections_per_doc` cap, then fetch parents with `Filter.by_id().contains_any(ids)`, keeping the fused order.

## Writing
- Deterministic IDs: parents `uuid5(doc:version:s{n})`, children `uuid5(doc:version:c{n})`.
- Write parents before children. The child `content_hash` includes `parent_id`, so a re-split section re-links its children.
- Supersession lives on children only. A parent is reached only through its own version's children.
- Batch with `fixed_size(100)` and fail the run on any `failed_objects`. DATE values cap at year 2262, so use `NOT_SUPERSEDED` (2199-12-31).

## Schema
- Change it only through `advanced/migrations/NNNN_<name>.py` (idempotent).
- Changing the embedding model or vectorized properties needs a new collection and a full re-index.
