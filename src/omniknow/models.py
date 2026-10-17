"""Strict domain models shared by ingest, retrieval, and the answer pipeline."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Modality = Literal["text", "table", "pdf", "image"]

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_GROUP_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

PUBLIC_GROUP = "public"
IDK = "I don't know based on the documents you have access to."


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_groups(groups: list[str]) -> list[str]:
    cleaned: list[str] = []
    for group in groups:
        g = group.strip().lower()
        if not _GROUP_RE.match(g):
            raise ValueError(f"invalid group name {group!r}")
        if g not in cleaned:
            cleaned.append(g)
    return cleaned


class DocumentSpec(_Strict):
    """One manifest entry describing a source file and who may read it."""

    id: str
    title: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=300)
    modality: Modality
    acl: list[str] = Field(min_length=1, max_length=16)
    tags: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _ID_RE.match(value):
            raise ValueError("document id must be lowercase letters, digits and dashes")
        return value

    @field_validator("acl")
    @classmethod
    def _acl(cls, value: list[str]) -> list[str]:
        return _check_groups(value)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"):
            raise ValueError("document path must be relative and stay inside the corpus")
        return value


class Document(_Strict):
    spec: DocumentSpec
    text: str = Field(max_length=500_000)
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.spec.id


class Chunk(_Strict):
    id: str  # "<doc-id>#<n>"
    doc_id: str
    title: str
    modality: Modality
    text: str = Field(min_length=1, max_length=8_000)
    context: str = Field(default="", max_length=400)  # heading / table header, indexed only
    acl: list[str]
    locator: str = ""  # e.g. "section: Paging", "rows 1-4", "page 2", "image"

    @property
    def searchable(self) -> str:
        return f"{self.context}\n{self.text}" if self.context else self.text


class Principal(_Strict):
    """Who is asking. Groups decide which documents are visible."""

    name: str = Field(min_length=1, max_length=64)
    groups: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("groups")
    @classmethod
    def _groups(cls, value: list[str]) -> list[str]:
        cleaned = _check_groups(value)
        if PUBLIC_GROUP not in cleaned:
            cleaned.insert(0, PUBLIC_GROUP)
        return cleaned


class SearchHit(_Strict):
    chunk: Chunk
    score: float  # reciprocal-rank-fused score, normalised to 0..1
    coverage: float  # idf-weighted share of query terms found in the chunk, 0..1
    bm25_rank: int | None = None
    vector_rank: int | None = None
    flagged: bool = False


class Citation(_Strict):
    chunk_id: str
    doc_id: str
    title: str
    modality: Modality
    locator: str = ""
    quote: str = Field(default="", max_length=600)


class SecurityFlag(_Strict):
    chunk_id: str
    kind: str
    excerpt: str = Field(max_length=200)


class TraceStep(_Strict):
    step: str
    detail: str = Field(max_length=2_000)


class Answer(_Strict):
    question: str
    principal: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    sub_queries: list[str] = Field(default_factory=list)
    grounded: bool
    confidence: Literal["high", "medium", "low", "none"]
    provider: str
    security_flags: list[SecurityFlag] = Field(default_factory=list)
    dropped_citations: list[str] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
