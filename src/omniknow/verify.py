"""Answer verification: every citation must exist and point at allowed evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

from omniknow.acl import can_read
from omniknow.models import IDK, Chunk, Principal

CITATION_RE = re.compile(r"\[([a-z0-9][a-z0-9-]{0,63}#\d{1,4})\]")


@dataclass(frozen=True)
class Verification:
    text: str
    valid: list[str]
    dropped: list[str]

    @property
    def grounded(self) -> bool:
        return bool(self.valid)


def extract_citations(text: str) -> list[str]:
    seen: list[str] = []
    for cid in CITATION_RE.findall(text):
        if cid not in seen:
            seen.append(cid)
    return seen


def verify_answer(text: str, evidence: list[Chunk], principal: Principal) -> Verification:
    """Strip citations that were not in the evidence set or that the caller cannot read.

    If no valid citation survives, the answer is replaced by the "I don't know"
    message: an uncited answer is treated as ungrounded.
    """
    allowed = {c.id: c for c in evidence}
    valid: list[str] = []
    dropped: list[str] = []
    for cid in extract_citations(text):
        chunk = allowed.get(cid)
        if chunk is not None and can_read(chunk.acl, principal):
            valid.append(cid)
        else:
            dropped.append(cid)
    cleaned = text
    for cid in dropped:
        cleaned = cleaned.replace(f"[{cid}]", "")
    cleaned = " ".join(cleaned.split())
    if not valid:
        return Verification(text=IDK, valid=[], dropped=dropped)
    return Verification(text=cleaned, valid=valid, dropped=dropped)
