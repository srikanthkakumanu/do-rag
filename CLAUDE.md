# do-rag: RAG reference implementations (payments domain)

This repo holds independent RAG variants. All of them serve one use case: a **Dispute & Chargeback Policy Assistant** for payments operations.

## Repo map
- `basic/`: Basic RAG (Weaviate hybrid retrieval + OpenAI). **Active.**
- `advanced/`, `hybrid/`: planned. Do not create them unless asked.
- `.claude/rules/`: path-scoped rules, prefixed by variant (`basic-*.md`).

## Shared rules
- Each variant is self-contained: its own `pyproject.toml`, `uv` env, `docker-compose.yml`, and tests. Never import across variants. Share code only after an ADR in `<variant>/docs/adr/`.
- Run commands from the variant directory (e.g., `cd basic && uv run pytest`).
- IMPORTANT: Never read, print, or edit `.env` files. Reference config by key name only. See `.claude/rules/security-compliance.md`.
- Prefer editing existing files over adding new ones. Keep diffs minimal and focused.
- Before you say a task is done, run that variant's test, lint, and type check.

## Instruction layers
| Layer | Location | Loads |
|---|---|---|
| Repo | `CLAUDE.md` (this file) | always |
| Security | `.claude/rules/security-compliance.md` | always |
| Variant | `<variant>/CLAUDE.md` | in that variant |
| Rules | `.claude/rules/<variant>-*.md` | on matching paths |
| Module | `<variant>/src/<pkg>/<module>/CLAUDE.md` | in that module |
| Personal | `CLAUDE.local.md` (git-ignored) | always, if present |

Lower layers may tighten a rule, never loosen it. Each fact lives in one layer; other layers point to it.

## Working efficiently
- Use the Explore subagent for broad codebase searches; keep the main context for edits.
- Read `<variant>/docs/architecture.md` only when changing schema, chunking, or data flow.
- When context is compacted, keep: the current task, failing test output, and the non-negotiables.
