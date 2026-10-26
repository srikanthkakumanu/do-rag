"""Parent-child chunking. Parents = heading sections (sent to the LLM); children = small
sentence windows inside a parent (searched). Spec: `docs/architecture.md#chunking`."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

import tiktoken
from weaviate.util import generate_uuid5

from advanced.domain import Chunk, ChunkId, Section, SectionId, SourceDocument
from advanced.ingestion.metadata import extract_reason_codes

_HEADING: Final = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class ChunkSizes:
    parent_max: int = 1200
    child_max: int = 220
    child_overlap: int = 40


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def section_uuid(doc_id: str, version: str, index: int) -> SectionId:
    return SectionId(str(generate_uuid5(f"{doc_id}:{version}:s{index}")))


def chunk_uuid(doc_id: str, version: str, index: int) -> ChunkId:
    return ChunkId(str(generate_uuid5(f"{doc_id}:{version}:c{index}")))


DEFAULT_SIZES: Final = ChunkSizes()


@dataclass(frozen=True, slots=True)
class RawSection:
    path: str
    blocks: tuple[str, ...]


def split_sections(title: str, text: str) -> list[RawSection]:
    """Group paragraph blocks under their heading breadcrumb (`Title > H2 > H3`)."""
    stack: list[tuple[int, str]] = []
    sections: list[RawSection] = []
    current: list[str] = []
    buffer: list[str] = []

    def flush_block() -> None:
        if buffer:
            current.append("\n".join(buffer).strip())
            buffer.clear()

    def flush_section() -> None:
        flush_block()
        blocks = tuple(b for b in current if b)
        if blocks:
            sections.append(RawSection(" > ".join([title, *(h for _, h in stack)]), blocks))
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


def _units(block: str) -> list[str]:
    """Smallest splittable units: list items / table rows, or sentences of prose."""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if len(lines) > 1:
        return lines
    return [s for s in _SENTENCE_END.split(block) if s.strip()]


def pack(units: list[str], max_tokens: int, overlap_tokens: int, sep: str) -> list[str]:
    """Greedy-pack units up to `max_tokens`, carrying trailing units up to `overlap_tokens`."""
    windows: list[str] = []
    current: list[str] = []
    for unit in units:
        if current and count_tokens(sep.join([*current, unit])) > max_tokens:
            windows.append(sep.join(current))
            tail: list[str] = []
            for prev in reversed(current):
                if count_tokens(sep.join([prev, *tail])) > overlap_tokens:
                    break
                tail.insert(0, prev)
            current = [*tail, unit]
        else:
            current.append(unit)
    if current:
        windows.append(sep.join(current))
    return windows


def chunk(
    doc: SourceDocument, sizes: ChunkSizes = DEFAULT_SIZES
) -> tuple[list[Section], list[Chunk]]:
    """Turn a scrubbed document into parent sections and child chunks with stable IDs."""
    parents: list[Section] = []
    children: list[Chunk] = []
    for raw in split_sections(doc.doc_title, doc.text):
        for body in pack(list(raw.blocks), sizes.parent_max, 0, "\n\n"):
            p_index = len(parents)
            parent_content = f"{raw.path}\n\n{body}"
            parent = Section(
                section_id=section_uuid(doc.doc_id, doc.version, p_index),
                doc_id=doc.doc_id,
                version=doc.version,
                section_path=raw.path,
                section_index=p_index,
                effective_date=doc.effective_date,
                content=parent_content,
                content_hash=_sha(parent_content),
            )
            parents.append(parent)
            units = [u for block in body.split("\n\n") for u in _units(block)]
            for window in pack(units, sizes.child_max, sizes.child_overlap, "\n"):
                c_index = len(children)
                content = f"{raw.path}\n\n{window}"
                children.append(
                    Chunk(
                        chunk_id=chunk_uuid(doc.doc_id, doc.version, c_index),
                        parent_id=parent.section_id,
                        doc_id=doc.doc_id,
                        doc_title=doc.doc_title,
                        version=doc.version,
                        section_path=raw.path,
                        chunk_index=c_index,
                        source_type=doc.source_type,
                        card_network=doc.card_network,
                        reason_codes=extract_reason_codes(content, doc.card_network),
                        jurisdiction=doc.jurisdiction,
                        effective_date=doc.effective_date,
                        content=content,
                        # parent_id in the hash: a re-split section re-links its children
                        content_hash=_sha(f"{parent.section_id}\n{content}"),
                    )
                )
    return parents, children
