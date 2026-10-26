# do-rag: RAG reference implementations (payments domain)

This repo holds three **independent** RAG projects. All of them serve one use case: a **Dispute & Chargeback Policy Assistant** for payments operations.

## Repo map
- `basic-rag/`: single-shot hybrid retrieval → cited answer. Weaviate + OpenAI.
- `advanced-rag/`: query planning, multi-query + RRF, parent-child chunks, LLM rerank, multi-turn.
- `hybrid-rag/`: vector retrieval (Weaviate) + knowledge graph (Neo4j), fused into one cited answer.

## Shared rules
- Each variant is self-contained: its own `pyproject.toml`, `uv` env, `.env`, `docker-compose.yml` (distinct ports), corpus copy, and tests. Never import across variants.
- Run commands from the variant directory (e.g., `cd basic-rag && uv run pytest`).
- IMPORTANT: Never read, print, or edit any `.env`. Reference config by key name only. Only `OPENAI_API_KEY` is required; models default in each `config.py`.
- Keep diffs minimal; prefer editing existing files.
- Before you say a task is done, run that variant's tests, ruff, and mypy, plus the eval gate when it applies.

## Instruction layers
| Layer | Location | Loads |
|---|---|---|
| Repo | `CLAUDE.md` (this file) | always |
| Security | `.claude/rules/security-compliance.md` | always |
| Shared code rules | `.claude/rules/python.md`, `testing-eval.md` | on `*.py` / tests / eval in any variant |
| Variant | `<variant>/CLAUDE.md` | in that variant |
| Variant rules | `.claude/rules/<variant>-*.md` | on matching paths |
| Module | `<variant>/src/<pkg>/<module>/CLAUDE.md` | in that module |
| Personal | `CLAUDE.local.md` (git-ignored) | always, if present |

Lower layers may tighten a rule, never loosen it. Each fact lives in one layer; other layers point to it.

## Working efficiently
- Use the Explore subagent for broad codebase searches; keep the main context for edits.
- Read `<variant>/docs/architecture.md` only when changing schema, chunking, graph, or data flow.
- When context is compacted, keep: the current task, failing test output, and the non-negotiables.
