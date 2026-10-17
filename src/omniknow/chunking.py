"""Modality-aware chunking.

Each modality keeps the structure a reader would use to cite it:

* text  - split on Markdown headings, then pack paragraphs up to ``MAX_CHARS``
* table - a header context line plus ``ROWS_PER_CHUNK`` rendered rows per chunk
* pdf   - one or more chunks per page, cited as ``page N``
* image - a single chunk built from caption / alt text / OCR text
"""

from __future__ import annotations

import csv
import io
import re

from omniknow.ingest import PAGE_BREAK
from omniknow.models import Chunk, Document

MAX_CHARS = 700
ROWS_PER_CHUNK = 3

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _pack(paragraphs: list[str], limit: int = MAX_CHARS) -> list[str]:
    packed: list[str] = []
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        while len(para) > limit:  # hard-split very long paragraphs on a word boundary
            cut = para.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            if current:
                packed.append(current)
                current = ""
            packed.append(para[:cut].strip())
            para = para[cut:].strip()
        if current and len(current) + 2 + len(para) > limit:
            packed.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        packed.append(current)
    return packed


def _text_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.split("\n"):
        match = _HEADING_RE.match(line)
        if match:
            sections.append((match.group(2), []))
        else:
            sections[-1][1].append(line)
    return [(title, "\n".join(lines)) for title, lines in sections]


def _chunk_text(doc: Document) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for heading, body in _text_sections(doc.text):
        paragraphs = re.split(r"\n\s*\n", body)
        context = (
            f"{doc.spec.title} - {heading}"
            if heading and heading != doc.spec.title
            else doc.spec.title
        )
        locator = f"section: {heading}" if heading else "intro"
        for piece in _pack(paragraphs):
            out.append((piece, context, locator))
    return out


def _chunk_table(doc: Document) -> list[tuple[str, str, str]]:
    rows = [r for r in csv.reader(io.StringIO(doc.text)) if any(c.strip() for c in r)]
    header = [h.strip() for h in rows[0]]
    body = rows[1:]
    context = f"Table: {doc.spec.title} (columns: {', '.join(header)})"
    out: list[tuple[str, str, str]] = []
    for start in range(0, len(body), ROWS_PER_CHUNK):
        group = body[start : start + ROWS_PER_CHUNK]
        lines = []
        for row in group:
            cells = [f"{h}: {v.strip()}" for h, v in zip(header, row, strict=False) if v.strip()]
            lines.append("; ".join(cells) + ".")
        locator = f"rows {start + 1}-{start + len(group)}"
        out.append(("\n".join(lines), context, locator))
    return out


def _chunk_pdf(doc: Document) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for number, page in enumerate(doc.text.split(PAGE_BREAK), start=1):
        lines = [ln.strip() for ln in page.split("\n") if ln.strip()]
        for piece in _pack(lines):
            out.append((piece, f"{doc.spec.title} - page {number}", f"page {number}"))
    return out


def _chunk_image(doc: Document) -> list[tuple[str, str, str]]:
    image = doc.metadata.get("image", "")
    locator = f"image: {image}" if image else "image"
    return [(doc.text, f"Image: {doc.spec.title}", locator)]


_CHUNKERS = {
    "text": _chunk_text,
    "table": _chunk_table,
    "pdf": _chunk_pdf,
    "image": _chunk_image,
}


def chunk_document(doc: Document) -> list[Chunk]:
    pieces = _CHUNKERS[doc.spec.modality](doc)
    return [
        Chunk(
            id=f"{doc.id}#{n}",
            doc_id=doc.id,
            title=doc.spec.title,
            modality=doc.spec.modality,
            text=text[:8_000],
            context=context[:400],
            acl=list(doc.spec.acl),
            locator=locator,
        )
        for n, (text, context, locator) in enumerate(pieces, start=1)
    ]


def chunk_corpus(docs: list[Document]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in docs:
        chunks.extend(chunk_document(doc))
    return chunks
