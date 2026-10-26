# generation/

## Purpose
Fuse graph facts and vector chunks into one prompt, generate a cited answer, and validate it against **both** evidence kinds, or return the exact refusal.

## Owns
- `prompts/answer_v{n}.md`: explains `<graph_fact>` vs `<source>` and prefers facts for lists and counts.
- `assembler.py`: `AssembledPrompt(chunks, facts)`. Facts go first (small, exact), then chunks fill the remaining `source_token_budget` (lowest score dropped).
- `llm.py`: `LLMAnswer`, the `Answerer` protocol, and `OpenAIAnswerer` over the shared `StructuredLLM` (`purpose="answer"`).
- `validator.py`: `evidence_index()` and `validate()`.
- `service.py`: `answer_question(question, chunks, facts, ...)` and `refusal()`.

## Interface
```python
async def answer_question(question: str, chunks: list[RetrievedChunk], facts: list[GraphFact], *,
                          answerer: Answerer, settings: Settings) -> GroundedAnswer: ...
def validate(answer: LLMAnswer, prompt: AssembledPrompt, question: str = "") -> ValidationResult: ...
```

## Invariants
- No chunks **and** no facts means a refusal with no LLM call. Facts alone are enough to answer.
- Citations use `[doc_id §section_path]` for both kinds. `evidence_index` maps each key to all text sent under it (chunk content, fact statement + quote).
- Every number or code in the answer appears in a cited item, the question, or a spelled-out form ("two" supports "2"). Otherwise `unsupported_fact` → refusal.
- A schema failure retries once, then refuses. A model refusal is normalized to `REFUSAL_TEXT`. `prompt_version` and `model` are always set.

## Don't
- Don't let the LLM rephrase graph facts as facts of its own; statements come from `graph/retriever.render`.
- Don't stream; validation needs the whole answer.
- Don't hardcode models or the refusal text.

## Test
- Unit: facts-first assembly, budget keeps facts, citing a graph fact validates, number missing from cited items, unknown citation, facts-only answer, retry then refuse, number words, injection stays in tags.
