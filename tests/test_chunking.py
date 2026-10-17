from __future__ import annotations

from omniknow.chunking import MAX_CHARS, chunk_document
from omniknow.models import Chunk, Document, DocumentSpec


def test_chunk_ids_are_unique_and_stable(chunks: list[Chunk]) -> None:
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    assert "benefits-overview#1" in ids and "x200-datasheet#2" in ids


def test_markdown_split_by_heading(chunks: list[Chunk]) -> None:
    paging = next(c for c in chunks if c.id == "incident-runbook#2")
    assert paging.locator == "section: Paging"
    assert paging.context == "Incident Response Runbook - Paging"
    assert "5 minutes" in paging.text


def test_table_rows_rendered_with_headers(chunks: list[Chunk]) -> None:
    table = [c for c in chunks if c.doc_id == "q3-revenue"]
    assert [c.locator for c in table] == ["rows 1-3", "rows 4-5"]
    assert "region: Asia Pacific; quarter: 2026-Q3; revenue_musd: 9.7" in table[0].text
    assert table[0].context.startswith("Table: Q3 2026 Revenue by Region (columns: region")


def test_pdf_chunks_cite_pages(chunks: list[Chunk]) -> None:
    assert [c.locator for c in chunks if c.doc_id == "x200-datasheet"] == ["page 1", "page 2"]


def test_image_single_chunk(chunks: list[Chunk]) -> None:
    img = [c for c in chunks if c.doc_id == "fleet-architecture"]
    assert len(img) == 1 and img[0].modality == "image"
    assert img[0].locator == "image: fleet-architecture.png"


def test_acl_copied_to_chunks(chunks: list[Chunk]) -> None:
    assert all(c.acl == ["hr"] for c in chunks if c.doc_id == "salary-bands")


def test_long_paragraph_hard_split() -> None:
    spec = DocumentSpec(id="long", title="Long", path="l.md", modality="text", acl=["public"])
    doc = Document(spec=spec, text="# Big\n\n" + "word " * 600)
    pieces = chunk_document(doc)
    assert len(pieces) > 1
    assert all(len(p.text) <= MAX_CHARS for p in pieces)
