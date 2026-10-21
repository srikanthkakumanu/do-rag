# do-rag

RAG reference implementations for a payments use case: a **Dispute & Chargeback Policy Assistant**.

| Variant | Status | Stack |
|---|---|---|
| `basic/` | Instructions defined | Python 3.12, FastAPI, Weaviate (hybrid search), OpenAI |
| `advanced/` | Planned | – |
| `hybrid/` | Planned | – |

## Instruction layers (Claude Code)
```
CLAUDE.md                              repo-wide, always loaded
.claude/rules/security-compliance.md   PCI/PII, always loaded
basic/CLAUDE.md                        Basic RAG constitution (loaded in basic/)
.claude/rules/basic-*.md               path-scoped coding rules
basic/src/basic/<module>/CLAUDE.md     module contracts (loaded in that module)
basic/docs/architecture.md             read on demand
```
Every instruction file is 300–800 tokens. Only about 1k tokens load at startup.

## Setup
Copy `basic/.env.example` to `basic/.env` and add your OpenAI key. `.env` is git-ignored.
