# query/

## Purpose
Turn a question plus conversation history into a validated `QueryPlan`: a standalone question, sub-queries, filters, and a scope decision. Planning only; no retrieval.

## Owns
- `planner.py`: the `QueryPlanner` protocol, `LLMQueryPlanner` (fast model via `StructuredLLM`), `guard()`, `regex_plan()`, `mentioned_networks()`.
- `prompts/plan_v{n}.md`: the versioned planner prompt (`{max_queries}` placeholder).

## Interface
```python
class QueryPlanner(Protocol):
    async def plan(self, question: str, history: list[Turn],
                   card_network: CardNetwork | None) -> QueryPlan: ...

class QueryPlan(BaseModel):
    standalone_question: str
    sub_queries: list[str]          # [standalone, *≤ multi_query_max extra]
    card_network: CardNetwork | None
    reason_codes: list[str]
    in_scope: bool
    degraded: bool                  # regex fallback was used
```

## Invariants
- `sub_queries[0]` is always the standalone question. Extra sub-queries are deduped and capped at `multi_query_max`.
- `reason_codes` must appear in the question or history (regex), so model-invented codes are dropped.
- `card_network`: the request value wins. Otherwise use the model's value only when exactly one network is named or implied by a code (`48xx` → Mastercard). Comparisons get no network filter.
- Only the last `history_max_turns` turns are sent, wrapped in `<history>` and `<question>` data tags.
- Any `GenerationError` returns `regex_plan()` (`degraded=True`, in scope, no rewriting) and logs `planner_degraded`.

## Don't
- Don't let the planner see sources, choose prompts, or emit free-text filters.
- Don't refuse here. `in_scope=False` is a signal; `rag.py` decides.
- Don't edit `plan_v1.md` in place; add `plan_v2.md` and re-run the eval.

## Test
- Unit (`tests/unit/query/`): hallucinated code dropped, implied network, comparison means no filter, request network wins, history truncation, degraded fallback, prompt renders.
- Eval: multi-turn and implied-network items in `eval/golden.jsonl`.
