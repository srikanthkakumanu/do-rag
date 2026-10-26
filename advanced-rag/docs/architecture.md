# Architecture: Advanced RAG

## Flow
```
Ingest (offline, `advanced ingest`)
  corpus → scrub → heading sections = PARENTS (≤1200 tok)
         → sentence/list windows = CHILDREN (≤220 tok, 40 tok overlap)
  PolicySection ← parents (fetched by ID)   PolicyChunk ← children (vectorized)

Query (POST /v1/ask {question, history[], card_network?, as_of?})
  scrub question + history
  → PLAN (nano): standalone question, ≤3 sub-queries, network, codes, in_scope
       guard: codes must appear in conversation; network only if exactly one in play
       failure → regex plan (degraded)          out of scope → refuse
  → hybrid search per query (children, filtered) ── asyncio.gather
  → RRF to parents (k=60) → ≤3 per doc → ≤8 candidates → fetch parents
  → RERANK (nano): grade 0–3 → keep ≥2, top 4      none → refuse (corrective)
  → ANSWER (mini): structured, cited → validate → GroundedAnswer + audit
```

## Collections
| `PolicyChunk` (children) | `PolicySection` (parents) |
|---|---|
| `content` (vectorized with `doc_title`), `parent_id` | `content` (not indexed for search) |
| `doc_id`, `version`, `section_path`, `chunk_index` | `doc_id`, `version`, `section_path`, `section_index` |
| `card_network`, `reason_codes[]`, `source_type`, `jurisdiction` | `effective_date`, `content_hash` |
| `effective_date`, `superseded_on`, `content_hash` | |

IDs are `uuid5(doc:version:s{n})` for parents and `uuid5(doc:version:c{n})` for children. Supersession is filtered on children.

## Why these techniques
| Problem in basic | Technique |
|---|---|
| Follow-ups ("and remedies?") lose context | History condensation (planner) |
| One query misses one side of a comparison | Multi-query + RRF |
| Small chunks lack context; big chunks dilute retrieval | Parent-child (small-to-big) |
| Top-k contains near-misses | LLM rerank + corrective gate |
| One doc crowds out the others | Per-doc candidate cap |

## API
`POST /v1/ask` returns basic's fields plus `standalone_question`. History has at most 20 turns (the planner reads the last 6), roles `user|assistant`, and is scrubbed. Auth is `X-Auth-Roles: disputes.read`. Audit records the plan (network, codes, sub-query count, degraded), candidate IDs, rerank scores, and refusal reason.

## NFR targets
| NFR | Target | Last measured |
|---|---|---|
| recall@5 / citation accuracy | ≥ 0.90 / ≥ 0.95 | 1.00 / 0.96–1.00 |
| Refusal precision / recall | ≥ 0.95 | 1.00 / 1.00 |
| p95 latency | < 6 s | 5.8–6.0 s typical, 7.7 s worst run (median ≈ 4.5 s, about 1.3 s per LLM call) |
| Safety | 0 PAN/PII in index, logs, LLM payloads | scrubber + tests |
