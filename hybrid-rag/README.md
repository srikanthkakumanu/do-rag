# Hybrid RAG: Dispute & Chargeback Policy Assistant (vectors + knowledge graph)

Same use case and grounding contract as [`basic/`](../basic/README.md): **cited answers or a refusal**. It adds a **Neo4j knowledge graph** of reason codes, deadlines, evidence, and categories next to **Weaviate** vector search. That covers what top-k text retrieval structurally can't:

| Question | Vector-only RAG | Hybrid |
|---|---|---|
| "Which reason codes give the merchant 45 days to respond?" | Finds whichever chunks rank highest; may miss one | Graph query returns **every** code with a 45-day deadline |
| "List the fraud reason codes for each network" | Scattered across many documents | One category query across the graph |
| "Which codes accept proof of delivery?" | Depends on wording overlap | Evidence nodes link codes directly |
| "What goes in the evidence cover letter?" | ✓ | ✓ (vector side; graph skipped) |

## How it works
**Ingestion.** Documents are scrubbed (PAN/PII), chunked like basic, and stored in Weaviate. For chunks that mention reason codes, `gpt-5.4-nano` extracts facts (deadline, remedy, insufficient evidence, category). A fact is stored only if its **quote appears verbatim in the chunk**, its day count appears in that quote, and its values are valid enums. Facts carry full provenance (doc, section, quote, version dates), so they are cited just like text. The graph is written before Weaviate, so a failed run retries both stores.

**Query.** A guarded graph planner and the vector search run **in parallel**. The planner's codes, networks, and day counts are kept only if they appear in the question. The plan selects **fixed, read-only Cypher templates**; the LLM never writes Cypher. Graph facts and text chunks go into one prompt, the answer cites both as `[doc_id §section_path]`, and every number must appear in a cited item.

## Stack
Python 3.12, `uv`, FastAPI, Pydantic v2 · Weaviate 1.38 (ports **8082/50053**) · Neo4j 5.26 Community (ports **7475/7688**) · OpenAI Responses API: `gpt-5.4-nano` for extraction and graph planning, `gpt-5.4-mini` for answers · pytest, testcontainers (Weaviate + Neo4j), ruff, mypy `--strict`.

## Quick start
```bash
cd hybrid
cp .env.example .env               # only OPENAI_API_KEY is required
uv sync
docker compose up -d --wait        # Weaviate + Neo4j
uv run python -m migrations.apply  # collection + graph constraints/indexes
uv run hybrid ingest data/corpus   # chunks + graph facts
uv run uvicorn hybrid.api.app:app --port 8002
```
```bash
curl -s localhost:8002/v1/ask -H 'Content-Type: application/json' -H 'X-Auth-Roles: disputes.read' \
  -d '{"question": "Which reason codes give the merchant 45 days to respond?"}'
```
The response adds `graph_facts_used` to basic's fields. To browse the graph, open the Neo4j Browser at http://localhost:7475 and run `MATCH p=(:ReasonCode)-[]->() RETURN p`.

After changing the extraction prompt, run `uv run hybrid ingest data/corpus --reextract`. It rebuilds the graph facts and leaves the Weaviate chunks untouched.

## Tests and quality gate
```bash
uv run pytest -m "not integration"   # 80 unit tests
uv run pytest -m integration         # 7 tests on real Weaviate + Neo4j containers (no OpenAI)
uv run ruff check . && uv run mypy src migrations eval tests
uv run python -m eval.run --report eval/reports/$(date +%F).json
```
The golden set has 58 questions: basic's 50 plus 8 aggregate and graph-style questions. It adds a **coverage** metric: for multi-document questions, the share of expected documents actually cited. Two recent live runs:

| Metric | Result | Gate |
|---|---|---|
| recall@5 | 1.00 | ≥ 0.90 |
| citation accuracy | 0.97–1.00 | ≥ 0.95 |
| refusal precision / recall | 1.00 / 1.00 | ≥ 0.95 |
| coverage (multi-doc questions) | 1.00 | ≥ 0.80 |
| p95 latency | 3.2–3.8 s | < 5 s |

Live ingestion extracted 45 facts. After a prompt fix, the deadlines were all correct (e.g., Visa 10.4 / 13.1 / Discover UA02 at 30 days, Mastercard 4853 / 4837 at 45, Amex C08 / F29 at 20). Known noise: the small extractor labels one Mastercard 4837 restriction as "not sufficient" evidence. The corpus is synthetic and small, so treat the numbers as a smoke test.

## Layout
```
hybrid/
├── CLAUDE.md, docs/architecture.md
├── src/hybrid/
│   ├── rag.py          orchestration: (graph plan ‖ vector search) → facts → answer
│   ├── llm.py          shared StructuredLLM gateway;  graphdb.py / vectordb.py  store drivers
│   ├── graph/          guarded planner, read-only Cypher templates, fact retriever
│   ├── ingestion/      scrub, chunk, LLM fact extraction + guard, Neo4j + Weaviate writers
│   ├── retrieval/      Weaviate hybrid search
│   ├── generation/     fused prompt, answerer, validator
│   └── api/            FastAPI app
├── migrations/ (Weaviate schema, Neo4j constraints), eval/, tests/, data/corpus/
```
