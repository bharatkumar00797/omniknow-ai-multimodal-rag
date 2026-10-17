"""Configuration for the HTTP service, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from omniknow.config import env_bool, env_int

AccessMode = Literal["api-key", "dev", "public-demo"]


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class ApiSettings:
    """Service settings.

    Access modes:

    * keys configured (``OMNIKNOW_API_KEYS``) -> every ``/api`` call needs ``X-API-Key`` or a
      Bearer token; callers get the configured corpus (``OMNIKNOW_CORPUS_DIR``) and may use the
      configured LLM provider.
    * ``dev_mode`` -> no auth and full access; meant for ``localhost`` only.
    * neither -> public demo: anonymous callers only reach the packaged sample corpus with the
      offline mock provider, and every response is labelled ``simulated``.

    In every mode the principal (persona) is chosen from the packaged ``principals.json`` and
    the ACL filter runs on the server before retrieval.
    """

    api_keys: tuple[str, ...] = ()
    dev_mode: bool = False
    cors_origins: tuple[str, ...] = ()
    rate_limit_per_minute: int = 120
    ask_limit_per_minute: int = 20
    eval_limit_per_minute: int = 4
    trust_proxy: bool = False

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    @property
    def access_mode(self) -> AccessMode:
        if self.auth_enabled:
            return "api-key"
        return "dev" if self.dev_mode else "public-demo"

    @property
    def public_demo(self) -> bool:
        return self.access_mode == "public-demo"

    @classmethod
    def from_env(cls) -> ApiSettings:
        return cls(
            api_keys=_env_list("OMNIKNOW_API_KEYS"),
            dev_mode=env_bool("OMNIKNOW_DEV_MODE", False),
            cors_origins=_env_list("OMNIKNOW_CORS_ORIGINS"),
            rate_limit_per_minute=env_int("OMNIKNOW_RATE_LIMIT_PER_MINUTE", 120),
            ask_limit_per_minute=env_int("OMNIKNOW_ASK_LIMIT_PER_MINUTE", 20),
            eval_limit_per_minute=env_int("OMNIKNOW_EVAL_LIMIT_PER_MINUTE", 4),
            trust_proxy=env_bool("OMNIKNOW_TRUST_PROXY", False),
        )
