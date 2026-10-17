"""Runtime configuration from OMNIKNOW_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean (true/false), got {raw!r}")


@dataclass(frozen=True)
class Settings:
    provider: str = "mock"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout: float = 60.0
    top_k: int = 5
    min_evidence: float = 0.35
    corpus_dir: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        top_k = env_int("OMNIKNOW_TOP_K", cls.top_k)
        min_evidence = env_float("OMNIKNOW_MIN_EVIDENCE", cls.min_evidence)
        if not 1 <= top_k <= 20:
            raise ValueError("OMNIKNOW_TOP_K must be between 1 and 20")
        if not 0.0 <= min_evidence <= 1.0:
            raise ValueError("OMNIKNOW_MIN_EVIDENCE must be between 0 and 1")
        return cls(
            provider=os.getenv("OMNIKNOW_PROVIDER", "mock").strip().lower(),
            base_url=os.getenv("OMNIKNOW_BASE_URL", cls.base_url),
            api_key=os.getenv("OMNIKNOW_API_KEY", ""),
            model=os.getenv("OMNIKNOW_MODEL", cls.model),
            timeout=env_float("OMNIKNOW_TIMEOUT", cls.timeout),
            top_k=top_k,
            min_evidence=min_evidence,
            corpus_dir=os.getenv("OMNIKNOW_CORPUS_DIR", "").strip(),
        )
