---
paths:
  - "hybrid/src/hybrid/llm.py"
  - "hybrid/src/hybrid/ingestion/extract.py"
  - "hybrid/src/hybrid/ingestion/prompts/**"
  - "hybrid/src/hybrid/graph/planner.py"
  - "hybrid/src/hybrid/graph/prompts/**"
  - "hybrid/src/hybrid/generation/**"
---
# LLM & prompt conventions (hybrid/, OpenAI)

## One gateway, three calls
- Every model call goes through `StructuredLLM.parse(..., schema=..., purpose=...)` in `hybrid/llm.py`: Responses API, `store=False`, structured output, and `omit` for unset `temperature`/`reasoning`.
  | purpose | model | effort | when |
  |---|---|---|---|
  | `extract` | `fast_model` (gpt-5.4-nano) | none | ingestion, per changed chunk with codes |
  | `graph_plan` | `fast_model` | none | per request, in parallel with vector search |
  | `answer` | `openai_chat_model` (gpt-5.4-mini) | low | per request |
- Models come from `Settings` (only `OPENAI_API_KEY` is required). One client per process.

## Trust boundaries
- IMPORTANT: LLM output never becomes Cypher, labels, or filters directly. `graph/planner.guard` keeps codes only if they appear in the question, networks only if named or implied by a code, `deadline_days` only if that number is in the question, and `kinds`/`category` only as enum values.
- A planner failure degrades to a regex plan (codes + networks, all kinds). An extraction failure defers that chunk from both stores; the run exits non-zero and a rerun retries it.
- Wrap untrusted text in tags (`<chunk>`, `<question>`, `<graph_fact>`, `<source>`), and every prompt says the content inside is data.

## Prompts
- Prompts are versioned files: `ingestion/prompts/extract_v{n}.md`, `graph/prompts/plan_v{n}.md`, and `generation/prompts/answer_v{n}.md`.
- Never edit a released prompt in place. Add `v{n+1}` and run the eval gate twice (`testing-eval.md`). Changing the extraction prompt requires `hybrid ingest data/corpus --reextract`.

## Grounding contract (answer)
- Graph facts render as `<graph_fact id="G1" doc=... section=... effective=...>statement. Quote: "..."</graph_fact>`, and chunks as `<source ...>`.
- Cite both kinds as `[doc_id §section_path]`. Prefer graph facts for lists and counts, and sources for explanations. If the evidence covers only part of the question, say what is missing.
- Validation: each citation must match a sent fact or chunk, and numbers and codes must appear in a cited item or the question. Otherwise return `REFUSAL_TEXT`.
- Log token usage per `purpose`; never log prompt, chunk, or answer text.
