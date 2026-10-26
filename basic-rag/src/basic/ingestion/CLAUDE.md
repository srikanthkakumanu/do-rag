# ingestion/

## Purpose
Turn approved policy documents into clean, scrubbed, idempotently upserted `PolicyChunk` objects.

## Owns
- `loaders.py`: Markdown (front matter) and HTML/PDF (sidecar `<name>.meta`) to normalized text, keeping headings.
- `scrub.py`: PAN (Luhn, group-aligned spans) and PII redaction. `api/` reuses it for queries; never duplicate it.
- `chunker.py`: heading-aware splitting with breadcrumbs and sentence overlap (spec in `docs/architecture.md#chunking`).
- `metadata.py`: reason-code regex per network.
- `store.py`: the `ChunkStore` protocol and `WeaviateChunkStore` (sync client, typed `PolicyChunkProps`).
- `pipeline.py`: orchestration and version supersession. `cli.py`: the `basic ingest` entry point.

## Interface
```python
def scrub(text: str) -> ScrubResult: ...  # (clean_text, redaction_count)
def chunk(doc: SourceDocument) -> list[Chunk]: ...
def ingest(paths: Sequence[Path], store: ChunkStore, *, dry_run: bool = False) -> IngestReport: ...
```
Ingestion is an offline batch job, so it uses the sync client; request paths stay async.

## Invariants
- Scrubbing runs **before** chunking, hashing, or any network call. Unscrubbed text never leaves this process.
- The same input file, version, and config produce the same chunk UUIDs and `content_hash`, so re-runs are no-ops.
- Every version of a `doc_id` stays indexed. Each version's `superseded_on` equals the next version's `effective_date` (the latest gets `NOT_SUPERSEDED`), so future-dated versions can be pre-loaded.
- A document missing `doc_id`, `version`, or `effective_date` is rejected, not guessed.
- `IngestReport` counts files, created/updated/skipped/deleted/failed chunks, and redactions. The CLI exits non-zero on any failure.

## Don't
- Don't call OpenAI directly. Weaviate vectorizes server-side.
- Don't log chunk text; log `doc_id` and counts only.
- Don't add LLM-based chunking or summarization (that's an `advanced-rag/` concern).

## Test
- Unit: `tests/unit/ingestion/` with an in-memory `ChunkStore`.
- Integration: re-ingesting the corpus reports 0 created/updated/deleted, and no PAN reaches the index.
