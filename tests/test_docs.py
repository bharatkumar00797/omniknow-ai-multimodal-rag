"""The README stays in sync with the configuration and the shipped screenshots."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_documents_every_env_var() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^(OMNIKNOW_[A-Z_]+)=", example, re.M))
    assert documented
    missing = sorted(v for v in documented if f"`{v}`" not in README)
    assert not missing, f"README configuration table misses {missing}"


def test_readme_images_exist() -> None:
    images = re.findall(r"\]\((docs/screenshots/[^)]+)\)", README)
    assert len(images) >= 5
    for rel in images:
        assert (ROOT / rel).is_file(), rel


def test_readme_has_diagrams_and_security_model() -> None:
    assert README.count("```mermaid") == 2
    assert "## Security model" in README
    assert "Residual risks" in README
