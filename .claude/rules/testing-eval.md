---
paths:
  - "basic-rag/tests/**"
  - "basic-rag/eval/**"
  - "advanced-rag/tests/**"
  - "advanced-rag/eval/**"
  - "hybrid-rag/tests/**"
  - "hybrid-rag/eval/**"
---
# Testing & evaluation (all variants)

## Layout
- `tests/unit/`: pure logic, with no network and no Docker. Fast (a few seconds total).
- `tests/integration/`: real stores via `testcontainers`, marked `@pytest.mark.integration`. Weaviate uses `WEAVIATE_VECTORIZER=none` with `fake_embed` vectors, so no OpenAI calls run in CI.
- `eval/`: offline quality gate against `eval/golden.jsonl`. Runs against real OpenAI using the variant's own `.env`.
- Test doubles live in `tests/fakes.py` and implement the same `Protocol`s as production.

## Rules
- Run `uv run pytest -m "not integration"` by default, and `uv run pytest -m integration` before merging store changes.
- Fake LLMs at the `Protocol` boundary. Never patch SDK internals, and never call real APIs in unit tests.
- `make_settings()` passes `_env_file=None` so tests never read a real `.env`.
- Tests are fully type-hinted. Name them by behavior: `test_<unit>_<condition>_<expected>`.
- Each bug fix adds a regression test that fails without the fix.
- IMPORTANT: Fixtures contain no real PANs, customer data, or proprietary network rule text. Use synthetic policy snippets.

## Cases every variant must cover
- The PAN scrubber catches spaced, dashed, and digit-adjacent PANs and leaves non-Luhn numbers alone.
- Re-ingesting identical input changes nothing (idempotency).
- Superseded document versions never come back from retrieval.
- No sources means the refusal string with no LLM call.
- A hallucinated citation or an unsupported number becomes a refusal.
- Prompt-injection text in a source stays inside its data tags.

## Eval gate (required for changes to retrieval, chunking, prompts, models, or the graph)
- Run `uv run python -m eval.run --report eval/reports/<date>.json`. Reports are git-ignored, so paste the summary into the PR.
- Thresholds live in `eval/run.py` (`THRESHOLDS`, `P95_LATENCY_MS`): recall@5 ≥ 0.90, citation accuracy ≥ 0.95, refusal precision and recall ≥ 0.95, plus the variant's p95 latency.
- LLM outputs vary between runs. Run the gate twice before you call a result a regression or a fix.
