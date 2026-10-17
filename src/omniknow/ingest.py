"""Load a corpus manifest and parse each modality into a sanitized Document.

Supported modalities (all offline and deterministic):

* ``text``  - Markdown / plain text
* ``table`` - CSV (kept as raw CSV; the chunker renders rows)
* ``pdf``   - text PDFs via pypdf (pages joined with form feeds)
* ``image`` - a JSON sidecar with caption, alt text and OCR text, so images are
  searchable without a vision model
"""

from __future__ import annotations

import csv
import io
import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

from omniknow.models import Document, DocumentSpec, Principal

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DOCUMENTS = 500
PAGE_BREAK = "\f"

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")


class CorpusError(ValueError):
    """Raised when a corpus or one of its files is invalid."""


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="corpus", max_length=200)
    documents: list[DocumentSpec] = Field(min_length=1, max_length=MAX_DOCUMENTS)


def packaged_data_dir() -> Path:
    return Path(str(resources.files("omniknow") / "data"))


def default_corpus_dir() -> Path:
    return packaged_data_dir() / "corpus"


def sanitize(text: str) -> str:
    """Drop control characters (keeping newlines, tabs and page breaks) and normalise EOLs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", text)


def load_manifest(root: Path) -> Manifest:
    path = root / "manifest.json"
    if not path.is_file():
        raise CorpusError(f"no manifest.json in {root}")
    try:
        manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CorpusError(f"invalid manifest: {exc}") from exc
    ids = [d.id for d in manifest.documents]
    if len(ids) != len(set(ids)):
        raise CorpusError("duplicate document ids in manifest")
    return manifest


def _resolve_inside(root: Path, rel: str) -> Path:
    base = root.resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base):
        raise CorpusError(f"path escapes corpus: {rel}")
    if not target.is_file():
        raise CorpusError(f"missing file: {rel}")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise CorpusError(f"file too large (> {MAX_FILE_BYTES} bytes): {rel}")
    return target


def _parse_text(path: Path) -> tuple[str, dict[str, str]]:
    return path.read_text(encoding="utf-8", errors="replace"), {}


def _parse_table(path: Path) -> tuple[str, dict[str, str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows or not any(cell.strip() for cell in rows[0]):
        raise CorpusError(f"table has no header row: {path.name}")
    return raw, {"columns": ", ".join(c.strip() for c in rows[0]), "rows": str(len(rows) - 1)}


def _parse_pdf(path: Path) -> tuple[str, dict[str, str]]:
    try:
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:  # pypdf raises a variety of errors on malformed files
        raise CorpusError(f"could not read PDF {path.name}: {exc.__class__.__name__}") from exc
    return PAGE_BREAK.join(pages), {"pages": str(len(pages))}


def _parse_image(path: Path) -> tuple[str, dict[str, str]]:
    try:
        meta: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusError(f"invalid image sidecar {path.name}") from exc
    if not isinstance(meta, dict):
        raise CorpusError(f"image sidecar must be an object: {path.name}")
    fields = {k: str(meta.get(k, "")).strip() for k in ("image", "caption", "alt_text", "ocr_text")}
    if not (fields["caption"] or fields["alt_text"] or fields["ocr_text"]):
        raise CorpusError(f"image sidecar has no caption, alt_text or ocr_text: {path.name}")
    lines = []
    if fields["caption"]:
        lines.append(f"Caption: {fields['caption']}.")
    if fields["alt_text"]:
        lines.append(f"Description: {fields['alt_text']}")
    if fields["ocr_text"]:
        lines.append(f"Text in image: {fields['ocr_text']}")
    return "\n".join(lines), {"image": fields["image"]}


_PARSERS = {
    "text": _parse_text,
    "table": _parse_table,
    "pdf": _parse_pdf,
    "image": _parse_image,
}


def load_document(root: Path, spec: DocumentSpec) -> Document:
    path = _resolve_inside(root, spec.path)
    text, metadata = _PARSERS[spec.modality](path)
    text = sanitize(text).strip()
    if not text:
        raise CorpusError(f"document {spec.id} is empty")
    return Document(spec=spec, text=text, metadata=metadata)


def load_corpus(root: Path | str | None = None) -> list[Document]:
    base = Path(root) if root else default_corpus_dir()
    manifest = load_manifest(base)
    return [load_document(base, spec) for spec in manifest.documents]


def load_principals(path: Path | None = None) -> dict[str, Principal]:
    source = path or packaged_data_dir() / "principals.json"
    data: Any = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CorpusError("principals file must map names to group lists")
    return {
        str(name): Principal(name=str(name), groups=list(groups)) for name, groups in data.items()
    }


def get_principal(name: str) -> Principal:
    principals = load_principals()
    if name not in principals:
        known = ", ".join(sorted(principals))
        raise KeyError(f"unknown principal {name!r} (known: {known})")
    return principals[name]
