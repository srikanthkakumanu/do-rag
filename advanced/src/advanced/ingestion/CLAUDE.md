# ingestion/

## Purpose
Turn approved policy documents into scrubbed **parent sections** and **child chunks**, upserted idempotently into `PolicySection` and `PolicyChunk`.

## Owns
- `loaders.py`: Markdown (front matter) and HTML/PDF (sidecar `<name>.meta`) to normalized text.
- `scrub.py`: PAN (Luhn, group-aligned spans) and PII redaction. `api/` reuses it for questions **and history**.
- `chunker.py`: `chunk(doc, ChunkSizes) -> (sections, children)`. Parents are heading sections (split only above `parent_max`); children are sentence or list-item windows with overlap.
- `metadata.py`: reason-code regex per network. `query/planner.py` reuses it.
- `store.py`: the `ChunkStore` protocol and `WeaviateChunkStore` for both collections.
- `pipeline.py`: orchestration, supersession, stale cleanup. `cli.py`: `advanced ingest`.

## Interface
```python
def chunk(doc: SourceDocument, sizes: ChunkSizes = DEFAULT_SIZES) -> tuple[list[Section], list[Chunk]]: ...
def ingest(paths: Sequence[Path], store: ChunkStore, *, sizes: ChunkSizes = DEFAULT_SIZES,
           dry_run: bool = False) -> IngestReport: ...
```

## Invariants
- Scrubbing runs before chunking, hashing, or any network call.
- Re-running identical input is a no-op for both collections (deterministic IDs + hashes).
- Every child's `parent_id` points to a parent of the same doc version, and parents are written first.
- The child `content_hash` covers `parent_id` plus content, so re-split sections re-link children.
- Older versions stay indexed. Their children get `superseded_on` = the next version's `effective_date`.
- Stale children and parents of the same version are deleted. `IngestReport` counts both.

## Don't
- Don't call OpenAI here (Weaviate vectorizes children server-side).
- Don't log chunk or section text.
- Don't make parents searchable or embed them.

## Test
- Unit: `tests/unit/ingestion/`: parent/child linkage, overlap, list splitting, hash re-linking, stale section cleanup (in-memory store).
- Integration: re-ingest reports zero writes; a child hit resolves to its full parent section.
