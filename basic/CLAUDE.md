# basic/: Basic RAG, Dispute & Chargeback Policy Assistant

## Mission
Payments operations analysts ask dispute questions ("What evidence defeats Visa 10.4?", "Mastercard 4853 response window?"). The service retrieves approved policy chunks from Weaviate and returns a **cited** answer, or refuses. Wrong answers cost chargebacks, so grounding beats helpfulness.

Scope is single-shot retrieve → generate. No agents, query rewriting, reranking, or graph. Those belong to `advanced/`. "Hybrid" here means Weaviate's BM25 + vector query mode, not the `hybrid/` variant.

## Stack
| Concern | Choice |
|---|---|
| Runtime | Python 3.12, `uv`, FastAPI, Pydantic v2, pydantic-settings |
| Vector DB | Weaviate 1.3x (Docker Compose), v4 Python client |
| Embeddings | Weaviate `text2vec-openai` (`OPENAI_EMBED_MODEL`, default `text-embedding-3-small`) |
| LLM | OpenAI Responses API via `openai` SDK (`OPENAI_CHAT_MODEL`) |
| Quality | pytest, testcontainers, ruff, mypy `--strict` |
| Ops | structlog (JSON), OpenTelemetry |

Config keys are listed in `.env.example`. You create the real `.env`; it is git-ignored and never read by Claude.

## Commands (run from `basic/`; target contract, implement to match)
```bash
uv sync                                   # install
docker compose up -d weaviate             # local Weaviate on :8080
uv run python -m migrations.apply         # create/upgrade schema
uv run basic ingest data/corpus           # scrub, chunk, upsert
uv run fastapi dev src/basic/api/app.py   # serve POST /v1/ask
uv run pytest -m "not integration"        # unit tests
uv run ruff check . && uv run mypy src    # lint + types
uv run python -m eval.run                 # quality gate
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
- Module contracts: `src/basic/{ingestion,retrieval,generation}/CLAUDE.md`
- Coding rules load automatically from `.claude/rules/basic-*.md`
