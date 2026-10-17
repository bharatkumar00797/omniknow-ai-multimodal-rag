from __future__ import annotations

from omniknow.models import IDK, Chunk, Principal
from omniknow.verify import extract_citations, verify_answer

EMP = Principal(name="e", groups=["all-staff"])


def _chunk(cid: str, acl: list[str]) -> Chunk:
    return Chunk(id=cid, doc_id=cid.split("#")[0], title="T", modality="text", text="x", acl=acl)


def test_extract_citations_dedupes_in_order() -> None:
    assert extract_citations("a [b#1] c [d-e#22] [b#1] [Bad#1] [x]") == ["b#1", "d-e#22"]


def test_keeps_valid_drops_unknown_and_forbidden() -> None:
    evidence = [_chunk("ok#1", ["all-staff"]), _chunk("secret#1", ["hr"])]
    v = verify_answer("Fact [ok#1]. Leak [secret#1]. Made up [ghost#3].", evidence, EMP)
    assert v.valid == ["ok#1"]
    assert v.dropped == ["secret#1", "ghost#3"]
    assert v.text == "Fact [ok#1]. Leak . Made up ."
    assert v.grounded


def test_uncited_answer_becomes_idk() -> None:
    v = verify_answer("The answer is 42.", [_chunk("ok#1", ["all-staff"])], EMP)
    assert v.text == IDK and not v.grounded
