"""The digest of the loaded lessons: a derived file, `rules-digest.json`, in the plugin's data folder.

It holds, per topic, a heading and one line per lesson. It never lives in a record. A caller finds the data folder
with `mem.data_dir(os.environ)`; `read` and `write` take it as an argument.

Shape: {"topics": {topic: {"heading": str, "of": str, "lines": {handle: {"text": str, "of": str, "under": str}}}}}
`of` fingerprints what the text was written from; `under` fingerprints the heading a line was written under.
A text is fresh only while its fingerprint still matches (C88 to C90).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

import records
import rules

FILE = "rules-digest.json"
HEADING_LIMIT = 80
MIN_LESSONS = 2  # a topic is digested only with at least this many ready lessons


def _print(*parts: str) -> str:
    """The first 16 hexadecimal characters of the SHA-256 of the parts, each with whitespace collapsed, joined by NUL."""
    text = "\0".join(" ".join((p or "").split()) for p in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def line_print(m: records.Memory) -> str:
    """Hashes the claim and the short form of the lesson; nothing else (not log, versions or topic)."""
    return _print(m.claim, m.short or "")


def heading_print(lessons: Sequence[records.Memory]) -> str:
    """Hashes the lessons' handles and claims, sorted by handle, so the order of the lessons does not matter."""
    return _print(*(part for m in sorted(lessons, key=lambda m: m.handle) for part in (m.handle, m.claim)))


def _strings(d, *keys) -> bool:
    return isinstance(d, dict) and all(isinstance(d.get(k), str) for k in keys)


def read(data: Path | None) -> dict:
    """The file's content; anything missing or wrong reads as empty, entry by entry, and never raises."""
    out: dict = {"topics": {}}
    try:
        raw = json.loads((Path(data) / FILE).read_text(encoding="utf-8"))
        topics = raw["topics"]
        if not isinstance(topics, dict):
            return out
        for topic, entry in topics.items():
            if not isinstance(topic, str) or not _strings(entry, "heading", "of") or not isinstance(entry.get("lines"), dict):
                continue
            lines = {h: dict(v) for h, v in entry["lines"].items()
                     if isinstance(h, str) and _strings(v, "text", "of", "under")}
            out["topics"][topic] = {"heading": entry["heading"], "of": entry["of"], "lines": lines}
    except Exception:
        pass
    return out


def write(data: Path, digest: dict) -> None:
    """Writes the file through a temporary file in the same folder, then renames it into place."""
    data = Path(data)
    data.mkdir(parents=True, exist_ok=True)
    tmp = data / f"{FILE}.{os.getpid()}.tmp"
    try:
        tmp.write_text(json.dumps(digest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, data / FILE)
    finally:
        tmp.unlink(missing_ok=True)


def topics_of(global_lessons: Sequence[records.Memory], today: datetime.date) -> dict[str, list[records.Memory]]:
    """Ready global lessons (loaded, or left as over the limit or index only) by topic, topics with two or more."""
    choice = rules.choose([], global_lessons, today)
    ready = [*choice.loaded, *(m for m, why in choice.left if why in (rules.OVER, rules.INDEX))]
    groups: dict[str, list[records.Memory]] = {}
    for m in ready:
        if m.topic:
            groups.setdefault(m.topic, []).append(m)
    return {t: ls for t, ls in groups.items() if len(ls) >= MIN_LESSONS}


def heading(digest: dict, topic: str, lessons: Sequence[records.Memory]) -> str | None:
    """The stored heading when it was written for exactly these lessons and claims, else None."""
    entry = digest.get("topics", {}).get(topic)
    return entry["heading"] if entry and entry["of"] == heading_print(lessons) else None


def line(digest: dict, topic: str, m: records.Memory, lessons: Sequence[records.Memory]) -> str | None:
    """The stored text when it matches the lesson, was written under the stored heading, and that heading is fresh."""
    if heading(digest, topic, lessons) is None:
        return None
    entry = digest["topics"][topic]
    stored = entry["lines"].get(m.handle)
    return stored["text"] if stored and stored["of"] == line_print(m) and stored["under"] == entry["of"] else None
