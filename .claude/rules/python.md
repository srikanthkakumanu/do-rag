---
paths:
  - "basic/**/*.py"
  - "advanced/**/*.py"
  - "hybrid/**/*.py"
---
# Python conventions (all variants)

`<pkg>` is the variant's package: `basic`, `advanced`, or `hybrid`.

## Type hints (enforced: `mypy --strict`, ruff `ANN`)
- Annotate every function, method, parameter, and module-level constant, including the `-> None` return type.
- Use modern syntax: `list[str]`, `X | None`. Use PEP 695 `type` aliases and generics (`def first[T](xs: list[T]) -> T`). Don't use `typing.List`, `Optional`, or `Union`.
- No bare `Any`. If one is unavoidable, add `# type: ignore[<code>]  # reason: ...`.
- Closed sets: `StrEnum` or `Literal` (`CardNetwork`, `SourceType`).
- IDs: `NewType` (`DocId`, `ChunkId`, ...). Never pass raw `str` IDs across modules.
- Boundaries: Pydantic v2 models for API and LLM I/O, `TypedDict` for store property dicts, `Protocol` for injectable clients.
- Constants: `Final`. Value objects: `@dataclass(frozen=True, slots=True)`.
- Each package ships `py.typed`. Avoid `cast()`; narrow types with `isinstance` or guards.

## Structure
- `src/<pkg>/` layout. Shared types live in `domain.py`, settings in `config.py`, store plumbing in `vectordb.py` (plus `graphdb.py` in hybrid).
- One `Settings(BaseSettings)`, loaded from the variant's own `.env` by absolute path. Inject it; never read `os.environ`.
- Create clients once at startup, inject them through FastAPI dependencies, and close them at shutdown.
- Never import across variants.

## Async & I/O
- Request paths are `async`. Ingestion is an offline batch job and may use sync clients.
- Every network call sets an explicit timeout.

## Errors
- Use one domain exception root per variant (`<Pkg>RagError`), with `IngestionError`, `RetrievalError`, and `GenerationError` under it.
- Catch narrowly, and use `raise ... from e`. Never use `except Exception: pass`.
- The API maps domain errors to RFC 9457 problem responses. It never leaks stack traces or provider error bodies.
- An optional LLM step (planner, reranker, extractor) degrades gracefully, logs a `warning`, and never takes the request down.

## Logging
- Use `structlog` JSON, with `query_id` bound per request. No `print()` outside CLI summaries.
- Levels: `info` for lifecycle events, `warning` for degraded paths and refusals, `error` for failures.

## Style
- `ruff format` and `ruff check` (rules `E,F,I,B,UP,ANN,S,SIM`), max line length 100. Markdown is excluded from ruff.
- Public functions get a one-line docstring that says *why*. Keep functions under ~40 lines; side effects belong at the edges.
