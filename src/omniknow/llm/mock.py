"""Deterministic offline provider used by default, in demos, and in tests.

``compose`` is extractive: it splits the allowed evidence into sentences and
greedily picks the ones that cover the most still-unanswered query terms
(weighted by rarity), citing each sentence's chunk id. It never writes text
that is not in the evidence, so its answers are grounded by construction.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from omniknow.llm.base import Completion, LLMProvider, Message, Usage
from omniknow.models import IDK, Chunk
from omniknow.retrieval import tokenize

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])|\n+")
MAX_SENTENCES = 3
MIN_GAIN = 0.2  # first sentence
MIN_FOLLOW_UP_GAIN = 0.3  # each extra sentence must add real coverage


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text) if len(s.strip()) > 3]


class MockProvider(LLMProvider):
    name = "mock"

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> Completion:
        joined = " ".join(m.content for m in messages)
        content = "Mock provider: use compose() for grounded extractive answers."
        return Completion(
            content=content,
            model="mock-omniknow-1",
            usage=Usage(prompt_tokens=len(joined) // 4, completion_tokens=len(content) // 4),
        )

    def compose(self, question: str, evidence: list[Chunk]) -> str:
        terms = set(tokenize(question))
        if not terms or not evidence:
            return IDK
        candidates: list[tuple[str, str, set[str]]] = []
        df: Counter[str] = Counter()
        for chunk in evidence:
            labels = {chunk.title.lower(), chunk.context.lower()}
            for sentence in split_sentences(chunk.text):
                if sentence.lower().rstrip(".") in labels:
                    continue  # a bare title / heading is context, not an answer
                toks = set(tokenize(sentence))
                candidates.append((chunk.id, sentence, toks))
                df.update(toks)
        n = max(len(candidates), 1)
        weight = {t: math.log(1 + n / (1 + df.get(t, 0))) for t in terms}
        total = sum(weight.values())
        remaining = set(terms)
        picked: list[tuple[str, str]] = []
        for _ in range(MAX_SENTENCES):
            best: tuple[float, int] | None = None
            for pos, (_cid, _sentence, toks) in enumerate(candidates):
                gain = sum(weight[t] for t in remaining & toks) / total
                if best is None or gain > best[0]:
                    best = (gain, pos)
            floor = MIN_FOLLOW_UP_GAIN if picked else MIN_GAIN
            if best is None or best[0] < floor:
                break
            cid, sentence, toks = candidates.pop(best[1])
            picked.append((cid, sentence))
            remaining -= toks
            if not remaining:
                break
        if not picked:
            return IDK
        return " ".join(f"{sentence.rstrip()} [{cid}]" for cid, sentence in picked)
