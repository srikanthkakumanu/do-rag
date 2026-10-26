# basic-rag/: Basic RAG, Dispute & Chargeback Policy Assistant

## Mission
Payments operations analysts ask dispute questions ("What evidence defeats Visa 10.4?", "Mastercard 4853 response window?"). The service retrieves approved policy chunks from Weaviate and returns a **cited** answer, or refuses. Wrong answers cost chargebacks, so grounding beats helpfulness.

Scope is single-shot retrieve → generate. No agents, query rewriting, reranking, or graph. Those belong to `advanced-rag/`. "Hybrid" here means Weaviate's BM25 + vector query mode, not the `hybrid-rag/` variant.

## Stack
| Concern | Choice |
|---|---|
| Runtime | Python 3.12, `uv`, FastAPI, Pydantic v2, pydantic-settings |
| Vector DB | Weaviate 1.3x (Docker Compose), v4 Python client |
| Embeddings | Weaviate `text2vec-openai` (`OPENAI_EMBED_MODEL`, default `text-embedding-3-small`) |
| LLM | OpenAI Responses API via `openai` SDK (`OPENAI_CHAT_MODEL`, validated with `gpt-5.4-mini`) |
| Quality | pytest, testcontainers, ruff, mypy `--strict` |
| Ops | structlog (JSON), OpenTelemetry |

Config keys are listed in `.env.example`; only `OPENAI_API_KEY` is required (models default in `config.py`). You create the real `.env`; it is git-ignored and never read by Claude.

## Commands (run from `basic-rag/`)
```bash
uv sync                                   # install
docker compose up -d weaviate             # local Weaviate on :8080
uv run python -m migrations.apply         # create/upgrade schema
uv run basic ingest data/corpus           # scrub, chunk, upsert
uv run uvicorn basic.api.app:app --reload # serve POST /v1/ask
uv run pytest -m "not integration"        # unit tests (no Docker)
uv run pytest -m integration              # real Weaviate via testcontainers
uv run ruff check . && uv run mypy src migrations eval tests
uv run python -m eval.run --report eval/reports/<date>.json
```

## Non-negotiables
1. Cite or refuse. Every claim maps to a retrieved chunk.
2. Fully type-hinted and clean under `mypy --strict`.
3. Weaviate v4 client only. Schema changes only through migrations.
4. Prompts are versioned files and are never edited in place.
5. Changes to retrieval, chunking, prompts, or models must pass the eval gate.

## Definition of done
- Unit and integration tests pass. Ruff and mypy are clean.
- The eval report is attached when the gate applies.
- New config keys are added to `.env.example` and `config.py`.
- Architecture changes are reflected in `docs/architecture.md`.

## Where to look
- Data flow, schema, NFRs: `docs/architecture.md` (read on demand)
- Shared types and constants: `src/basic/domain.py`; Weaviate plumbing: `src/basic/vectordb.py`
- Module contracts: `src/basic/{ingestion,retrieval,generation}/CLAUDE.md`
- Coding rules load automatically: shared `python.md` and `testing-eval.md`, plus `basic-*.md`
