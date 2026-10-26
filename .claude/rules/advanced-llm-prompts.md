---
paths:
  - "advanced-rag/src/advanced/llm.py"
  - "advanced-rag/src/advanced/query/**"
  - "advanced-rag/src/advanced/retrieval/reranker.py"
  - "advanced-rag/src/advanced/retrieval/prompts/**"
  - "advanced-rag/src/advanced/generation/**"
---
# LLM & prompt conventions (advanced-rag/, OpenAI)

## One gateway, three calls
- Every model call goes through `StructuredLLM.parse(..., schema=..., purpose=...)` in `advanced/llm.py`: Responses API, `store=False`, structured output, and `omit` for unset `temperature`/`reasoning`.
- Calls and models (from `Settings`; only `OPENAI_API_KEY` is required):
  | purpose | model | effort | output cap |
  |---|---|---|---|
  | `plan` | `fast_model` (gpt-5.4-nano) | none | 500 |
  | `rerank` | `fast_model` | none | 400 |
  | `answer` | `openai_chat_model` (gpt-5.4-mini) | low | `max_output_tokens` |
- Never construct an OpenAI client per request. Never hardcode a model ID outside `config.py`.

## Trust boundaries
- IMPORTANT: Model output is never trusted for filters. `planner.guard` keeps reason codes only if they appear in the conversation, and sets a network filter only when exactly one network is in play.
- Planner and reranker failures degrade to the regex plan and the fused order (`warning` log). Answer failures retry once on a schema error, then refuse.
- Wrap untrusted text in tags: `<history>`, `<question>`, `<candidate id="S1">`, `<source ...>`. Every prompt says the content inside is data.
- The reranker sees short IDs (`S1..Sn`), never UUIDs. Unknown IDs are ignored and ungraded candidates score 0.

## Prompts
- Prompts are versioned files: `query/prompts/plan_v{n}.md`, `retrieval/prompts/rerank_v1.md`, and `generation/prompts/answer_v{n}.md`.
- Never edit a released prompt in place. Add `v{n+1}`, then run the eval gate twice (`testing-eval.md`).
- Keep static instructions first and byte-stable (prompt caching).

## Grounding contract (answer)
- Cite every claim as `[doc_id §section_path]`. If sources cover only part of a comparison, answer that part and say plainly what is missing.
- Validation: citations must match sent sections. Numbers and codes must appear in a cited section or in the user's (standalone) question. Otherwise refuse with `REFUSAL_TEXT`.
- Log token usage per `purpose`. Never log prompt or answer text.
