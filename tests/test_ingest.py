from __future__ import annotations

import json
from pathlib import Path

import pytest

from omniknow.ingest import (
    PAGE_BREAK,
    CorpusError,
    get_principal,
    load_corpus,
    sanitize,
)
from omniknow.models import Document


def test_packaged_corpus_covers_all_modalities(docs: list[Document]) -> None:
    assert len(docs) == 9
    assert {d.spec.modality for d in docs} == {"text", "table", "pdf", "image"}


def test_pdf_pages_extracted(docs: list[Document]) -> None:
    pdf = next(d for d in docs if d.id == "x200-datasheet")
    pages = pdf.text.split(PAGE_BREAK)
    assert len(pages) == 2
    assert "Battery life: 9 hours" in pages[0]
    assert "ISO 3691-4" in pages[1]


def test_image_sidecar_becomes_searchable_text(docs: list[Document]) -> None:
    img = next(d for d in docs if d.id == "office-floorplan")
    assert img.metadata["image"] == "office-floorplan.png"
    assert "Caption:" in img.text and "Text in image:" in img.text


def test_table_metadata(docs: list[Document]) -> None:
    table = next(d for d in docs if d.id == "q3-revenue")
    assert table.metadata["rows"] == "5"
    assert table.metadata["columns"].startswith("region")


def test_sanitize_strips_control_chars() -> None:
    assert sanitize("a\x00b\x1bc\r\nd\fe") == "abc\nd\fe"


def _write_corpus(tmp: Path, docs: list[dict[str, object]], files: dict[str, str]) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(text, encoding="utf-8")
    (tmp / "manifest.json").write_text(json.dumps({"documents": docs}), encoding="utf-8")
    return tmp


def test_custom_corpus_loads(tmp_path: Path) -> None:
    root = _write_corpus(
        tmp_path,
        [{"id": "n", "title": "N", "path": "n.md", "modality": "text", "acl": ["public"]}],
        {"n.md": "# N\n\nhello world"},
    )
    assert load_corpus(root)[0].text.startswith("# N")


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "link.md").symlink_to(outside)
    _write_corpus(
        root,
        [{"id": "l", "title": "L", "path": "link.md", "modality": "text", "acl": ["public"]}],
        {},
    )
    with pytest.raises(CorpusError, match="escapes"):
        load_corpus(root)


def test_missing_and_duplicate_and_empty(tmp_path: Path) -> None:
    spec = {"id": "a", "title": "A", "path": "a.md", "modality": "text", "acl": ["public"]}
    with pytest.raises(CorpusError, match="missing"):
        load_corpus(_write_corpus(tmp_path / "1", [spec], {}))
    with pytest.raises(CorpusError, match="duplicate"):
        load_corpus(_write_corpus(tmp_path / "2", [spec, spec], {"a.md": "x"}))
    with pytest.raises(CorpusError, match="empty"):
        load_corpus(_write_corpus(tmp_path / "3", [spec], {"a.md": "  \n"}))
    with pytest.raises(CorpusError, match="no manifest"):
        load_corpus(tmp_path / "nothing")


def test_bad_image_sidecar(tmp_path: Path) -> None:
    spec = {"id": "i", "title": "I", "path": "i.json", "modality": "image", "acl": ["public"]}
    with pytest.raises(CorpusError, match="no caption"):
        load_corpus(_write_corpus(tmp_path, [spec], {"i.json": "{}"}))


def test_corrupt_pdf(tmp_path: Path) -> None:
    spec = {"id": "p", "title": "P", "path": "p.pdf", "modality": "pdf", "acl": ["public"]}
    with pytest.raises(CorpusError):
        load_corpus(_write_corpus(tmp_path, [spec], {"p.pdf": "not a pdf"}))


def test_unknown_principal() -> None:
    assert get_principal("engineer").groups == ["public", "all-staff", "engineering"]
    with pytest.raises(KeyError, match="unknown principal"):
        get_principal("root")
