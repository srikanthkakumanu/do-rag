# ingestion/

## Purpose
Turn approved policy documents into scrubbed Weaviate chunks **and** grounded knowledge-graph facts, keeping both stores in step.

## Owns
- `loaders.py`, `scrub.py`, `metadata.py`, `chunker.py`: same contracts as `basic/` (heading-aware chunks, PAN/PII scrub first, reason-code regex).
- `store.py`: `ChunkStore` / `WeaviateChunkStore` (sync, typed props).
- `extract.py` + `prompts/extract_v{n}.md`: the `FactExtractor` protocol, `LLMFactExtractor` (fast model), `guard()`, `extract_all()` (bounded concurrency).
- `graph_store.py`: the `GraphStore` protocol and `Neo4jGraphStore` (write Cypher constants, one transaction per chunk).
- `pipeline.py`: `GraphSync`, `ingest()`, supersession. `cli.py`: `hybrid ingest [--dry-run] [--reextract]`.

## Interface
```python
def ingest(paths: Sequence[Path], store: ChunkStore, graph: GraphSync, *,
           dry_run: bool = False, reextract: bool = False) -> IngestReport: ...
class FactExtractor(Protocol):
    async def extract(self, chunk: Chunk) -> Extraction: ...   # facts, rejected, failed
```

## Invariants
- Order per changed chunk: extract, then **graph write, then Weaviate write**. A failure before Weaviate means the next run retries both.
- A failed extraction (`failed=True`) defers the chunk from both stores. `IngestReport.deferred > 0` makes the CLI exit non-zero.
- Unchanged chunks skip extraction. `--reextract` rebuilds their facts (graph only) after an extraction-prompt change.
- Only chunks with reason codes are sent to the LLM. Facts pass `guard()`: code in chunk, verbatim quote, days in quote, enum values.
- Supersession and stale deletes hit the graph and Weaviate in the same run, keyed by the same `chunk_id`.

## Don't
- Don't write graph facts without a quote, or store LLM text that isn't in the chunk.
- Don't log chunk text or quotes.
- Don't call the extractor from request paths.

## Test
- Unit: guard cases (`test_extract.py`); pipeline with `MemoryGraphStore` and `RegexExtractor` (facts written, unchanged skips extraction, failure defers, supersession, `--reextract`).
- Integration: re-ingest makes zero extractor calls; the graph honours supersession; no PAN in either store.
