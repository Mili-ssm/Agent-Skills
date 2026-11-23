"""The digest of the loaded lessons: a derived file, `rules-digest.json`, in the plugin's data folder.

It holds, per topic, a heading and one line per lesson. It never lives in a record. A caller finds the data folder
with `mem.data_dir(os.environ)`; `read` and `write` take it as an argument.

Shape: {"topics": {topic: {"heading": str, "of": str, "lines": {handle: {"text": str, "of": str, "under": str}}}}}
`of` fingerprints what the text was written from; `under` fingerprints the heading a line was written under.
A text is fresh only while its fingerprint still matches (C88 to C90).
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import records
import rules
import shortcheck

FILE = "rules-digest.json"
HEADING_LIMIT = 80
MIN_LESSONS = 2  # a topic is digested only with at least this many ready lessons
DIGEST_ATTEMPTS = 2  # tries of one heading or one line before it is left alone
DIGEST_LIMIT = 30  # lessons one run asks lines for; a topic is never split


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


class Work(NamedTuple):
    topic: str
    lessons: list  # every ready lesson of the topic
    heading_state: str  # "keep" (the stored heading is fresh), "write", or "given_up" (its tries are spent)
    heading: str | None  # the stored text when the state is "keep"
    write: list  # lessons that need a line
    keep: dict  # handle -> stored text of the lessons whose line is still written from their claim and short form


def _heading_key(topic: str, lessons: Sequence[records.Memory]) -> str:
    return f"h:{topic}@{heading_print(lessons)}"


def _line_key(m: records.Memory, lessons: Sequence[records.Memory]) -> str:
    return f"l:{m.handle}@{line_print(m)}@{heading_print(lessons)}"


def _tries(state: Mapping, key: str) -> int:
    return state.get("tries", {}).get(key, 0)


def work(topics: Mapping[str, list], digest: dict, state: Mapping) -> list[Work]:
    """What one run asks for, by topic in the order of the names. Lessons without a valid short form get no line."""
    out: list[Work] = []
    asked = 0
    for topic in sorted(topics):
        if asked >= DIGEST_LIMIT:
            break
        lessons = list(topics[topic])
        kept_heading = heading(digest, topic, lessons)
        if kept_heading is not None:
            hstate = "keep"
        elif _tries(state, _heading_key(topic, lessons)) >= DIGEST_ATTEMPTS:
            continue
        else:
            hstate = "write"
        stored = digest.get("topics", {}).get(topic, {}).get("lines", {})
        to_write: list = []
        keep: dict = {}
        for m in lessons:
            if not records.valid_short(m.short):
                continue
            old = stored.get(m.handle)
            if old and old["of"] == line_print(m):
                keep[m.handle] = old["text"]
            elif _tries(state, _line_key(m, lessons)) < DIGEST_ATTEMPTS:
                to_write.append(m)
        if hstate == "keep" and not to_write:
            continue
        out.append(Work(topic, lessons, hstate, kept_heading, to_write, keep))
        asked += len(to_write)
    return out


def _one_line(text) -> str:
    return " ".join(str(text).split())


def blocks(works: Sequence[Work]) -> str:
    """What the writer reads. A kept heading prints `heading (keep): <text>`, one to write `heading: write`; a lesson prints only when it is
    written or kept; the header of a topic is a block of its own."""
    topics = []
    for w in works:
        parts = [f"topic: {_one_line(w.topic)}"]
        parts.append(f"heading (keep): {_one_line(w.heading)}" if w.heading_state == "keep" else "heading: write")
        items = ["\n".join(parts)]
        for m in w.lessons:
            if m in w.write or m.handle in w.keep:
                rows = [f"id: g:{m.handle}", f"do: {'write' if m in w.write else 'keep'}", f"claim: {_one_line(m.claim)}"]
                if m.context:
                    rows.append(f"context: {_one_line(m.context)}")
                rows.append(f"short: {_one_line(m.short)}")
                if m.handle in w.keep:
                    rows.append(f"line: {_one_line(w.keep[m.handle])}")
                items.append("\n".join(rows))
        topics.append("\n\n".join(items))
    return "\n\n\n".join(topics)


def validate(payload, works: Sequence[Work]) -> dict[str, dict]:
    """The writer's answer as {topic: {"heading": str | None, "lines": {handle: str}}}; only what was asked is kept."""
    if not isinstance(payload, dict) or not isinstance(payload.get("topics"), list):
        raise ValueError("the answer must be an object with a list `topics`")
    by_topic = {w.topic: w for w in works}
    out: dict[str, dict] = {}
    for item in payload["topics"]:
        if not isinstance(item, dict) or not isinstance(item.get("topic"), str) or item["topic"] not in by_topic \
                or item["topic"] in out:
            continue
        w = by_topic[item["topic"]]
        text = item.get("heading")
        heading_text = text if w.heading_state == "write" and isinstance(text, str) else None
        asked = {f"g:{m.handle}": m.handle for m in w.write}
        lines: dict[str, str] = {}
        for entry in item["lines"] if isinstance(item.get("lines"), list) else []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("line"), str):
                handle = asked.get(entry["id"])
                if handle is not None and handle not in lines:
                    lines[handle] = entry["line"]
        out[w.topic] = {"heading": heading_text, "lines": lines}
    return out


def _form_problem(text: str, limit: int) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return "empty"
    if len(text.splitlines()) != 1:
        return "more than one line"
    if text != text.strip():
        return "spaces at its ends"
    if len(text) > limit:
        return f"over {limit} characters"
    return None


def heading_problem(text: str) -> str | None:
    return _form_problem(text, HEADING_LIMIT) or ("ends with a period or a colon" if text[-1] in ".:" else None)


def line_problem(text: str, m: records.Memory) -> str | None:
    found = _form_problem(text, records.SHORT_LIMIT)
    if found:
        return found
    return "; ".join(shortcheck.problems(m.claim, text)) or None


def _work_pairs(w: Work, p: Mapping) -> list[tuple[str, records.Memory, str, str]]:
    proposed_heading = p.get("heading")
    if w.heading_state == "write":
        head = proposed_heading if isinstance(proposed_heading, str) and heading_problem(proposed_heading) is None else None
    else:
        head = w.heading
    if head is None:
        return []
    lines = p.get("lines", {})
    out = []
    for m in w.lessons:
        text = lines.get(m.handle) if m in w.write else None
        if text is not None and line_problem(text, m) is None:
            out.append((f"g:{m.handle}", m, head, text))
        elif w.heading_state == "write" and m.handle in w.keep:
            out.append((f"g:{m.handle}", m, head, w.keep[m.handle]))
    return out


def pairs(works: Sequence[Work], proposed: Mapping[str, Mapping]) -> list[tuple[str, records.Memory, str, str]]:
    """(id, lesson, heading, line) for every line the checker judges."""
    return [pair for w in works for pair in _work_pairs(w, proposed.get(w.topic, {}))]


def _ok(verdicts: Mapping[str, Mapping], ident: str, *keys: str) -> bool:
    v = verdicts.get(ident)
    return isinstance(v, Mapping) and all(v.get(k) is True for k in keys)


def decide(works: Sequence[Work], proposed: Mapping[str, Mapping], verdicts: Mapping[str, Mapping], digest: dict,
           state: Mapping) -> tuple[dict, dict, dict[str, int]]:
    """The new digest, the new state and the counts. Nothing passed in is changed."""
    new = copy.deepcopy(digest)
    new.setdefault("topics", {})
    st = copy.deepcopy(dict(state))
    tries = st.setdefault("tries", {})
    st.setdefault("failures", {"count": 0, "fingerprint": ""})
    counts = {"headings_written": 0, "lines_written": 0, "refused_code": 0, "refused_check": 0, "missing": 0}

    def refuse(key: str, why: str) -> None:
        tries[key] = tries.get(key, 0) + 1
        counts[why] += 1

    for w in works:
        p = proposed.get(w.topic, {})
        topic_pairs = _work_pairs(w, p)
        got = {ident: (text) for ident, _, _, text in topic_pairs}
        lines = p.get("lines", {})
        of = heading_print(w.lessons)
        if w.heading_state == "write":
            text = p.get("heading")
            if not isinstance(text, str):
                refuse(_heading_key(w.topic, w.lessons), "missing")
                continue
            if heading_problem(text) is not None or not topic_pairs:
                refuse(_heading_key(w.topic, w.lessons), "refused_code")
                continue
            if not all(_ok(verdicts, ident, "fits") for ident in got):
                refuse(_heading_key(w.topic, w.lessons), "refused_check")
                continue
            entry = {"heading": text, "of": of, "lines": {}}
            new["topics"][w.topic] = entry
            counts["headings_written"] += 1
        else:
            entry = new["topics"][w.topic]
        for handle, stored_text in w.keep.items():
            if w.heading_state == "write" and _ok(verdicts, f"g:{handle}", "fits", "faithful"):
                m = next(x for x in w.lessons if x.handle == handle)
                entry["lines"][handle] = {"text": stored_text, "of": line_print(m), "under": of}
        for m in w.write:
            key = _line_key(m, w.lessons)
            text = lines.get(m.handle)
            if text is None:
                refuse(key, "missing")
            elif line_problem(text, m) is not None:
                refuse(key, "refused_code")
            elif not _ok(verdicts, f"g:{m.handle}", "fits", "faithful"):
                refuse(key, "refused_check")
            else:
                entry["lines"][m.handle] = {"text": text, "of": line_print(m), "under": entry["of"]}
                counts["lines_written"] += 1
    return new, st, counts
