"""Load Markdown, HTML, and PDF policy documents into normalized `SourceDocument`s.

Metadata comes from Markdown front matter (`---` block of `key: value` lines) or, for
HTML/PDF, from a sidecar file `<name>.meta` in the same `key: value` format.
"""

from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Final

from pypdf import PdfReader

from basic.domain import CardNetwork, DocId, SourceDocument, SourceType
from basic.errors import IngestionError

SUPPORTED_SUFFIXES: Final = frozenset({".md", ".html", ".htm", ".pdf"})
_REQUIRED: Final = ("doc_id", "version", "effective_date")
_FRONT_MATTER: Final = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def parse_key_values(block: str) -> dict[str, str]:
    """Parse simple `key: value` lines (no nesting) into a dict."""
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition(":")
            out[key.strip().lower()] = value.strip().strip('"').strip("'")
    return out


class _HtmlToMarkdown(HTMLParser):
    """Keep headings (as `#`), paragraphs, list items, and table rows; drop the rest."""

    _BLOCKS: Final = {"p", "div", "br", "tr", "table", "ul", "ol", "section"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")
        elif tag in self._BLOCKS:
            self.parts.append("\n\n" if tag in {"p", "div", "section", "table"} else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
        elif re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def _read_body(path: Path) -> tuple[str, dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".md":
        raw = path.read_text(encoding="utf-8")
        match = _FRONT_MATTER.match(raw)
        if not match:
            return raw, {}
        return raw[match.end() :], parse_key_values(match.group(1))
    sidecar = path.with_suffix(".meta")
    meta = parse_key_values(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
    if suffix in {".html", ".htm"}:
        parser = _HtmlToMarkdown()
        parser.feed(path.read_text(encoding="utf-8"))
        return parser.text(), meta
    if suffix == ".pdf":
        pages = [page.extract_text() or "" for page in PdfReader(str(path)).pages]
        return "\n\n".join(pages), meta
    raise IngestionError(f"unsupported file type: {path.name}")


def load_document(path: Path) -> SourceDocument:
    """Load one file. Rejects documents missing doc_id, version, or effective_date."""
    body, meta = _read_body(path)
    missing = [key for key in _REQUIRED if not meta.get(key)]
    if missing:
        raise IngestionError(f"{path.name}: missing required metadata {missing}")
    try:
        return SourceDocument(
            doc_id=DocId(meta["doc_id"]),
            doc_title=meta.get("title", path.stem),
            version=meta["version"],
            effective_date=date.fromisoformat(meta["effective_date"]),
            source_type=SourceType(meta.get("source_type", SourceType.INTERNAL_SOP)),
            card_network=CardNetwork(meta.get("card_network", CardNetwork.ALL)),
            jurisdiction=meta.get("jurisdiction", "global"),
            text=body.strip(),
        )
    except ValueError as e:
        raise IngestionError(f"{path.name}: invalid metadata ({e})") from e


def discover(paths: list[Path]) -> list[Path]:
    """Expand directories into supported files, sorted for deterministic runs."""
    found: list[Path] = []
    for p in paths:
        if p.is_dir():
            found.extend(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED_SUFFIXES)
        elif p.suffix.lower() in SUPPORTED_SUFFIXES:
            found.append(p)
    return sorted(set(found))
