# generation/

## Purpose
Turn reranked parent sections and the standalone question into a cited, validated `GroundedAnswer`, or the exact refusal. Generation only.

## Owns
- `prompts/answer_v{n}.md`: the versioned answer prompt (allows clearly labelled partial answers).
- `assembler.py`: `AssembledPrompt`, with sections in `<source>` tags and the lowest grade dropped first when over `source_token_budget`.
- `llm.py`: the `LLMAnswer` schema, the `Answerer` protocol, and `OpenAIAnswerer` over the shared `StructuredLLM` (`purpose="answer"`).
- `validator.py`: citation and fact checks.
- `service.py`: `answer_question()` and `refusal()`.

## Interface
```python
class Answerer(Protocol):
    @property
    def model(self) -> str: ...
    async def generate(self, prompt: AssembledPrompt) -> LLMAnswer: ...

async def answer_question(question: str, sections: list[RetrievedSection], *,
                          answerer: Answerer, settings: Settings) -> GroundedAnswer: ...
def validate(answer: LLMAnswer, sent: tuple[RetrievedSection, ...], question: str = "") -> ValidationResult: ...
```

## Invariants
- No sections means a refusal with no LLM call.
- Every citation `(doc_id, section_path)` must be a sent section. Otherwise the answer becomes a refusal (`citation_mismatch`).
- Every number or code in the answer (outside citation marks) appears in a cited section or in the question. Otherwise the answer becomes a refusal (`unsupported_fact`). Echoing the user's own numbers is allowed.
- A schema-parse failure retries once, then refuses. A model refusal is normalized to `REFUSAL_TEXT`.
- `prompt_version` and `model` are always set for the audit trail.

## Don't
- Don't pass history here; the planner already condensed it into the question.
- Don't stream; validation needs the whole answer.
- Don't hardcode models or the refusal text.

## Test
- Unit, with `FakeAnswerer`: empty short-circuit, hallucinated citation, unsupported number, question-echo allowed, retry then refuse, budget drop, injection stays in `<source>`.
