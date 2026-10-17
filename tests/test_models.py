from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniknow.models import DocumentSpec, Principal


def _spec(**overrides: object) -> DocumentSpec:
    data: dict[str, object] = {
        "id": "doc-1",
        "title": "Doc",
        "path": "a/b.md",
        "modality": "text",
        "acl": ["all-staff"],
    }
    data.update(overrides)
    return DocumentSpec.model_validate(data)


def test_valid_spec_normalises_groups() -> None:
    spec = _spec(acl=["All-Staff", "all-staff", "finance"])
    assert spec.acl == ["all-staff", "finance"]


@pytest.mark.parametrize("bad", ["Doc 1", "../x", "", "a" * 70])
def test_rejects_bad_ids(bad: str) -> None:
    with pytest.raises(ValidationError):
        _spec(id=bad)


@pytest.mark.parametrize("path", ["/etc/passwd", "../secret.md", "a/../../b.md", "\\\\share"])
def test_rejects_escaping_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        _spec(path=path)


def test_rejects_unknown_modality_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _spec(modality="video")
    with pytest.raises(ValidationError):
        _spec(owner="x")


def test_acl_required() -> None:
    with pytest.raises(ValidationError):
        _spec(acl=[])


def test_principal_always_has_public() -> None:
    p = Principal(name="x", groups=["engineering"])
    assert p.groups == ["public", "engineering"]
    with pytest.raises(ValidationError):
        Principal(name="x", groups=["bad group!"])
