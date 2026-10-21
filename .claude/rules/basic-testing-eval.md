---
paths:
  - "basic/tests/**"
  - "basic/eval/**"
---
# Testing & evaluation (basic/)

## Layout
- `tests/unit/`: pure logic (chunking, PAN scrubber, citation validator, prompt assembly). No network. Fast (<5 s total).
- `tests/integration/`: real Weaviate via `testcontainers`, marked `@pytest.mark.integration`. The vectorizer is `none` and tests supply fixed vectors, so no OpenAI calls run in CI.
- `eval/`: offline quality gate against the golden set. Runs against real OpenAI and needs `.env`; run it locally or as a gated CI job.

## Rules
- Run `uv run pytest -m "not integration"` by default and `uv run pytest -m integration` before merging retrieval changes.
- Mock OpenAI at the `Protocol` boundary with typed fakes. Never patch SDK internals, and never call real APIs in unit tests.
- Tests are fully type-hinted like source code. Fixtures return typed objects.
- Name tests by behavior: `test_<unit>_<condition>_<expected>`.
- Each bug fix adds a regression test that fails without the fix.
- IMPORTANT: Fixtures contain no real PANs, customer data, or proprietary network rule text. Use synthetic policy snippets.

## Must-have cases
- The PAN scrubber catches spaced and dashed PANs and leaves non-Luhn numbers alone.
- Re-ingesting identical input changes nothing (idempotency).
- Superseded document versions never come back from retrieval.
- Zero chunks above threshold returns the refusal string without calling the LLM.
- A hallucinated citation is caught by the validator and turned into a refusal.
- Prompt-injection text inside a chunk doesn't change the system behavior.

## Eval gate (required for changes to retrieval, chunking, prompts, or models)
- The golden set is in `eval/golden.jsonl` (`question`, `expected_doc_ids`, `must_refuse`), with at least 50 items covering every card network and out-of-scope questions.
- Run with `uv run python -m eval.run --report eval/reports/<date>.json`.
- Thresholds: recall@5 ≥ 0.90, citation accuracy ≥ 0.95, refusal precision/recall ≥ 0.95, p95 latency < 3 s.
- Attach the report summary to the PR. Any regression larger than 2 points blocks the merge.
