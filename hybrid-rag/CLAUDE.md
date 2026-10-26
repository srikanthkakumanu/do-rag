# hybrid-rag/: Hybrid RAG (vector + knowledge graph), Dispute & Chargeback Policy Assistant

## Mission
Same users, corpus, and grounding contract as `basic-rag/`: **cited or refused**. Vector search finds prose; a **knowledge graph** answers aggregate questions top-k misses ("Which codes give merchants 45 days?").

Independent project: its own `pyproject.toml`, `.env`, Weaviate (8082/50053), Neo4j (7475/7688), and corpus copy. Never import from `basic-rag/` or `advanced-rag/`.

## Pipeline (`src/hybrid/rag.py`)
1. In parallel: **graph plan** (LLM, guarded: codes, networks, fact kinds, days, category) and **vector search** (Weaviate hybrid, like basic). A plan with no graph signal skips the graph; it never refuses.
2. **Graph retrieval** (`graph/`): fixed, parameterized, read-only Cypher templates selected by the plan. Each fact keeps provenance (doc, section, quote).
3. **Fuse**: `<graph_fact>` items and `<source>` chunks go into one prompt, and the answer cites `[doc_id §section_path]` for both.
4. **Validate**: citations match sent items, and numbers appear in cited text; otherwise `REFUSAL_TEXT`.

Ingestion: an LLM **extracts facts** from chunks with reason codes; a fact is kept only if its quote is verbatim in the chunk. Graph is written before Weaviate.

## Stack
| Concern | Choice |
|---|---|
| Runtime | Python 3.12, `uv`, FastAPI, Pydantic v2 |
| Vector DB | Weaviate 1.38, v4 client, `PolicyChunk` (hybrid search) |
| Graph DB | Neo4j 5.26 Community, official `neo4j` driver (async for the API) |
| LLMs | OpenAI Responses API: `gpt-5.4-nano` extraction and graph plan, `gpt-5.4-mini` answer (only `OPENAI_API_KEY` required) |
| Quality | pytest, testcontainers (Weaviate + Neo4j), ruff, mypy `--strict` |

## Commands (run from `hybrid-rag/`)
```bash
uv sync && docker compose up -d --wait
uv run python -m migrations.apply            # Weaviate schema + Neo4j constraints
uv run hybrid ingest data/corpus             # chunks + facts (--reextract after prompt changes)
uv run uvicorn hybrid.api.app:app --port 8002
uv run pytest -m "not integration"           # and: -m integration
uv run ruff check . && uv run mypy src migrations eval tests
uv run python -m eval.run --report eval/reports/<date>.json
```

## Non-negotiables
1. Cite or refuse. Graph facts are cited through their source section.
2. IMPORTANT: Never execute LLM-generated Cypher. Only templates in `graph/queries.py`, with parameters.
3. Never store an extracted fact without a verbatim quote from its chunk.
4. Graph and vector stores share chunk IDs and supersession dates. They change together or not at all.
5. Changes to extraction, retrieval, prompts, or models pass the eval gate twice (including `coverage` ≥ 0.80 on multi-doc questions).

## Where to look
- Ontology, schema, NFRs: `docs/architecture.md` (on demand)
- Module contracts: `src/hybrid/{ingestion,graph,retrieval,generation}/CLAUDE.md`
- Rules: shared `python.md` and `testing-eval.md`, plus `hybrid-*.md`
