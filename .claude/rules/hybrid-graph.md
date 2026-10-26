---
paths:
  - "hybrid-rag/src/hybrid/graph/**"
  - "hybrid-rag/src/hybrid/graphdb.py"
  - "hybrid-rag/src/hybrid/ingestion/extract.py"
  - "hybrid-rag/src/hybrid/ingestion/graph_store.py"
  - "hybrid-rag/migrations/**"
---
# Knowledge graph conventions (hybrid-rag/, Neo4j)

Ontology and templates live in `hybrid-rag/docs/architecture.md`. Read it before changing labels, relationships, or queries.

## Driver
- Use the official `neo4j` driver only, through `hybrid/graphdb.py`: a sync driver for ingestion and migrations, `AsyncDriver` for the API. Create it once and close it at shutdown.
- Local ports are 7475 (HTTP) and 7688 (Bolt). Auth comes from `NEO4J_USER`/`NEO4J_PASSWORD` (`SecretStr`); empty means no auth (local dev only).
- Use `session.execute_read` for queries and `execute_write` for ingestion, with an explicit `database_` and timeouts.

## Cypher
- IMPORTANT: Never build Cypher from strings or LLM output. Every query is a named constant in `graph/queries.py` (reads) or `ingestion/graph_store.py` (writes), and values pass only as `$parameters`.
- Read templates are `MATCH`-only and always filter `r.effective_date <= $as_of AND r.superseded_on > $as_of`, with `LIMIT $limit`.
- Labels and relationship types are a closed set (`Network`, `ReasonCode`, `Deadline`, `Evidence`, `Category`; `DEFINES`, `HAS_DEADLINE`, `REMEDIED_BY`, `NOT_SUFFICIENT`, `IN_CATEGORY`). Adding one needs a migration and a docs update.
- Use `MERGE` on unique keys only (constraints are created in `migrations/`). Store dates as Neo4j `date` values.

## Facts and provenance
- Every fact edge stores `chunk_id`, `doc_id`, `version`, `section_path`, `quote`, `effective_date`, and `superseded_on`, matching the Weaviate chunk exactly.
- Writes are per chunk: delete that chunk's fact edges, then create the new ones in the same transaction. Re-ingesting an unchanged chunk skips extraction entirely.
- When a version is superseded, update `superseded_on` on its edges in the same run as Weaviate. Stale chunks delete their edges.
- Orphan target nodes (`Evidence`, `Deadline`) may remain; queries reach them only through current edges.

## Extraction guard (`ingestion/extract.py`)
- The LLM proposes facts; code decides. Keep a fact only if: its `reason_code` is in the chunk's codes, its `quote` is a verbatim (whitespace-normalized) substring of the chunk, deadline `days` are digits that appear in the quote, and `kind`/`party`/`category` are enum values.
- Evidence names are normalized (lowercase, trimmed, ≤ 80 chars). Dropped facts are counted in `IngestReport.facts_rejected`.
- Chunks without reason codes are never sent for extraction.
