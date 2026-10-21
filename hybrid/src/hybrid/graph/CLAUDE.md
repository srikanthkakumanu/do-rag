# graph/

## Purpose
Answer the structured half of a question from Neo4j: plan a lookup (guarded), run only fixed read-only templates, and return provenance-carrying `GraphFact`s.

## Owns
- `planner.py` + `prompts/plan_v{n}.md`: the `GraphPlanner` protocol, `LLMGraphPlanner` (fast model), `guard()`, `regex_plan()`, `mentioned_networks()`.
- `queries.py`: the ONLY read Cypher (`FACTS_FOR_CODES`, `FACTS_FOR_NETWORKS`, `CODES_BY_DEADLINE`, `CODES_BY_CATEGORY`).
- `retriever.py`: the `GraphRetriever` protocol, `Neo4jGraphRetriever`, `select_queries()`, `render()`.

## Interface
```python
class GraphPlanner(Protocol):
    async def plan(self, question: str, card_network: CardNetwork | None) -> GraphPlan: ...
class GraphRetriever(Protocol):
    async def facts(self, plan: GraphPlan, as_of: date) -> list[GraphFact]: ...
# GraphPlan: reason_codes, networks, kinds, deadline_days, category, in_scope, degraded
```

## Invariants
- `guard()`: codes must appear in the question; networks must be named or implied by a code (the request network wins); `deadline_days` must be a number in the question; kinds and category are enums.
- `in_scope=False` means "the graph has nothing to add", and `rag.py` skips the graph. It is **never** a refusal: scope belongs to the answer step.
- `select_queries()`: codes → `FACTS_FOR_CODES`; days → `CODES_BY_DEADLINE`; category → `CODES_BY_CATEGORY`; otherwise networks + kinds → `FACTS_FOR_NETWORKS`; no signal → no query.
- Every template is `MATCH`-only, filters `effective_date <= $as_of < superseded_on`, and has `LIMIT $limit` (`GRAPH_MAX_FACTS`).
- `render()` builds statements deterministically from node properties. Results are deduped and capped. Neo4j errors raise `RetrievalError`.

## Don't
- IMPORTANT: Never run LLM-written or string-built Cypher. Add a template plus a test instead.
- Don't return driver records beyond this module.
- Don't let the planner see chunks or answers.

## Test
- Unit (`tests/unit/graph/`): guard cases, regex fallback, template selection, templates read-only and time-filtered, write queries parameterized, rendering.
- Integration: the 45-day aggregate returns both Mastercard codes; code and network lookups; supersession.
