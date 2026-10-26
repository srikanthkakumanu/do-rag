# generation/

## Purpose
Turn retrieved chunks and a question into a `GroundedAnswer` that is cited and validated, or into the exact refusal. Generation only; no retrieval.

## Owns
- `prompts/answer_v{n}.md`: versioned prompt templates (rules in `.claude/rules/basic-llm-prompts.md`).
- `assembler.py`: `AssembledPrompt`. Builds the prompt within the token budget, wrapping chunks in `<source>` tags.
- `llm.py`: the `LLMAnswer` schema, the `Answerer` protocol, and `OpenAIAnswerer` (Responses API `parse`).
- `validator.py`: checks citations and facts against the chunks that were sent.
- `service.py`: `answer_question()` orchestration.

## Interface
```python
class Answerer(Protocol):
    @property
    def model(self) -> str: ...
    async def generate(self, prompt: AssembledPrompt) -> LLMAnswer: ...

async def answer_question(question: str, chunks: list[RetrievedChunk], *,
                          answerer: Answerer, settings: Settings) -> GroundedAnswer: ...
```

## Invariants
- `chunks == []` returns the refusal immediately, with no LLM call.
- Every citation's `doc_id` and `section_path` must be among the chunks that were sent. Otherwise the answer becomes a refusal and a `citation_mismatch` warning is logged.
- `GroundedAnswer.prompt_version` and `model` are always set (for the audit trail).
- On `SchemaParseError`, retry once, then refuse.
- Every number and reason code in the answer (outside citation marks) must appear verbatim in a cited chunk. Otherwise `unsupported_fact` causes a refusal.
- A model refusal is normalized to `REFUSAL_TEXT` exactly.

## Don't
- Don't hardcode the model ID or the refusal string; read them from `Settings` and `basic/domain.py`.
- Don't stream partial answers. Validation needs the full response.
- Don't add memory, tools, or multi-turn state (that's `advanced/`).

## Test
- Unit, with `FakeAnswerer` (`tests/fakes.py`): the empty-chunks short-circuit, hallucinated citation, unsupported number, retry then refusal, budget drop, and prompt injection kept inside `<source>`.
- Prompt changes: new version file plus an eval report. Never edit in place.
