"""The knowledge agent loop: decompose -> ACL-filtered hybrid retrieval -> guard ->
evidence gate -> compose -> verify citations -> assemble a cited Answer."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from omniknow.acl import visible_documents
from omniknow.chunking import chunk_corpus
from omniknow.config import Settings
from omniknow.guard import scan
from omniknow.ingest import load_corpus
from omniknow.llm import LLMProvider, MockProvider, build_provider
from omniknow.models import (
    IDK,
    Answer,
    Chunk,
    Citation,
    Document,
    Principal,
    SearchHit,
    SecurityFlag,
    TraceStep,
)
from omniknow.retrieval import Retriever, tokenize
from omniknow.verify import verify_answer

MAX_QUESTION_CHARS = 1_000
MAX_SUB_QUERIES = 4

_WH_START = re.compile(
    r"^(what|how|who|whom|where|when|which|why|is|are|was|were|does|do|did|can|could|should)\b",
    re.I,
)

ProgressHook = Callable[[str, str], None]


def decompose(question: str) -> list[str]:
    """Split a multi-part question into standalone sub-queries (deterministic).

    Splits on sentence-ending ``?`` / ``;`` and on ``and`` / ``also`` when the
    next clause starts a new question ("... and what is ..."), so phrases like
    "exits and assembly point" stay together.
    """
    parts: list[str] = []
    for piece in re.split(r"[?;]+", question):
        piece = piece.strip()
        if not piece:
            continue
        clauses = re.split(r",?\s+\b(?:and|also|plus)\b\s+(?=\S)", piece, flags=re.I)
        current = clauses[0]
        for clause in clauses[1:]:
            if _WH_START.match(clause):
                parts.append(current)
                current = clause
            else:
                current = f"{current} and {clause}"
        parts.append(current)
    cleaned = [p.strip(" ,.") for p in parts if tokenize(p)]
    return cleaned[:MAX_SUB_QUERIES] or [question.strip()]


@dataclass
class KnowledgeAgent:
    documents: list[Document]
    provider: LLMProvider = field(default_factory=MockProvider)
    top_k: int = 5
    min_evidence: float = 0.35

    def __post_init__(self) -> None:
        self.chunks: list[Chunk] = chunk_corpus(self.documents)
        self.by_id = {c.id: c for c in self.chunks}
        self.retriever = Retriever(self.chunks)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> KnowledgeAgent:
        settings = settings or Settings.from_env()
        return cls(
            documents=load_corpus(settings.corpus_dir or None),
            provider=build_provider(settings),
            top_k=settings.top_k,
            min_evidence=settings.min_evidence,
        )

    def visible(self, principal: Principal) -> list[Document]:
        return visible_documents(self.documents, principal)

    def search(self, query: str, principal: Principal, k: int | None = None) -> list[SearchHit]:
        return self.retriever.search(_clean_question(query), principal, k or self.top_k)

    def ask(
        self,
        question: str,
        principal: Principal,
        *,
        on_step: ProgressHook | None = None,
    ) -> Answer:
        question = _clean_question(question)
        trace: list[TraceStep] = []

        def step(name: str, detail: str) -> None:
            trace.append(TraceStep(step=name, detail=detail[:2_000]))
            if on_step:
                on_step(name, detail)

        visible = self.visible(principal)
        step("access", f"{len(visible)} documents visible to '{principal.name}'")
        sub_queries = decompose(question)
        step("decompose", " | ".join(sub_queries))

        flags: dict[str, SecurityFlag] = {}
        evidence: list[Chunk] = []
        answered: list[tuple[str, list[Chunk]]] = []
        unanswered: list[str] = []
        strengths: list[float] = []
        for sub in sub_queries:
            hits = self.search(sub, principal)
            safe: list[SearchHit] = []
            for hit in hits:
                if hit.flagged:
                    for flag in scan(hit.chunk):
                        flags.setdefault(f"{flag.chunk_id}:{flag.kind}", flag)
                else:
                    safe.append(hit)
            strong = [h for h in safe if h.coverage >= self.min_evidence]
            best = max((h.coverage for h in safe), default=0.0)
            step(
                "retrieve",
                f"{sub!r}: {len(hits)} hits, {len(hits) - len(safe)} quarantined, "
                f"best coverage {best:.2f} -> "
                + ", ".join(f"{h.chunk.id}({h.coverage:.2f})" for h in strong[:3]),
            )
            if not strong:
                unanswered.append(sub)
                continue
            chosen = [h.chunk for h in strong[:3]]
            strengths.append(best)
            answered.append((sub, chosen))
            for chunk in chosen:
                if chunk.id not in {c.id for c in evidence}:
                    evidence.append(chunk)
        if flags:
            step("guard", f"quarantined {len(flags)} injection pattern(s) in retrieved text")

        parts: list[str] = []
        for sub, chunks in answered:
            parts.append(self.provider.compose(sub, chunks))
        step("compose", f"provider={self.provider.name}, {len(answered)} sub-answer(s)")
        raw = " ".join(p for p in parts if p and p != IDK)
        verification = verify_answer(raw, evidence, principal) if raw else None
        valid = verification.valid if verification else []
        dropped = verification.dropped if verification else []
        step("verify", f"{len(valid)} valid citation(s), {len(dropped)} dropped")

        if not valid or verification is None:
            text = IDK
            grounded = False
            confidence: Literal["high", "medium", "low", "none"] = "none"
        else:
            text = verification.text
            if unanswered:
                text += " I don't know: " + "; ".join(unanswered) + "."
            grounded = True
            confidence = _confidence(min(strengths, default=0.0), partial=bool(unanswered))

        citations = [self._citation(cid, text) for cid in valid]
        return Answer(
            question=question,
            principal=principal.name,
            answer=text,
            citations=citations,
            sub_queries=sub_queries,
            grounded=grounded,
            confidence=confidence,
            provider=self.provider.name,
            security_flags=list(flags.values()),
            dropped_citations=dropped,
            trace=trace,
        )

    def _citation(self, cid: str, text: str) -> Citation:
        chunk = self.by_id[cid]
        quote = ""
        marker = f"[{cid}]"
        end = text.find(marker)
        if end > 0:
            start = max(text.rfind("]", 0, end) + 1, 0)
            quote = text[start:end].strip()[:600]
        return Citation(
            chunk_id=cid,
            doc_id=chunk.doc_id,
            title=chunk.title,
            modality=chunk.modality,
            locator=chunk.locator,
            quote=quote,
        )


def _confidence(weakest: float, *, partial: bool) -> Literal["high", "medium", "low"]:
    """Confidence follows the weakest answered sub-query; partial answers are always low."""
    if partial or weakest < 0.5:
        return "low"
    return "high" if weakest >= 0.75 else "medium"


def _clean_question(question: str) -> str:
    question = " ".join(question.split())
    if not question:
        raise ValueError("question must not be empty")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"question longer than {MAX_QUESTION_CHARS} characters")
    return question
