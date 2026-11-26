"""The lookups of the digest: the fingerprints and the stored heading or line of a lesson, if still fresh.

Both `digest` and `rules` import this module, so neither imports the other back. `digest` re-exports the four public
names, so `digest.heading` and the others keep working."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from store.memory_model import Memory


def _print(*parts: str) -> str:
    """The first 16 hexadecimal characters of the SHA-256 of the parts, each with whitespace collapsed, joined by NUL."""
    text = "\0".join(" ".join((p or "").split()) for p in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def line_print(m: Memory) -> str:
    """Hashes the claim and the short form of the lesson; nothing else (not log, versions or topic)."""
    return _print(m.claim, m.short or "")


def heading_print(lessons: Sequence[Memory]) -> str:
    """Hashes the lessons' handles and claims, sorted by handle, so the order of the lessons does not matter."""
    return _print(
        *(part for m in sorted(lessons, key=lambda m: m.handle) for part in (m.handle, m.claim))
    )


def heading(digest: dict, topic: str, lessons: Sequence[Memory]) -> str | None:
    """The stored heading when it was written for exactly these lessons and claims, else None."""
    entry = digest.get("topics", {}).get(topic)
    return entry["heading"] if entry and entry["of"] == heading_print(lessons) else None


def line(digest: dict, topic: str, m: Memory, lessons: Sequence[Memory]) -> str | None:
    """The stored text when it matches the lesson, was written under the stored heading, and that heading is fresh."""
    if heading(digest, topic, lessons) is None:
        return None
    entry = digest["topics"][topic]
    stored = entry["lines"].get(m.handle)
    return (
        stored["text"]
        if stored and stored["of"] == line_print(m) and stored["under"] == entry["of"]
        else None
    )
