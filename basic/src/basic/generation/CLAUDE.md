# generation/

## Purpose
Turn retrieved chunks and a question into a `GroundedAnswer` that is cited and validated, or into the exact refusal. Generation only; no retrieval.

## Owns
- `prompts/answer_v{n}.md`: versioned prompt templates (rules in `.claude/rules/basic-llm-prompts.md`).
- `assembler.py`: builds the prompt within the token budget, wrapping chunks in `<source>` tags.
- `llm.py`: the `OpenAIAnswerer`, which implements the `Answerer` protocol (Responses API with structured output).
- `validator.py`: checks citations against the chunks that were sent.
- `service.py`: `answer_question()` orchestration.

## Interface
```python
class Answerer(Protocol):
    async def generate(self, prompt: AssembledPrompt) -> GroundedAnswer: ...

async def answer_question(
    question: str, chunks: list[RetrievedChunk], *, answerer: Answerer, settings: Settings,
) -> GroundedAnswer: ...
```

## Invariants
- `chunks == []` returns the refusal immediately, with no LLM call.
- Every `Citation.doc_id` and `section_path` must be among the chunks that were sent. Otherwise the answer becomes a refusal and a `citation_mismatch` warning is logged.
- `GroundedAnswer.prompt_version` and `model` are always set (for the audit trail).
- The output never contains text outside the structured schema. On schema-parse failure, retry once, then refuse.
- Deadlines, amounts, and reason codes in the answer must appear verbatim in a cited chunk. The validator checks digits and codes.

## Don't
- Don't hardcode the model ID or the refusal string; read both from `Settings` and constants.
- Don't stream partial answers. Validation needs the full response.
- Don't add memory, tools, or multi-turn state (that's `advanced/`).

## Test
- Unit, with a fake `Answerer`: the empty-chunks short-circuit, hallucinated-citation rejection, a numeric claim not found in any source, an over-budget context dropping the lowest-score chunk, and an injection string inside a chunk.
- Prompt changes: new version file plus an eval report. Never edit in place.
