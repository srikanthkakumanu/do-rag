# Architecture: Basic RAG

## Flow
```
Ingest (offline, `basic ingest`)
  data/corpus/*.{md,html,pdf}
    → load + normalize → PAN/PII scrub → heading-aware chunk
    → upsert PolicyChunk (Weaviate vectorizes via text2vec-openai)
    → set superseded_on on older versions

Query (online, POST /v1/ask)
  question + filters (card_network?, as_of?)
    → PAN/PII scrub → hybrid search (BM25 + vector, filtered, top_k)
    → min_score / max_vector_distance → [none pass → refusal, no LLM call]
    → prompt assembly (versioned) → OpenAI Responses API (structured output)
    → citation + fact validation → GroundedAnswer + audit event
```

## Collection `PolicyChunk`
| Property | Type | Vec | Tokenization | Notes |
|---|---|---|---|---|
| `content` | text | yes | word | scrubbed body |
| `doc_title` | text | yes | word | |
| `doc_id` | text | no | field | stable source ID |
| `version` | text | no | field | |
| `section_path` | text | no | field | breadcrumb |
| `chunk_index` | int | no | – | |
| `source_type` | text | no | field | `network_rule` \| `internal_sop` \| `playbook` |
| `card_network` | text | no | field | `visa` \| `mastercard` \| `amex` \| `discover` \| `all` |
| `reason_codes` | text[] | no | field | e.g., `["10.4"]` |
| `jurisdiction` | text | no | field | |
| `effective_date` | date | no | – | version start |
| `superseded_on` | date | no | – | next version's start, or 2199-12-31 |
| `content_hash` | text | no | field | SHA-256 |

- Object UUID: `uuid5(doc_id:version:chunk_index)`. Vectorizer: `text2vec-openai` on `content` and `doc_title`; HNSW, cosine.

## Chunking
- Split on headings, then paragraphs. Pack up to 600 tokens; carry ~90 tokens of trailing sentences as overlap. Never split a table or list.
- Prefix each chunk with its `section_path` breadcrumb so it stands alone.
- Reason codes come from per-network regex and are matched by BM25.

## Retrieval tuning
`HYBRID_ALPHA` (default 0.5), `TOP_K` (5), `MIN_SCORE` (0), and `MAX_VECTOR_DISTANCE` (0.75) are tuned only with the eval gate.

## API contract
`POST /v1/ask` takes `{question, card_network?, as_of?}` and returns `{answer, citations[{doc_id, section_path, effective_date}], refused, query_id, prompt_version, notice}`.
The gateway verifies the SSO JWT and forwards roles in `X-Auth-Roles`; the service requires `disputes.read` (otherwise 403). Errors are RFC 9457 `application/problem+json`.

## NFR targets
| NFR | Target |
|---|---|
| Latency | p95 < 3 s end to end |
| Retrieval quality | recall@5 ≥ 0.90 on the golden set |
| Faithfulness | citation accuracy ≥ 0.95 |
| Safety | 0 PAN/PII in index, logs, LLM payloads |
| Cost | < $0.01 avg per query |
