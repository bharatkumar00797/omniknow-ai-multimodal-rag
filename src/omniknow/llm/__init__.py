"""LLM provider implementations and factory."""

from __future__ import annotations

from omniknow.config import Settings
from omniknow.llm.base import Completion, LLMError, LLMProvider, Message, Usage
from omniknow.llm.mock import MockProvider
from omniknow.llm.openai_compat import OpenAICompatibleProvider

__all__ = [
    "Completion",
    "LLMError",
    "LLMProvider",
    "Message",
    "MockProvider",
    "OpenAICompatibleProvider",
    "Usage",
    "build_provider",
]

OPENAI_COMPATIBLE = {"openai", "groq", "ollama", "openai-compatible"}

_DEFAULT_URLS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}


def build_provider(settings: Settings) -> LLMProvider:
    """Create the configured provider; the offline mock is the default."""
    if settings.provider in OPENAI_COMPATIBLE:
        base = settings.base_url
        if settings.provider in _DEFAULT_URLS and base == Settings.base_url:
            # Provider-sensible default when only OMNIKNOW_PROVIDER is set.
            base = _DEFAULT_URLS[settings.provider]
        provider = OpenAICompatibleProvider(
            base_url=base,
            model=settings.model,
            api_key=settings.api_key,
            timeout=settings.timeout,
        )
        provider.name = settings.provider
        return provider
    if settings.provider != "mock":
        raise ValueError(f"unknown provider {settings.provider!r} (use mock|openai|groq|ollama)")
    return MockProvider()
