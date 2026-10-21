# do-rag

Three independent RAG implementations for one payments use case: a **Dispute & Chargeback Policy Assistant**. Analysts ask questions like *"What evidence defeats a Visa 10.4 dispute?"* and get an answer where every claim cites approved policy, or a refusal.

| Project | Approach | Status |
|---|---|---|
| [`basic/`](basic/README.md) | Single-shot: Weaviate hybrid search → OpenAI cited answer | Done: 64 tests, eval gate passed |
| [`advanced/`](advanced/README.md) | Query planning, multi-query + RRF, parent-child chunks, LLM rerank, multi-turn | Done: 91 tests; quality gates pass, p95 latency borderline (~6 s) |
| [`hybrid/`](hybrid/README.md) | Weaviate vector search + Neo4j knowledge graph, fused | Done: 87 tests, eval gate passed (incl. coverage) |

Each project has its own `pyproject.toml`, `.env`, Docker Compose (distinct ports), corpus, and tests. Only `OPENAI_API_KEY` is required in each `.env`.

## Ports
| Project | Weaviate (HTTP/gRPC) | Neo4j (HTTP/Bolt) | API (suggested) |
|---|---|---|---|
| basic | 8080 / 50051 | – | 8000 |
| advanced | 8081 / 50052 | – | 8001 |
| hybrid | 8082 / 50053 | 7475 / 7688 | 8002 |

## Instruction layers (Claude Code)
```
CLAUDE.md                                   repo-wide, always loaded
.claude/rules/security-compliance.md        PCI/PII, always loaded
.claude/rules/python.md, testing-eval.md    shared code rules (all variants, path-scoped)
<variant>/CLAUDE.md                         variant constitution (loaded inside that folder)
.claude/rules/<variant>-*.md                variant rules (Weaviate, LLM, graph), path-scoped
<variant>/src/<pkg>/<module>/CLAUDE.md      module contracts (loaded inside that module)
<variant>/docs/architecture.md              read on demand
```
Every instruction file is 300–800 tokens, and about 1k tokens load at startup. The rest loads only when Claude works in the matching folder or files.
