"""Request and response schemas for the HTTP API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from omniknow.agent import MAX_QUESTION_CHARS
from omniknow.evals import EvalReport
from omniknow.models import Answer, Modality

PRINCIPAL_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,31}$"
PrincipalName = Annotated[str, Field(min_length=1, max_length=32, pattern=PRINCIPAL_PATTERN)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AskIn(_Request):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    principal: PrincipalName
    provider: Literal["mock", "configured"] | None = None


class SearchIn(_Request):
    query: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    principal: PrincipalName
    k: int = Field(default=5, ge=1, le=20)


class SourceOut(BaseModel):
    """A cited chunk as the caller is allowed to see it."""

    chunk_id: str
    doc_id: str
    title: str
    modality: Modality
    locator: str
    text: str


class AskOut(BaseModel):
    answer: Answer
    sources: list[SourceOut]
    access_mode: str
    simulated: bool


class HitOut(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    modality: Modality
    locator: str
    score: float
    coverage: float
    bm25_rank: int | None = None
    vector_rank: int | None = None
    flagged: bool
    text: str


class SearchOut(BaseModel):
    query: str
    principal: str
    hits: list[HitOut]
    simulated: bool


class DocumentOut(BaseModel):
    id: str
    title: str
    modality: Modality
    tags: list[str]
    acl: list[str]
    chunks: int


class DocumentListOut(BaseModel):
    principal: str
    groups: list[str]
    total_documents: int
    documents: list[DocumentOut]


class PrincipalOut(BaseModel):
    name: str
    groups: list[str]
    visible_documents: int


class PrincipalListOut(BaseModel):
    principals: list[PrincipalOut]


class EvalOut(BaseModel):
    report: EvalReport
    provider: str
    corpus: str
    simulated: bool


class ConfigOut(BaseModel):
    version: str
    access_mode: str
    auth_required: bool
    authenticated: bool
    provider: str
    providers: list[str]
    corpus: str
    documents: int
    principals: list[str]
    default_principal: str
    examples: list[dict[str, str]]
    simulated: bool


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    documents: int
    chunks: int
