"""Prompt-injection guard for retrieved context.

Retrieved document text is data, never instructions. Every chunk is scanned
for injection patterns; flagged chunks are quarantined (reported, but not used
as evidence). Allowed chunks are wrapped in ``<untrusted-context>`` tags with
any look-alike delimiters neutralised so a document cannot close the fence.
"""

from __future__ import annotations

import re
from html import escape

from omniknow.models import Chunk, SecurityFlag

INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction-override",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,20}\b(previous|prior|above|earlier|all)\b"
            r".{0,20}\b(instructions?|rules|prompts?)\b",
            re.I | re.S,
        ),
    ),
    (
        "role-hijack",
        re.compile(r"\byou are now\b|\bdeveloper mode\b|\bact as (an? )?(admin|system)\b", re.I),
    ),
    (
        "prompt-exfiltration",
        re.compile(
            r"\b(reveal|print|show|repeat|leak)\b.{0,30}\b(system prompt|hidden instructions)\b",
            re.I | re.S,
        ),
    ),
    (
        "data-exfiltration",
        re.compile(
            r"\b(reveal|leak|send|exfiltrate|email)\b.{0,40}"
            r"\b(passwords?|api keys?|secrets?|credentials|salar(y|ies)|salary bands)\b",
            re.I | re.S,
        ),
    ),
    (
        "delimiter-spoof",
        re.compile(r"<\s*/?\s*(untrusted-context|system|assistant)\b", re.I),
    ),
)

_DELIMITER_RE = re.compile(r"<(\s*/?\s*)(untrusted-context|system|assistant)", re.I)


def scan(chunk: Chunk) -> list[SecurityFlag]:
    flags: list[SecurityFlag] = []
    for kind, pattern in INJECTION_PATTERNS:
        match = pattern.search(chunk.text)
        if match:
            excerpt = chunk.text[max(0, match.start() - 20) : match.end() + 20]
            flags.append(
                SecurityFlag(chunk_id=chunk.id, kind=kind, excerpt=" ".join(excerpt.split())[:200])
            )
    return flags


def neutralize(text: str) -> str:
    """Defang anything that looks like one of our prompt delimiters."""
    return _DELIMITER_RE.sub(lambda m: "&lt;" + m.group(1) + m.group(2), text)


def wrap(chunk: Chunk) -> str:
    attrs = (
        f'id="{escape(chunk.id)}" title="{escape(chunk.title)}" '
        f'modality="{chunk.modality}" locator="{escape(chunk.locator)}"'
    )
    return f"<untrusted-context {attrs}>\n{neutralize(chunk.text)}\n</untrusted-context>"
