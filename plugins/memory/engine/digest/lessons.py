"""The digest of the loaded lessons: a derived file, `rules-digest.json`, in the plugin's data folder.

It holds, per topic, a heading and one line per lesson. It never lives in a record. A caller finds the data folder
with `mem.data_dir(os.environ)`; `read` and `write` take it as an argument.

Shape: {"topics": {topic: {"heading": str, "of": str, "lines": {handle: {"text": str, "of": str, "under": str}}}}}
`of` fingerprints what the text was written from; `under` fingerprints the heading a line was written under.
A text is fresh only while its fingerprint still matches (C88 to C90).
"""

from __future__ import annotations

import copy
import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from memories import records, rules, shortcheck
from memories.fingerprints import heading, heading_print, line, line_print

if TYPE_CHECKING:
    import datetime
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "DIGEST_ATTEMPTS",
    "DIGEST_LIMIT",
    "FILE",
    "HEADING_LIMIT",
    "MIN_LESSONS",
    "DigestFormatError",
    "Work",
    "blocks",
    "decide",
    "heading",
    "heading_print",
    "heading_problem",
    "line",
    "line_print",
    "line_problem",
    "pairs",
    "pruned",
    "read",
    "topics_of",
    "validate",
    "work",
    "write",
]


class DigestFormatError(ValueError):
    """The writer's answer is not the shape `validate` expects."""


FILE = "rules-digest.json"
HEADING_LIMIT = 80
MIN_LESSONS = 2  # a topic is digested only with at least this many ready lessons
DIGEST_ATTEMPTS = 2  # tries of one heading or one line before it is left alone
DIGEST_LIMIT = 30  # lessons one run asks lines for; a topic is never split


def _strings(d, *keys) -> bool:
    return isinstance(d, dict) and all(isinstance(d.get(k), str) for k in keys)


def _control(text: str) -> bool:
    return any(c < " " or c == "\x7f" for c in text)


def _printable(text: str, limit: int) -> bool:
    """A non-empty single line with no control character, within `limit`: what a stored text must still be when read."""
    return (
        bool(text.strip())
        and len(text.splitlines()) == 1
        and not _control(text)
        and len(text) <= limit
    )


def _read_topics(data: Path | None, out: dict) -> None:
    """Fills `out` with the file's topics that are well formed; raises on a file that is missing or not the expected shape."""
    if data is None:
        raise TypeError("no data folder")
    raw = json.loads((Path(data) / FILE).read_text(encoding="utf-8"))
    topics = raw["topics"]
    if not isinstance(topics, dict):
        return
    for topic, entry in topics.items():
        if (
            not isinstance(topic, str)
            or not _strings(entry, "heading", "of")
            or not isinstance(entry.get("lines"), dict)
            or not _printable(entry["heading"], HEADING_LIMIT)
        ):
            continue  # a heading that is not a plain line takes its topic's lines with it
        lines = {
            h: dict(v)
            for h, v in entry["lines"].items()
            if isinstance(h, str)
            and _strings(v, "text", "of", "under")
            and _printable(v["text"], records.SHORT_LIMIT)
        }
        out["topics"][topic] = {"heading": entry["heading"], "of": entry["of"], "lines": lines}


def read(data: Path | None) -> dict:
    """The file's content; anything missing or wrong reads as empty, entry by entry, and never raises."""
    out: dict = {"topics": {}}
    try:
        _read_topics(data, out)
    except Exception:
        logger.debug(
            "the digest file could not be read; the entries read so far are kept", exc_info=True
        )
    return out


def write(data: Path, digest: dict) -> None:
    """Writes the file through a temporary file in the same folder, then renames it into place."""
    data = Path(data)
    data.mkdir(parents=True, exist_ok=True)
    tmp = data / f"{FILE}.{os.getpid()}.tmp"
    try:
        tmp.write_text(
            json.dumps(digest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
        os.replace(tmp, data / FILE)
    finally:
        tmp.unlink(missing_ok=True)


def topics_of(
    global_lessons: Sequence[records.Memory], today: datetime.date
) -> dict[str, list[records.Memory]]:
    """Ready global lessons (loaded, or left as over the limit or index only) by topic, topics with two or more."""
    choice = rules.choose([], global_lessons, today)
    ready = [*choice.loaded, *(m for m, why in choice.left if why in {rules.OVER, rules.INDEX})]
    groups: dict[str, list[records.Memory]] = {}
    for m in ready:
        if m.topic:
            groups.setdefault(m.topic, []).append(m)
    return {t: ls for t, ls in groups.items() if len(ls) >= MIN_LESSONS}


class Work(NamedTuple):
    topic: str
    lessons: list  # every ready lesson of the topic
    heading_state: (
        str  # "keep" (the stored heading is fresh), "write", or "given_up" (its tries are spent)
    )
    heading: str | None  # the stored text when the state is "keep"
    write: list  # lessons that need a line
    keep: dict  # handle -> stored text of the lessons whose line is still written from their claim and short form


def _heading_key(topic: str, lessons: Sequence[records.Memory]) -> str:
    return f"h:{topic}@{heading_print(lessons)}"


def _line_key(m: records.Memory, lessons: Sequence[records.Memory]) -> str:
    return f"l:{m.handle}@{line_print(m)}@{heading_print(lessons)}"


def _tries(state: Mapping, key: str) -> int:
    return state.get("tries", {}).get(key, 0)


def pruned(digest: dict, state: Mapping, topics: Mapping[str, list]) -> tuple[dict, dict]:
    """The digest and the state without what no longer applies: topics that are not in `topics`, lines of lessons that
    left their topic, and tries of texts that can no longer be asked for. Nothing passed in is changed."""
    new = copy.deepcopy(digest)
    st = copy.deepcopy(dict(state))
    keys: set[str] = set()
    for topic, lessons in topics.items():
        keys.add(_heading_key(topic, lessons))
        keys.update(_line_key(m, lessons) for m in lessons if records.valid_short(m.short))
    for topic in list(new.get("topics", {})):
        if topic not in topics:
            del new["topics"][topic]
        else:
            present = {m.handle for m in topics[topic]}
            new["topics"][topic]["lines"] = {
                h: v for h, v in new["topics"][topic]["lines"].items() if h in present
            }
    if "tries" in st:
        st["tries"] = {k: n for k, n in st["tries"].items() if k in keys}
    return new, st


def _line_split(
    lessons: Sequence[records.Memory], stored: Mapping, state: Mapping
) -> tuple[list, dict]:
    """The lessons that need a line, and handle -> text of those whose stored line is still fresh."""
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
    return to_write, keep


def _topic_work(topic: str, lessons: list, digest: dict, state: Mapping) -> Work | None:
    """What one topic asks for, or None when its heading is given up or nothing is left to write."""
    kept_heading = heading(digest, topic, lessons)
    if kept_heading is not None:
        hstate = "keep"
    elif _tries(state, _heading_key(topic, lessons)) >= DIGEST_ATTEMPTS:
        return None
    else:
        hstate = "write"
    stored = digest.get("topics", {}).get(topic, {}).get("lines", {})
    to_write, keep = _line_split(lessons, stored, state)
    if hstate == "keep" and not to_write:
        return None
    return Work(topic, lessons, hstate, kept_heading, to_write, keep)


def work(topics: Mapping[str, list], digest: dict, state: Mapping) -> list[Work]:
    """What one run asks for, by topic in the order of the names. Lessons without a valid short form get no line."""
    out: list[Work] = []
    asked = 0
    for topic in sorted(topics):
        if asked >= DIGEST_LIMIT:
            break
        topic_work = _topic_work(topic, list(topics[topic]), digest, state)
        if topic_work is not None:
            out.append(topic_work)
            asked += len(topic_work.write)
    return out


def _one_line(text) -> str:
    return " ".join(str(text).split())


def blocks(works: Sequence[Work]) -> str:
    """What the writer reads. A kept heading prints `heading (keep): <text>`, one to write `heading: write`; a lesson prints only when it is
    written or kept; the header of a topic is a block of its own."""
    topics = []
    for w in works:
        parts = [f"topic: {_one_line(w.topic)}"]
        parts.append(
            f"heading (keep): {_one_line(w.heading)}"
            if w.heading_state == "keep"
            else "heading: write"
        )
        items = ["\n".join(parts)]
        for m in w.lessons:
            if m in w.write or m.handle in w.keep:
                rows = [
                    f"id: g:{m.handle}",
                    f"do: {'write' if m in w.write else 'keep'}",
                    f"claim: {_one_line(m.claim)}",
                ]
                if m.context:
                    rows.append(f"context: {_one_line(m.context)}")
                rows.append(f"short: {_one_line(m.short)}")
                if m.handle in w.keep:
                    rows.append(f"line: {_one_line(w.keep[m.handle])}")
                items.append("\n".join(rows))
        topics.append("\n\n".join(items))
    return "\n\n\n".join(topics)


def _answered_lines(item: dict, w: Work) -> dict[str, str]:
    """handle -> line for the lines the answer gives to lessons that were asked, the first of each."""
    asked = {f"g:{m.handle}": m.handle for m in w.write}
    lines: dict[str, str] = {}
    for entry in item["lines"] if isinstance(item.get("lines"), list) else []:
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and isinstance(entry.get("line"), str)
        ):
            handle = asked.get(entry["id"])
            if handle is not None and handle not in lines:
                lines[handle] = entry["line"]
    return lines


def validate(payload, works: Sequence[Work]) -> dict[str, dict]:
    """The writer's answer as {topic: {"heading": str | None, "lines": {handle: str}}}; only what was asked is kept."""
    if not isinstance(payload, dict) or not isinstance(payload.get("topics"), list):
        raise DigestFormatError("the answer must be an object with a list `topics`")
    by_topic = {w.topic: w for w in works}
    out: dict[str, dict] = {}
    for item in payload["topics"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("topic"), str)
            or item["topic"] not in by_topic
            or item["topic"] in out
        ):
            continue
        w = by_topic[item["topic"]]
        text = item.get("heading")
        heading_text = text if w.heading_state == "write" and isinstance(text, str) else None
        out[w.topic] = {"heading": heading_text, "lines": _answered_lines(item, w)}
    return out


def _form_problem(text: str, limit: int) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return "empty"
    if len(text.splitlines()) != 1:
        return "more than one line"
    if _control(text):
        return "a control character"
    if text != text.strip():
        return "spaces at its ends"
    if len(text) > limit:
        return f"over {limit} characters"
    return None


def heading_problem(text: str) -> str | None:
    return _form_problem(text, HEADING_LIMIT) or (
        "ends with a period or a colon" if text[-1] in ".:" else None
    )


def line_problem(text: str, m: records.Memory) -> str | None:
    found = _form_problem(text, records.SHORT_LIMIT)
    if found:
        return found
    return "; ".join(shortcheck.problems(m.claim, text)) or None


def _work_pairs(w: Work, p: Mapping) -> list[tuple[str, records.Memory, str, str]]:
    proposed_heading = p.get("heading")
    if w.heading_state == "write":
        head = (
            proposed_heading
            if isinstance(proposed_heading, str) and heading_problem(proposed_heading) is None
            else None
        )
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


def pairs(
    works: Sequence[Work], proposed: Mapping[str, Mapping]
) -> list[tuple[str, records.Memory, str, str]]:
    """(id, lesson, heading, line) for every line the checker judges."""
    return [pair for w in works for pair in _work_pairs(w, proposed.get(w.topic, {}))]


def _ok(verdicts: Mapping[str, Mapping], ident: str, *keys: str) -> bool:
    v = verdicts.get(ident)
    return isinstance(v, Mapping) and all(v.get(k) is True for k in keys)


class _Ruling:
    """What `decide` keeps while it rules on the works: the verdicts, the tries to update and the counts."""

    def __init__(self, verdicts: Mapping[str, Mapping], tries: dict) -> None:
        self.verdicts = verdicts
        self.tries = tries
        self.counts = {
            "headings_written": 0,
            "lines_written": 0,
            "refused_code": 0,
            "refused_check": 0,
            "missing": 0,
            "unjudged": 0,
        }

    def refuse(self, key: str, why: str) -> None:
        self.tries[key] = self.tries.get(key, 0) + 1
        self.counts[why] += 1

    def ok(self, ident: str, *keys: str) -> bool:
        return _ok(self.verdicts, ident, *keys)

    def judged(self, topic_pairs: Sequence[tuple]) -> set[str]:
        """The ids of the pairs the checker answered; counts the others as unjudged (an answer that leaves a lesson out is no judgment of it)."""
        got = {ident for ident, _, _, _ in topic_pairs}
        judged = {ident for ident in got if isinstance(self.verdicts.get(ident), Mapping)}
        self.counts["unjudged"] += len(got) - len(judged)
        return judged

    def new_heading(
        self, w: Work, p: Mapping, topic_pairs: Sequence[tuple], judged: set[str]
    ) -> dict | None:
        """The entry for a heading that was written and passed, or None (refused, or not judged yet)."""
        text = p.get("heading")
        key = _heading_key(w.topic, w.lessons)
        if not isinstance(text, str):
            self.refuse(key, "missing")
        elif heading_problem(text) is not None or not topic_pairs:
            self.refuse(key, "refused_code")
        elif not judged:
            pass
        elif not all(self.ok(ident, "fits") for ident in judged):
            self.refuse(key, "refused_check")
        else:
            self.counts["headings_written"] += 1
            return {"heading": text, "of": heading_print(w.lessons), "lines": {}}
        return None

    def keep_lines(self, w: Work, entry: dict) -> None:
        """Carries over the stored lines of a rewritten heading whose lesson the checker still finds faithful."""
        for handle, stored_text in w.keep.items():
            if w.heading_state == "write" and self.ok(f"g:{handle}", "fits", "faithful"):
                m = next(x for x in w.lessons if x.handle == handle)
                entry["lines"][handle] = {
                    "text": stored_text,
                    "of": line_print(m),
                    "under": entry["of"],
                }

    def _line_outcome(self, m: records.Memory, text: str | None, judged: set[str]) -> str:
        if text is None:
            return "missing"
        if line_problem(text, m) is not None:
            return "refused_code"
        if f"g:{m.handle}" not in judged:
            return "unjudged"
        if not self.ok(f"g:{m.handle}", "fits", "faithful"):
            return "refused_check"
        return "written"

    def write_lines(self, w: Work, entry: dict, lines: Mapping, judged: set[str]) -> None:
        """Rules on each line asked for: writes it into `entry`, or refuses it and counts a try."""
        for m in w.write:
            text = lines.get(m.handle)
            outcome = self._line_outcome(m, text, judged)
            if outcome in {"missing", "refused_code", "refused_check"}:
                self.refuse(_line_key(m, w.lessons), outcome)
            elif outcome == "written":
                entry["lines"][m.handle] = {"text": text, "of": line_print(m), "under": entry["of"]}
                self.counts["lines_written"] += 1


def decide(
    works: Sequence[Work],
    proposed: Mapping[str, Mapping],
    verdicts: Mapping[str, Mapping],
    digest: dict,
    state: Mapping,
) -> tuple[dict, dict, dict[str, int]]:
    """The new digest, the new state and the counts. Nothing passed in is changed."""
    new = copy.deepcopy(digest)
    new.setdefault("topics", {})
    st = copy.deepcopy(dict(state))
    tries = st.setdefault("tries", {})
    st.setdefault("failures", {"count": 0, "fingerprint": ""})
    ruling = _Ruling(verdicts, tries)
    for w in works:
        p = proposed.get(w.topic, {})
        topic_pairs = _work_pairs(w, p)
        judged = ruling.judged(topic_pairs)
        if w.heading_state == "write":
            entry = ruling.new_heading(w, p, topic_pairs, judged)
            if entry is None:
                continue
            new["topics"][w.topic] = entry
        else:
            entry = new["topics"][w.topic]
        ruling.keep_lines(w, entry)
        ruling.write_lines(w, entry, p.get("lines", {}), judged)
    return new, st, ruling.counts
