"""Heading-aware chunking with breadcrumbs. Spec: `docs/architecture.md#chunking`."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

import tiktoken
from weaviate.util import generate_uuid5

from hybrid.domain import Chunk, ChunkId, SourceDocument
from hybrid.ingestion.metadata import extract_reason_codes

TARGET_MIN_TOKENS: Final = 400
TARGET_MAX_TOKENS: Final = 600
OVERLAP_TOKENS: Final = 90  # ~15% of the max
_HEADING: Final = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


@dataclass(frozen=True, slots=True)
class Section:
    path: str
    blocks: tuple[str, ...]


def chunk_uuid(doc_id: str, version: str, chunk_index: int) -> ChunkId:
    """Deterministic object ID so re-ingesting the same input is a no-op."""
    return ChunkId(str(generate_uuid5(f"{doc_id}:{version}:{chunk_index}")))


def _is_atomic(block: str) -> bool:
    """Tables and lists must never be split."""
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    return bool(lines) and all(
        ln.startswith(("|", "-", "*", "+")) or re.match(r"^\d+[.)]\s", ln) for ln in lines
    )


def split_sections(title: str, text: str) -> list[Section]:
    """Group paragraph blocks under their heading breadcrumb (`Title > H2 > H3`)."""
    stack: list[tuple[int, str]] = []
    sections: list[Section] = []
    current: list[str] = []
    buffer: list[str] = []

    def path() -> str:
        return " > ".join([title, *(h for _, h in stack)])

    def flush_block() -> None:
        if buffer:
            current.append("\n".join(buffer).strip())
            buffer.clear()

    def flush_section() -> None:
        flush_block()
        blocks = tuple(b for b in current if b)
        if blocks:
            sections.append(Section(path=path(), blocks=blocks))
        current.clear()

    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            flush_section()
            level, name = len(heading.group(1)), heading.group(2).strip()
            if level == 1 and not stack and name == title:
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, name))
        elif not line.strip():
            flush_block()
        else:
            buffer.append(line.rstrip())
    flush_section()
    return sections


def _split_oversized(block: str) -> list[str]:
    """Split a long prose block on sentence boundaries; atomic blocks stay whole."""
    if _is_atomic(block) or count_tokens(block) <= TARGET_MAX_TOKENS:
        return [block]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(block):
        candidate = f"{current} {sentence}".strip()
        if current and count_tokens(candidate) > TARGET_MAX_TOKENS:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _tail_overlap(unit: str) -> str | None:
    """Trailing sentences of a prose unit, up to ~15% of the max; never part of a table."""
    if _is_atomic(unit):
        return None
    tail: list[str] = []
    for sentence in reversed(_SENTENCE_END.split(unit)):
        if count_tokens(" ".join([sentence, *tail])) > OVERLAP_TOKENS:
            break
        tail.insert(0, sentence)
    return " ".join(tail) or None


def pack_blocks(blocks: tuple[str, ...]) -> list[list[str]]:
    """Greedy-pack blocks up to the max, carrying ~15% tail overlap into the next chunk."""
    units = [piece for block in blocks for piece in _split_oversized(block)]
    groups: list[list[str]] = []
    current: list[str] = []
    for unit in units:
        if current and count_tokens("\n\n".join([*current, unit])) > TARGET_MAX_TOKENS:
            groups.append(current)
            overlap = _tail_overlap(current[-1])
            current = [overlap, unit] if overlap else [unit]
        else:
            current.append(unit)
    if current:
        groups.append(current)
    return groups


def chunk(doc: SourceDocument) -> list[Chunk]:
    """Turn a scrubbed document into breadcrumb-prefixed chunks with stable IDs."""
    chunks: list[Chunk] = []
    for section in split_sections(doc.doc_title, doc.text):
        for group in pack_blocks(section.blocks):
            body = "\n\n".join(group)
            content = f"{section.path}\n\n{body}"
            index = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=chunk_uuid(doc.doc_id, doc.version, index),
                    doc_id=doc.doc_id,
                    doc_title=doc.doc_title,
                    version=doc.version,
                    section_path=section.path,
                    chunk_index=index,
                    source_type=doc.source_type,
                    card_network=doc.card_network,
                    reason_codes=extract_reason_codes(content, doc.card_network),
                    jurisdiction=doc.jurisdiction,
                    effective_date=doc.effective_date,
                    content=content,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            )
    return chunks
