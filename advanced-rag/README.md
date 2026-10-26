# Advanced RAG: Dispute & Chargeback Policy Assistant

Same use case and grounding contract as [`basic/`](../basic/README.md): **cited answers or a refusal**. It adds the techniques that fix single-shot RAG's typical failures:

| Failure in basic RAG | What advanced does |
|---|---|
| "And what remedies apply?" loses the conversation | **Query planner** rewrites follow-ups into a standalone question |
| "Window for 4853?" has no network filter | Planner infers the network from the code (guarded: never trusts invented codes) |
| "Compare Visa 10.4 and Mastercard 4837" retrieves one side | **Multi-query** search + **reciprocal rank fusion** |
| Small chunks lose context; big chunks dilute search | **Parent-child**: search 220-token children, answer from whole sections |
| Top-k includes near-misses | **LLM reranker** (0–3) + corrective refusal when nothing is relevant |
| One long document crowds out others | Per-document candidate cap |

## Stack
Python 3.12, `uv`, FastAPI, Pydantic v2 · Weaviate 1.38 (ports **8081/50052**, so it runs beside `basic/`) · `text-embedding-3-small` · OpenAI Responses API: `gpt-5.4-nano` for planning and reranking, `gpt-5.4-mini` for answers · pytest, testcontainers, ruff, mypy `--strict`.

## Quick start
```bash
cd advanced
cp .env.example .env              # only OPENAI_API_KEY is required
uv sync
docker compose up -d --wait weaviate
uv run python -m migrations.apply
uv run advanced ingest data/corpus
uv run uvicorn advanced.api.app:app --port 8001
```
```bash
curl -s localhost:8001/v1/ask -H 'Content-Type: application/json' -H 'X-Auth-Roles: disputes.read' -d '{
  "question": "And what remedies apply?",
  "history": [
    {"role": "user", "content": "What is the response window for Mastercard 4853?"},
    {"role": "assistant", "content": "45 calendar days from the chargeback date."}
  ]}'
```
The response includes `standalone_question` (here: *"What remedies apply for Mastercard dispute reason code 4853?"*) along with `answer`, `citations`, `refused`, `query_id`, `prompt_version`, and `notice`.

## Reliability by design
- **Guarded planning:** reason codes must appear in the conversation, and a network filter is set only when exactly one network is in play.
- **Graceful degradation:** if the planner fails, a regex plan is used; if the reranker fails, the fused order is kept. Neither fails the request.
- **Validation:** citations must match sent sections, and every number must appear in a cited section or the user's question.
- **Security:** question and history are scrubbed (PAN/PII), untrusted text is wrapped in data tags, and every answer writes an audit event.

## Tests and quality gate
```bash
uv run pytest -m "not integration"   # 84 unit tests
uv run pytest -m integration         # 7 tests on a real Weaviate container (no OpenAI)
uv run ruff check . && uv run mypy src migrations eval tests
uv run python -m eval.run --report eval/reports/$(date +%F).json
```
The golden set has 60 questions: basic's 50 with network hints removed, plus 5 multi-turn follow-ups, 3 cross-network comparisons, an out-of-scope follow-up, and a code-only question. Recent live runs:

| Metric | Result | Gate |
|---|---|---|
| recall@5 | 1.00 | ≥ 0.90 |
| citation accuracy | 0.96–1.00 | ≥ 0.95 |
| refusal precision / recall | 1.00 / 1.00 | ≥ 0.95 |
| p95 latency | 5.8–6.0 s, 7.7 s worst run | < 6 s |

**Latency is borderline.** Three LLM calls run in sequence (median ≈ 1.3 s each, about 4.5 s end to end), so OpenAI response-time swings push p95 around the 6 s gate. Options if it matters: stream the answer, skip reranking when candidates are few, or use a faster answer model. The corpus is synthetic and small, so treat these numbers as a smoke test.

## Layout
```
advanced/
├── CLAUDE.md, docs/architecture.md
├── src/advanced/
│   ├── rag.py          orchestration: plan → retrieve → rerank → answer
│   ├── llm.py          shared StructuredLLM gateway (OpenAI Responses API)
│   ├── query/          planner + prompt
│   ├── retrieval/      child search, RRF, parent fetch, reranker + prompt
│   ├── generation/     prompt assembly, answerer, validator
│   ├── ingestion/      scrub, parent-child chunking, two-collection store
│   └── api/            FastAPI app
├── migrations/, eval/, tests/, data/corpus/
```
