---
paths:
  - "basic/**/*.py"
---
# Python conventions (basic/)

## Type hints (enforced: `mypy --strict`, ruff `ANN`)
- Annotate every function, method, parameter, and module-level constant, including the `-> None` return type.
- Use modern syntax: `list[str]`, `dict[str, int]`, `X | None`. Use PEP 695 `type` aliases and generics (`def first[T](xs: list[T]) -> T`). Don't use `typing.List`, `Optional`, or `Union`.
- No bare `Any`. If one is unavoidable, add `# type: ignore[<code>]  # reason: ...`.
- Closed sets: `StrEnum` or `Literal` (`CardNetwork`, `SourceType`).
- IDs: `NewType` (`DocId`, `ChunkId`, `QueryId`). Never pass raw `str` IDs across modules.
- Boundaries: Pydantic v2 models for API and LLM I/O, `TypedDict` for Weaviate property dicts, `Protocol` for injectable clients (retriever, LLM).
- Constants: `Final`. Immutable value objects: `@dataclass(frozen=True, slots=True)`.
- The package ships `py.typed`. Avoid `cast()`; narrow types with `isinstance` or guards.

## Structure
- Use the `src/` layout. Modules: `config`, `ingestion`, `retrieval`, `generation`, `api`. Dependencies flow `api → generation → retrieval`; `ingestion` stands alone.
- One `Settings(BaseSettings)` in `basic/config.py`. Inject it, never read `os.environ` directly.
- Create clients (Weaviate, OpenAI) once at app startup, inject them through FastAPI dependencies, and close them at shutdown.

## Async & I/O
- Request paths are `async`. Use `AsyncOpenAI` and the async Weaviate client. Never block the event loop.
- Every network call sets an explicit timeout.

## Errors
- Use a domain exception hierarchy rooted in `BasicRagError` (`RetrievalError`, `GenerationError`, `IngestionError`).
- Catch narrowly, and use `raise ... from e`. Never use `except Exception: pass`.
- The API maps domain errors to RFC 9457 problem responses. It never leaks stack traces or provider error bodies.

## Logging
- Use `structlog` with JSON output, and bind `query_id` per request. No `print()`.
- Log levels: `info` for lifecycle events, `warning` for degraded paths (e.g., a refusal), `error` for failures, with context.

## Style
- Use `ruff format` and `ruff check` (rules `E,F,I,B,UP,ANN,S,SIM`). Max line length is 100.
- Public functions get a one-line docstring that says *why*, not *what*.
- Keep functions under ~40 lines. Prefer pure functions; side effects belong at the edges.
