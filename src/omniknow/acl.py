"""Document-level access control, applied before any retrieval or scoring."""

from __future__ import annotations

from collections.abc import Iterable

from omniknow.models import Chunk, Document, Principal


def can_read(acl: Iterable[str], principal: Principal) -> bool:
    groups = set(principal.groups)
    return any(group in groups for group in acl)


def visible_documents(docs: Iterable[Document], principal: Principal) -> list[Document]:
    return [d for d in docs if can_read(d.spec.acl, principal)]


def visible_chunks(chunks: Iterable[Chunk], principal: Principal) -> list[Chunk]:
    return [c for c in chunks if can_read(c.acl, principal)]
