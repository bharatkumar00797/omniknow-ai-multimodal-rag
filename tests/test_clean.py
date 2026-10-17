"""Repository cleanliness: no attribution trailers, no embedded secrets."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Assembled so this file does not contain the phrases as contiguous literals.
_BAN_SNIPPETS = tuple(
    "".join(parts)
    for parts in (
        ("Gener", "ated by"),
        ("Co-authored", "-by"),
        ("[", "bot]"),
    )
)
_SECRET_PATTERNS = ("sk-proj-", "sk-ant-", "ghp_", "BEGIN RSA PRIVATE KEY")
_SKIP = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
_BINARY = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".pyc", ".so"}


def _texts() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix in _BINARY:
            continue
        if any(part in _SKIP for part in path.parts):
            continue
        try:
            out.append((path, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return out


def test_no_attribution_snippets() -> None:
    bad = [f"{p.relative_to(ROOT)}: {b}" for p, t in _texts() for b in _BAN_SNIPPETS if b in t]
    assert not bad, bad


def test_no_embedded_secrets() -> None:
    bad = [
        f"{p.relative_to(ROOT)}: {s}"
        for p, t in _texts()
        if p.name not in {"test_clean.py", ".env.example"}
        for s in _SECRET_PATTERNS
        if s in t
    ]
    assert not bad, bad
