"""Provider-agnostic chat completion interface plus the grounded-answer hook."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from omniknow.models import Chunk

Role = Literal["system", "user", "assistant"]


class LLMError(RuntimeError):
    """Raised when a provider cannot produce a completion."""


@dataclass(frozen=True)
class Message:
    role: Role
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class Completion:
    content: str
    model: str
    usage: Usage = field(default_factory=Usage)


class LLMProvider(ABC):
    """Minimal chat-completion contract.

    ``compose`` turns a question and its allowed evidence into an answer that
    cites ``[doc#chunk]`` ids. The default implementation prompts the model; the
    offline mock overrides it with deterministic extractive answering.
    """

    name: str = "base"

    @abstractmethod
    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> Completion:
        """Return the assistant reply for the given conversation."""

    def compose(self, question: str, evidence: list[Chunk]) -> str:
        from omniknow.prompts import build_answer_messages

        return self.complete(build_answer_messages(question, evidence)).content.strip()
