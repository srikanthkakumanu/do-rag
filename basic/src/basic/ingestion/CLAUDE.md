# ingestion/

## Purpose
Turn approved policy documents into clean, scrubbed, idempotently upserted `PolicyChunk` objects.

## Owns
- `loaders.py`: Markdown, PDF, and HTML to normalized text, keeping headings.
- `scrub.py`: PAN (Luhn) and PII redaction. The query path in `api/` imports and reuses this; never duplicate it.
- `chunker.py`: heading-aware splitting with breadcrumbs (spec in `docs/architecture.md#chunking`).
- `metadata.py`: reason-code extraction per network, plus `effective_date` and `version` parsing.
- `pipeline.py`: orchestration. `cli.py`: the `basic ingest` entry point.

## Interface
```python
def scrub(text: str) -> ScrubResult: ...            # (clean_text, redaction_count)
def chunk(doc: SourceDocument) -> list[Chunk]: ...
async def ingest(paths: Sequence[Path], *, dry_run: bool = False) -> IngestReport: ...
```

## Invariants
- Scrubbing runs **before** chunking, hashing, or any network call. Unscrubbed text never leaves this process.
- The same input file, version, and config produce the same chunk UUIDs and `content_hash`, so re-runs are no-ops.
- A document missing `doc_id`, `version`, or `effective_date` is rejected, not guessed.
- `IngestReport` counts files, chunks (created / updated / skipped / failed), and redactions. The run exits non-zero on any failure.

## Don't
- Don't call OpenAI directly. Weaviate vectorizes server-side.
- Don't log chunk text; log `doc_id` and counts only.
- Don't add LLM-based chunking or summarization (that's an `advanced/` concern).

## Test
- Unit: `tests/unit/ingestion/`, covering the scrubber edge cases, chunk boundaries (tables and lists intact), and reason-code regex per network.
- Integration: ingest the same corpus twice and assert that the second run reports 0 created / 0 updated.
