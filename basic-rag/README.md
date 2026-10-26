# Basic RAG: Dispute & Chargeback Policy Assistant

Payments operations analysts ask dispute questions like *"What evidence defeats a Visa 10.4 dispute?"* or *"What is the Mastercard 4853 response window?"*. The service retrieves approved policy chunks from **Weaviate** and returns an answer from **OpenAI** where every claim is **cited**. If the sources don't cover the question, it refuses.

Scope: one retrieval step, then one generation step. No query rewriting, reranking, agents, or memory; those belong to `../advanced/`.

## Stack
| Concern | Choice |
|---|---|
| Runtime | Python 3.12, `uv`, FastAPI, Pydantic v2, pydantic-settings |
| Vector DB | Weaviate 1.38 (Docker Compose), v4 Python client, hybrid search (BM25 + vector) |
| Embeddings | `text2vec-openai` module, `text-embedding-3-small` (Weaviate vectorizes server-side) |
| LLM | OpenAI Responses API, structured output (validated with `gpt-5.4-mini`, reasoning effort `low`) |
| Quality | pytest, testcontainers, ruff, mypy `--strict` |
| Ops | structlog JSON logs + audit events, OpenTelemetry spans |

## Quick start
```bash
cd basic
cp .env.example .env            # add OPENAI_API_KEY (the only required value)
uv sync
docker compose up -d --wait weaviate
uv run python -m migrations.apply
uv run basic ingest data/corpus
uv run uvicorn basic.api.app:app --reload
```
```bash
curl -s localhost:8000/v1/ask \
  -H 'Content-Type: application/json' -H 'X-Auth-Roles: disputes.read' \
  -d '{"question": "What evidence defeats a Visa 10.4 dispute?", "card_network": "visa"}'
```
The response has `answer`, `citations[{doc_id, section_path, effective_date}]`, `refused`, `query_id`, `prompt_version`, and a "verify against the source" `notice`.

## How it works
1. **Ingest** (`src/basic/ingestion/`): loads Markdown (front matter), HTML, and PDF (sidecar `.meta`). It scrubs PANs (Luhn check) and PII **before** anything else, then splits on headings with breadcrumbs and ~15% sentence overlap, and upserts with deterministic UUIDs. Re-running is a no-op. All versions of a document stay indexed, and each one gets a `superseded_on` date.
2. **Retrieve** (`src/basic/retrieval/`): Weaviate hybrid query, filtered to versions current on `as_of` and to the requested card network plus cross-network docs.
3. **Generate** (`src/basic/generation/`): a versioned prompt with sources in `<source>` tags (prompt-injection safe). Output is OpenAI structured output, then validated: every citation must match a sent chunk, and every number or code must appear verbatim in a cited chunk. Any failure returns the exact refusal text.
4. **API** (`src/basic/api/`): `POST /v1/ask` requires the `disputes.read` role (`X-Auth-Roles` header from the gateway), scrubs the question, and writes one audit event per answer. Errors use RFC 9457 problem responses.

## Tests and quality gate
```bash
uv run pytest -m "not integration"     # 56 unit tests, no Docker
uv run pytest -m integration           # 8 tests on a real Weaviate container (fake vectors, no OpenAI)
uv run ruff check . && uv run mypy src migrations eval tests
uv run python -m eval.run --report eval/reports/$(date +%F).json   # needs .env + ingested corpus
```

The eval runs a 50-question golden set (`eval/golden.jsonl`), including 8 questions that must be refused. Latest run with `gpt-5.4-mini`, reasoning effort `low`:

| Metric | Result | Gate |
|---|---|---|
| recall@5 | 1.00 | ≥ 0.90 |
| citation accuracy | 1.00 | ≥ 0.95 |
| refusal precision / recall | 1.00 / 1.00 | ≥ 0.95 |
| p95 latency | 2.7 s | < 3 s |

The corpus in `data/corpus/` is **synthetic** (made-up summaries, not card-network rule text) and small, so these scores are a smoke test, not a benchmark.

## Layout
```
basic/
├── CLAUDE.md               Claude Code instructions for this project
├── docs/architecture.md    data flow, schema, NFRs
├── src/basic/              config, domain, vectordb, ingestion/, retrieval/, generation/, api/
├── migrations/             versioned Weaviate schema scripts
├── eval/                   golden set + quality gate runner
├── tests/                  unit/ and integration/
└── data/corpus/            synthetic sample policies
```
