"""The units of a part: sentences and list items with the references on them, and the fingerprints of a part's text.

A leaf below `document` and `edit`: `Unit` and its parser, `fingerprint` and friends, and the few link and fence helpers
that both of them share. Imports nothing from mem.py.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

NOTE_FOLDERS = ("literature", "knowledge", "research")  # where a Sources link may point
MIN_NOTE_PARTS = 2
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")


def _next_fence(fence: str | None, marker: str) -> str | None:
    """The fence state after a line that opens or closes with `marker` (its first character)."""
    return None if fence and marker == fence else (fence or marker)


def _relative(target: str) -> bool:
    return not target.startswith(("#", "mailto:")) and not _SCHEME.match(target)


def _file_part(target: str) -> str:
    return urllib.parse.unquote(target.split("#", 1)[0])


def _note_key(target: str) -> str:
    return posixpath.normpath(urllib.parse.unquote(_file_part(target)))


_REF_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_INTRO_ITEM = re.compile(
    r"[ \t]*(?:[-*+]|\d+[.)])[ \t]+"
)  # a list item a colon-final line may introduce
_LIST_MARK = re.compile(r"(?:>\s*)*(?:(?:[-*+]|\d+[.)])[ \t]+|#{1,6}[ \t]+)?")
_BOLD_LABEL = re.compile(r"\*\*[^*\n]*[.!?:]\*\*(?=\s|$)")
_TABLE_SEP = re.compile(r"\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*")
_ABBREVIATION = re.compile(r"(?:^|[\s(\[])(?:e\.g|i\.e|et al|vs|cf)$", re.IGNORECASE)
_CLOSERS = "\"'\u201d\u2019)]\u00bb"
_GAP = " \t,;"
_FRONTMATTER_SLOT = "{frontmatter}"
_SUMMARY_SLOT = "{summary}"


@dataclass(frozen=True)
class Unit:
    """One sentence or table row of a part's body."""

    n: int  # 1-based
    text: str  # as stored, including the references that follow the sentence
    plain: str  # without references: trailing ones dropped, inline ones reduced to their label
    refs: list[str]  # targets (file part), in order
    span: tuple[int, int]  # character offsets in the part text, [start, end)


@dataclass(frozen=True)
class _Ref:
    start: int
    end: int
    label: str
    target: str
    trailing: (
        bool  # follows the closing punctuation of its sentence: dropped, not reduced to its label
    )


def _is_ref(target: str) -> bool:
    """A relative link into a note folder (the folders may be reached through leading `..`)."""
    if not _relative(target) or target.startswith("/"):
        return False
    parts = [p for p in posixpath.normpath(_file_part(target)).split("/") if p not in {"", "."}]
    while parts and parts[0] == "..":
        parts.pop(0)
    return len(parts) >= MIN_NOTE_PARTS and parts[0] in NOTE_FOLDERS and parts[-1].endswith(".md")


def _inline(raw: str) -> list[tuple[int, int, str, re.Match[str] | None]]:
    """Code spans and links of a line, as (start, end, kind, match); nothing inside them splits or links."""
    found, i = [], 0
    while i < len(raw):
        if raw[i] == "`":
            n = len(raw[i:]) - len(raw[i:].lstrip("`"))
            j = i + n
            while (j := raw.find("`" * n, j)) != -1 and raw[j : j + n + 1] == "`" * (n + 1):
                j += len(raw[j:]) - len(raw[j:].lstrip("`"))
            if j != -1:
                found.append((i, j + n, "code", None))
                i = j + n
                continue
            i += n
        elif raw[i] == "[" and (m := _REF_LINK.match(raw, i)):
            found.append((i, m.end(), "link", m))
            i = m.end()
        else:
            i += 1
    return found


def _remove(text: str, lo: int, hi: int, refs: Sequence[_Ref]) -> str:
    out, pos = [], lo
    for r in refs:
        if r.trailing:
            s = r.start
            while s > pos and text[s - 1] in _GAP:
                s -= 1
            out.append(text[pos:s])
        else:
            out.append(text[pos : r.start] + r.label)
        pos = r.end
    return "".join(out) + text[pos:hi]


def _last_content(lines: list[str]) -> int | None:
    """Index of the last line that is not blank."""
    return next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)


def _ref_of(m: re.Match[str], base: int, trailing: bool) -> _Ref:
    return _Ref(base + m.start(), base + m.end(), m.group(1), m.group(2), trailing)


def _list_mark_end(raw: str) -> int:
    m = _LIST_MARK.match(raw)
    return m.end() if m else 0


class _Line:
    """One prose or table line of a body: its links into notes and the scans that look at them."""

    def __init__(self, raw: str, base: int) -> None:
        self.raw, self.base = raw, base
        spans = _inline(raw)
        self.links = {
            s: (e, m)
            for s, e, kind, m in spans
            if kind == "link" and m is not None and _is_ref(m.group(2))
        }
        self.starts = {s: e for s, e, _, _ in spans}
        self.ce = len(raw.rstrip())
        self.indent = len(raw) - len(raw.lstrip())

    def ref(self, m: re.Match[str], trailing: bool) -> _Ref:
        return _ref_of(m, self.base, trailing)

    def skip_gap(self, p: int, chars: str = " \t") -> int:
        while p < self.ce and self.raw[p] in chars:
            p += 1
        return p

    def only_refs_follow(self, p: int) -> bool:
        # `et al.` ends a unit when only references follow it on the line: the abbreviation stops splitting
        # mid-sentence, but a reference added after it must not merge the unit into its own label.
        p = self.skip_gap(p, _GAP)
        if p >= self.ce or p not in self.links:
            return False
        while p in self.links:
            p = self.skip_gap(self.links[p][0], _GAP)
        return p >= self.ce

    def colon_intro_head(self, lo: int) -> int | None:
        """Where the references start when the rest of the line is `words:` plus only references."""
        for s0 in sorted(self.links):
            if s0 < lo:
                continue
            p = s0
            while p > lo and self.raw[p - 1] in _GAP:
                p -= 1
            if (
                p > lo
                and self.raw[p - 1] == ":"
                and self.only_refs_follow(s0)
                and re.search(r"\w", self.raw[lo:p])
            ):
                return s0
            break
        return None

    def table_refs(self) -> list[_Ref]:
        refs = []
        for s, (_, m) in self.links.items():
            k = s
            while k > self.indent and self.raw[k - 1] in _GAP:
                k -= 1
            refs.append(self.ref(m, k > self.indent and self.raw[k - 1] in ".!?" + _CLOSERS))
        return refs

    def punct_end(self, k: int) -> tuple[int, int]:
        """(end of the run of `.!?` at `k`, end of the closing quotes and brackets after it)."""
        j = k + 1
        while j < self.ce and self.raw[j] in ".!?":
            j += 1
        t = j
        while t < self.ce and self.raw[t] in _CLOSERS:
            t += 1
        return j, t

    def ends_unit(self, k: int, j: int, t: int, ustart: int) -> bool:
        """Whether the punctuation at `k` (run to `j`, closers to `t`) ends the unit that began at `ustart`."""
        if not (t >= self.ce or self.raw[t].isspace() or t in self.links):
            return False
        abbreviation = (
            self.raw[k] == "."
            and j == k + 1
            and _ABBREVIATION.search(self.raw[ustart:k])
            and not self.only_refs_follow(t)
        )
        return not abbreviation

    def unit_end(self, t: int) -> int:
        """The end of a unit whose punctuation ends at `t`: the references that follow it belong to it."""
        end = t
        while (p := self.skip_gap(end, _GAP)) in self.links:
            end = self.links[p][0]
        return end


class _Parser:
    """Walks the lines of a body and collects the units (as character spans with their references) and orphans."""

    def __init__(self, lines: list[str], offsets: list[int], count: int) -> None:
        self.lines, self.offsets, self.count = lines, offsets, count
        self.found: list[tuple[int, int, list[_Ref]]] = []
        self.orphans: list[_Ref] = []
        self.fence: str | None = None
        self.prev_blank = True

    def run(self) -> None:
        for i in range(self.count):
            self.feed(i)

    def feed(self, i: int) -> None:
        raw = self.lines[i].rstrip("\r")
        if f := _FENCE.match(raw):
            self.fence = _next_fence(self.fence, f.group(1)[0])
            self.prev_blank = False
            return
        if self.fence:
            return
        if not raw.strip():
            self.prev_blank = True
            return
        was_blank, self.prev_blank = self.prev_blank, False
        line = _Line(raw, self.offsets[i])
        if raw.lstrip().startswith("|"):
            self.table(line)
        else:
            self.prose(i, line, was_blank)

    def table(self, line: _Line) -> None:
        if _TABLE_SEP.fullmatch(line.raw) and "-" in line.raw:
            return
        self.found.append((line.base + line.indent, line.base + line.ce, line.table_refs()))

    def introduces_block(self, n: int) -> bool:
        nxt = next(
            (self.lines[j].rstrip("\r") for j in range(n + 1, self.count) if self.lines[j].strip()),
            None,
        )
        # a table row or a list item only: a heading or a quote after a colon introduces no block of this unit
        return nxt is not None and (nxt.lstrip().startswith("|") or bool(_INTRO_ITEM.match(nxt)))

    def prose(self, i: int, line: _Line, was_blank: bool) -> None:
        cs = _list_mark_end(line.raw)
        if (was_blank or cs > 0) and (m := _BOLD_LABEL.match(line.raw, cs, line.ce)):
            # A reference inside a label supports no sentence: it has no owner.
            self.orphans.extend(
                line.ref(lm, False) for s, (_, lm) in line.links.items() if cs <= s < m.end()
            )
            cs = m.end()
        pos = line.skip_gap(cs)
        while pos in line.links:  # a reference with no sentence before it
            end, m = line.links[pos]
            self.orphans.append(line.ref(m, False))
            pos = line.skip_gap(end, _GAP)
        self.tail(i, line, self.sentences(line, pos))

    def sentences(self, line: _Line, pos: int) -> int:
        """Record the units that end before the end of the line; return where the unfinished one starts."""
        ustart, k = pos, pos
        while k < line.ce:
            if k in line.starts:
                k = line.starts[k]
            elif line.raw[k] not in ".!?":
                k += 1
            else:
                k, ustart = self.sentence(line, k, ustart)
        return ustart

    def sentence(self, line: _Line, k: int, ustart: int) -> tuple[int, int]:
        """The punctuation at `k`: (where to scan on, where the next unit starts)."""
        j, t = line.punct_end(k)
        if not line.ends_unit(k, j, t, ustart):
            return j, ustart
        if not re.search(r"\w", line.raw[ustart:k]):
            nxt = line.skip_gap(t)
            return nxt, nxt
        end = line.unit_end(t)
        refs = [line.ref(m, s >= t) for s, (_, m) in line.links.items() if ustart <= s < end]
        self.found.append((line.base + ustart, line.base + end, refs))
        nxt = line.skip_gap(end)
        return nxt, nxt

    def tail(self, i: int, line: _Line, ustart: int) -> None:
        """The unit that runs to the end of the line, if it has any word."""
        if ustart >= line.ce or not re.search(r"\w", line.raw[ustart : line.ce]):
            return
        head = line.colon_intro_head(ustart)
        # A unit that ends in `:` before a table or list closes there: a reference added after the colon
        # must not merge into the unit's own words.
        split = head if head is not None and self.introduces_block(i) else None
        refs = [
            line.ref(m, split is not None and s >= split)
            for s, (_, m) in line.links.items()
            if ustart <= s < line.ce
        ]
        self.found.append((line.base + ustart, line.base + line.ce, refs))


def _parse(text: str) -> tuple[list[Unit], list[_Ref], list[_Ref], int]:
    """(units, every reference of the body in order, the references without an owner, end of the body)."""
    lines = text.split("\n")
    offsets, o = [], 0
    for ln in lines:
        offsets.append(o)
        o += len(ln) + 1
    last = _last_content(lines)
    count, body_end = len(lines), len(text)
    if last is not None and lines[last].startswith("Sources:"):
        count, body_end = last, offsets[last]
    parser = _Parser(lines, offsets, count)
    parser.run()
    units = [
        Unit(n, text[a:b], _remove(text, a, b, refs), [_file_part(r.target) for r in refs], (a, b))
        for n, (a, b, refs) in enumerate(parser.found, 1)
    ]
    every = sorted(
        [r for _, _, refs in parser.found for r in refs] + parser.orphans, key=lambda r: r.start
    )
    return units, every, parser.orphans, body_end


def units(text: str) -> tuple[list[Unit], list[str]]:
    """A part's body (everything but the closing `Sources:` line) as numbered units, and the targets of the
    references that have no owner.

    A unit is a sentence or a table row. A reference is a relative link into a note folder; one that follows a
    sentence's closing punctuation (white space, `,` or `;` between) belongs to that sentence, and so does one
    inside it. A bold label that opens a paragraph or list item (`**What it is.**`) belongs to no unit."""
    found, _, orphans, _ = _parse(text)
    return found, [_file_part(r.target) for r in orphans]


def _body_without_references(text: str) -> tuple[str, int]:
    _, every, _, body_end = _parse(text)
    return _remove(text, 0, body_end, every), body_end


def without_references(text: str) -> str:
    """The part's text with the references of its body removed (the `Sources:` line stays as it is)."""
    body, body_end = _body_without_references(text)
    return body + text[body_end:]


def fingerprint(text: str) -> str:
    """A short hash of a section's text without its `Sources:` line, its references and surrounding whitespace."""
    return _hash(_body_without_references(text)[0])


def _hash(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:10]


def fingerprint_legacy(text: str) -> str:
    """The fingerprint before references existed: stored by notes stamped earlier, still accepted."""
    lines = text.split("\n")
    last = _last_content(lines)
    if last is not None and lines[last].startswith("Sources:"):
        lines = lines[:last]
    return _hash("\n".join(lines))


def note_fingerprint(text: str, target: str) -> str:
    """The stamp of one note in a part: `u:` plus a hash of the sorted multiset of the units that cite the note and
    the part's table rows (they cannot carry a reference), each as plain text with white space collapsed. A note
    that no unit cites gets `fingerprint(text)`, the whole-part rule.

    `target` is the note as a reference names it: the relative link from the synthesis folder, `../knowledge/<d>/<f>.md`
    (the entries of `Unit.refs`); spelling variants (`./`, `%20`, `#fragment`) compare equal."""
    key = _note_key(target)
    found = units(text)[0]
    if not any(key in {_note_key(r) for r in u.refs} for u in found):
        return fingerprint(text)
    picked = [
        " ".join(u.plain.split())
        for u in found
        if key in {_note_key(r) for r in u.refs} or u.text.lstrip().startswith("|")
    ]
    return "u:" + _hash("\n".join(sorted(picked)))


def is_current(stored: object, text: str, target: str | None = None) -> bool:
    """Whether a note's `part_of_hash` matches the part's text. A `u:` stamp compares with `note_fingerprint`
    (never current without a `target`); any other stamp is the whole part, by the current or the legacy fingerprint."""
    if isinstance(stored, str) and stored.startswith("u:"):
        return target is not None and stored == note_fingerprint(text, target)
    return isinstance(stored, str) and stored in {fingerprint(text), fingerprint_legacy(text)}


def word_count(text: str) -> int:
    return len(text.split())


def first_paragraph(text: str) -> str:
    """The text up to the first blank line; empty when that paragraph is the `Sources:` line."""
    para = re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]
    return "" if para.startswith("Sources:") else para
