# advanced-rag/: Advanced RAG, Dispute & Chargeback Policy Assistant

## Mission
Same users, corpus, and grounding contract as `basic-rag/`, but it handles what single-shot RAG misses: follow-up questions, implied networks ("window for 4853?"), cross-network comparisons, and near-miss retrieval. Every answer is still **cited or refused**.

Independent project: its own `pyproject.toml`, `.env`, Weaviate (ports 8081/50052), and corpus copy. Never import from `basic-rag/` or `hybrid-rag/`.

## Pipeline (`src/advanced/rag.py`)
1. **Plan** (`query/`): the LLM condenses history into a standalone question, adds up to 3 sub-queries, extracts network and codes (guarded), and flags out-of-scope questions, which are refused before retrieval.
2. **Retrieve** (`retrieval/`): hybrid search over **child** chunks per query, RRF fused to **parent** sections, capped per doc.
3. **Rerank**: LLM grades candidates 0–3. Only those ≥ `MIN_RERANK_SCORE` go on (top 4); none left means a corrective refusal.
4. **Answer** (`generation/`): cited structured output, then validation, else `REFUSAL_TEXT`.

## Stack
| Concern | Choice |
|---|---|
| Runtime | Python 3.12, `uv`, FastAPI, Pydantic v2 |
| Vector DB | Weaviate 1.38, v4 client: `PolicyChunk` (children) + `PolicySection` (parents) |
| Embeddings | `text2vec-openai`, `text-embedding-3-small` |
| LLMs | OpenAI Responses API: `gpt-5.4-nano` plan/rerank, `gpt-5.4-mini` answer (defaults; only `OPENAI_API_KEY` required) |
| Quality | pytest, testcontainers, ruff, mypy `--strict` |

## Commands (run from `advanced-rag/`)
```bash
uv sync && docker compose up -d --wait weaviate
uv run python -m migrations.apply && uv run advanced ingest data/corpus
uv run uvicorn advanced.api.app:app --reload --port 8001
uv run pytest -m "not integration"   # and: -m integration
uv run ruff check . && uv run mypy src migrations eval tests
uv run python -m eval.run --report eval/reports/<date>.json
```

## Non-negotiables
1. Cite or refuse. Partial answers must name what the sources do not cover.
2. Model output never sets filters unchecked (see `planner.guard`).
3. Optional LLM steps degrade; they never fail the request.
4. Search children, send parents. Prompts are versioned and never edited in place.
5. Retrieval, prompt, or model changes pass the eval gate twice (p95 < 6 s; latency is borderline at about 4.5 s median).

## Definition of done
Tests, ruff, and mypy clean; eval summary in the PR; new config in `.env.example` and `config.py`; `docs/architecture.md` updated.

## Where to look
- Design, schema, NFRs: `docs/architecture.md` (on demand)
- Module contracts: `src/advanced/{ingestion,query,retrieval,generation}/CLAUDE.md`
- Rules: shared `python.md` and `testing-eval.md`, plus `advanced-*.md`
