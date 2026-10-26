# Architecture: Hybrid RAG (vector + knowledge graph)

## Flow
```
Ingest (offline, `hybrid ingest [--reextract]`)
  corpus → scrub → heading-aware chunks
        └→ chunks with codes → EXTRACT (nano) → guard (code ∈ chunk, quote ⊂ chunk,
           days ∈ quote, enums) → Neo4j (replace this chunk's facts) → then Weaviate

Query (POST /v1/ask {question, card_network?, as_of?})
  scrub → ┬ GRAPH PLAN (nano, guarded) → read-only templates → facts (≤12)
          └ vector hybrid search (top 5)            [concurrent]
  → any evidence? → ANSWER (mini) over <graph_fact> + <source> → validate → audit
  (plan.in_scope=false only skips the graph; refusal is the answer step's job)
```

## Graph ontology
| Node (key) | Relationship from `ReasonCode` | Meaning |
|---|---|---|
| `Network` (`name`) | `(Network)-[:DEFINES]->` | from chunk metadata, no LLM |
| `Deadline` (`days\|party\|action`) | `HAS_DEADLINE` | e.g., merchant must respond within 30 days |
| `Evidence` (`name`, lowercase) | `REMEDIED_BY` / `NOT_SUFFICIENT` | defends / does not suffice alone |
| `Category` (`name`) | `IN_CATEGORY` | fraud, authorization, processing_error, consumer_dispute |

`ReasonCode` is keyed by `code` and carries `network`. Fact edges carry provenance: `chunk_id`, `doc_id`, `version`, `section_path`, `quote`, `effective_date`, and `superseded_on`, matching the Weaviate chunk.

## Read templates (`graph/queries.py`)
| Template | When | Returns |
|---|---|---|
| `FACTS_FOR_CODES` | plan has codes | facts of the requested kinds |
| `CODES_BY_DEADLINE` | `deadline_days` | every code with that deadline |
| `CODES_BY_CATEGORY` | `category` | every code in that category |
| `FACTS_FOR_NETWORKS` | networks + kinds only | facts across those networks' codes |

All templates are `MATCH`-only, current on `$as_of`, and limited to `GRAPH_MAX_FACTS`.

## Why hybrid
Vector top-k returns the 5 most similar chunks. "Which codes give 45 days?" needs every matching fact, wherever it lives. The graph supplies exact, complete facts; the vectors supply prose context. The quote guard keeps the graph as grounded as the text.

## NFRs
| NFR | Target | Last measured (2 runs) |
|---|---|---|
| recall@5 / citation accuracy | ≥ 0.90 / ≥ 0.95 | 1.00 / 0.97–1.00 |
| Refusal precision / recall | ≥ 0.95 | 1.00 / 1.00 |
| Coverage (multi-doc: expected docs cited) | ≥ 0.80 | 1.00 |
| p95 latency | < 5 s | 3.2–3.8 s |
| Safety | 0 PAN/PII in either store, logs, prompts | scrubber + tests |

Known noise: the nano extractor sometimes labels a restriction as `NOT_SUFFICIENT` (the 4837 issuer limit).
