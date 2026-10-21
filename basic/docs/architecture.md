# Architecture: Basic RAG

## Flow
```
Ingest (offline)
  data/corpus/*.{md,pdf,html}
    → load + normalize → PAN/PII scrub → heading-aware chunk
    → upsert PolicyChunk (Weaviate vectorizes via text2vec-openai)

Query (online, POST /v1/ask)
  question + filters (card_network?, as_of?)
    → PAN/PII scrub → hybrid search (BM25 + vector, filtered, top_k)
    → score threshold → [none pass → refusal, no LLM call]
    → prompt assembly (versioned) → OpenAI Responses API (structured output)
    → citation validation → GroundedAnswer + audit event
```

## Collection `PolicyChunk`
| Property | Type | Vec | Tokenization | Notes |
|---|---|---|---|---|
| `content` | text | yes | word | scrubbed body |
| `doc_title` | text | yes | word | |
| `doc_id` | text | no | field | stable source ID |
| `version` | text | no | field | |
| `section_path` | text | no | field | e.g., `Visa > 10.4 > Remedies` |
| `chunk_index` | int | no | – | |
| `source_type` | text | no | field | `network_rule` \| `internal_sop` \| `playbook` |
| `card_network` | text | no | field | `visa` \| `mastercard` \| `amex` \| `discover` \| `all` |
| `reason_codes` | text[] | no | field | e.g., `["10.4"]`, `["4853"]` |
| `jurisdiction` | text | no | field | `US`, `EU`, `global` |
| `effective_date` | date | no | – | supersession filter |
| `content_hash` | text | no | field | SHA-256 |

- Object UUID: `uuid5(doc_id:version:chunk_index)`.
- Vectorizer: `text2vec-openai` on `content` and `doc_title`. Index: HNSW, cosine distance.

## Chunking
- Split on headings first, then on paragraphs. Target 400–600 tokens with ~15% overlap. Never split a table or a numbered evidence list.
- Prefix each chunk with its `section_path` breadcrumb, so it still makes sense when retrieved alone.
- Extract reason codes with per-network regex during ingestion. This metadata drives BM25 and filters.

## Retrieval tuning
`HYBRID_ALPHA` (0 = BM25, 1 = vector; default 0.5), `TOP_K` (5), and `MIN_SCORE` (tuned on eval) are set in `.env.example`.

## API contract
`POST /v1/ask` takes `{question, card_network?, as_of?}` and returns `{answer, citations[{doc_id, section_path, effective_date}], refused, query_id, prompt_version}`.
Authentication is via the upstream gateway (an internal SSO JWT). The service checks for the `disputes.read` role.

## NFR targets
| NFR | Target |
|---|---|
| Latency | p95 < 3 s end to end |
| Retrieval quality | recall@5 ≥ 0.90 on the golden set |
| Faithfulness | citation accuracy ≥ 0.95 |
| Safety | 0 PAN/PII in index, logs, LLM payloads |
| Availability | 99.5% (internal tool) |
| Cost | < $0.01 avg per query |
| Freshness | Updates searchable < 24 h |

