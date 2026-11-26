"""The `check`, `index`, `find`, `topics`, `show`, `search`, `passages`, `related`, `search-eval`, `stats` and `review` handlers (A5, ADR 0028): the read commands."""

from __future__ import annotations

import collections
import dataclasses
import datetime
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

from memories import records
from notes import check as check_rules
from notes import due as due_queries
from notes import index as index_files
from notes import links as link_rules
from notes import note as note_files
from notes import search as note_search
from syntheses import document
from syntheses import edit as synthesis_edit
from syntheses import project as project_syntheses

from commands import common

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

_MEM_PY = Path(__file__).resolve().parents[1] / "mem.py"  # `mem stats` counts this file by name


_SECTION_LEVEL = 2  # the heading level of a `## ` section


_SPARSE_HITS = 3  # fewer hits than this makes a search look for more


RECALL_TRIGGER = 0.8  # below these, revisit the search design (C-6 in docs/requirements.md)


MRR_TRIGGER = 0.6


_HEADING = re.compile(r"^(#{1,4})[ \t]+\S")


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(0-based index, level, text) of each Markdown heading outside fenced code."""
    return [
        (i, len(h.group(1)), line)
        for i, (line, fenced) in enumerate(zip(lines, link_rules._in_fence(lines), strict=False))
        if not fenced and (h := _HEADING.match(line))
    ]


def _sections(lines: list[str], wanted: list[str]) -> list[str]:
    """Requested `## ` sections in the note's order, then a message per absent one."""
    h2 = [
        (i, line[2:].strip().casefold())
        for i, level, line in _headings(lines)
        if level == _SECTION_LEVEL
    ]
    keys = {w.strip().casefold() for w in wanted}
    out: list[str] = []
    seen: set[str] = set()
    for n, (start, key) in enumerate(h2):
        if key in keys:
            seen.add(key)
            end = h2[n + 1][0] if n + 1 < len(h2) else len(lines)
            out.extend(lines[start:end])
    out.extend(f'(no section "{w}")' for w in wanted if w.strip().casefold() not in seen)
    return out


_KEY_FACTS = {
    "knowledge": ("confidence", "updated", "level"),
    "literature": ("year", "kind", "url", "level"),
    "research": ("status", "started"),
}


def _key_facts(note_type: str, meta: Any) -> str | None:
    """One line of the fields an agent needs to judge a note; missing fields are left out."""
    if not isinstance(meta, dict) or note_type not in _KEY_FACTS:
        return None
    flag = " [disputed]" if note_type == "knowledge" and meta.get("disputed") else ""
    return (
        " \u00b7 ".join(
            f"{k}: {meta[k]}{flag if k == 'confidence' else ''}"
            for k in _KEY_FACTS[note_type]
            if meta.get(k) is not None
        )
        or None
    )


_LEAD_SECTION = {"knowledge": "Claim", "literature": "TL;DR"}


def snippet(
    note: note_files.Note,
    terms: Sequence[str] = (),
    *,
    weights: Mapping[str, float] | None = None,
    width: int = 200,
) -> str:
    """The body line (not blank, heading, table separator or inside a fenced code block) with the highest
    total weight of its distinct `terms` (`weights`, else 1 each), earliest on ties; else the first such line.
    Whitespace is collapsed and text over `width` is cut with an ellipsis."""
    body = note.body.splitlines()
    fenced = link_rules._in_fence(body)
    lines = [
        line
        for line, inside in zip(body, fenced, strict=False)
        if not inside
        and line.strip()
        and not line.lstrip().startswith("#")
        and not set(line.strip()) <= set("|-: ")
    ]
    if not lines:
        return ""
    wanted = set(terms)
    weight = lambda line: sum(
        1.0 if weights is None else weights.get(t, 0.0)
        for t in wanted & set(records.tokenize(line))
    )
    best = max(lines, key=weight)  # max keeps the earliest tie
    text = " ".join(best.split())
    return text if len(text) <= width else text[: width - 1] + "\u2026"


class HitOptions(TypedDict, total=False):
    """The keyword options of `format_hit`."""

    score: float | None
    terms: Sequence[str]
    weights: Mapping[str, float] | None
    name: str | None


def _hit_summary(note: note_files.Note) -> list[str]:
    """The lead section of a note, indented, for the `summary` detail."""
    body = note.body.splitlines()
    lead = _LEAD_SECTION.get(note.type) or next(
        (line[2:].strip() for _, level, line in _headings(body) if level == _SECTION_LEVEL),
        None,
    )
    if lead is None:
        return []
    return ["  " + line for line in _sections(body, [lead])[1:] if line.strip()]


def _hit_disputed(note: note_files.Note) -> bool:
    return (
        note.type == "knowledge" and isinstance(note.meta, dict) and bool(note.meta.get("disputed"))
    )


def _hit_body_lines(note: note_files.Note, detail: str, options: HitOptions) -> list[str]:
    """The lines under a hit for the `snippet` and `summary` details; none for the others."""
    if detail == "summary":
        return _hit_summary(note)
    if detail == "snippet" and (
        text := snippet(note, options.get("terms", ()), weights=options.get("weights"))
    ):
        return ["  " + text]
    return []


def format_hit(note: note_files.Note, detail: str, **options: Unpack[HitOptions]) -> list[str]:
    """Output lines for one note at a `DETAILS` level; `score` is omitted from the line when None and
    `name` (a short handle) replaces the path."""
    name = options.get("name")
    score = options.get("score")
    if detail == "paths":
        return [name or note.rel]
    lines = [
        (name or note.rel)
        + ("" if score is None else f"\t{score:.2f}")
        + f"\t{note_search._title(note)}"
    ]
    if detail == "titles":
        if _hit_disputed(note):
            lines[0] += "  [disputed]"
        return lines
    if (facts := _key_facts(note.type, note.meta)) is not None:
        lines.append("  " + facts)
    lines.extend(_hit_body_lines(note, detail, options))
    return lines


def short_handles(root: Path) -> dict[str, str]:
    """Path -> the shortest prefix of its handle, cut at a hyphen and at least two words long, that no other
    handle starts with (the whole handle when none is); `resolve_note` turns it back into the note."""
    handles = {
        rel: note_files._handle(rel)
        for rel in (p.relative_to(root).as_posix() for _, p in note_files._note_files(root))
    }
    out = {}
    for rel, handle in handles.items():
        words = handle.split("-")
        out[rel] = next(
            (
                pre
                for k in range(2, len(words))
                if sum(h.startswith(pre := "-".join(words[:k])) for h in handles.values()) == 1
            ),
            handle,
        )
    return out


_CONCLUSION = {
    "knowledge": ("Claim", "Does not apply when"),
    "literature": ("TL;DR",),
    "research": ("Question",),
}


def _expand_conclusion(note_type: str, lines: list[str], sections: list[str]) -> list[str]:
    """Replace `conclusion` by the note type's lead sections that exist; other kinds get their first `## `."""
    present = [line[2:].strip() for _, level, line in _headings(lines) if level == _SECTION_LEVEL]
    lead = [
        n
        for n in _CONCLUSION.get(note_type, present[:1])
        if n.casefold() in {p.casefold() for p in present}
    ]
    return [
        x for s in sections for x in (lead or [s] if s.strip().casefold() == "conclusion" else [s])
    ]


def _outline_ranges(lines: list[str], body_line: int) -> list[str]:
    """`<start>-<end><TAB><words>w<TAB><heading>` per heading; a section ends before the next heading of its level or higher."""
    while lines and not lines[-1]:
        lines = lines[:-1]
    heads = _headings(lines)
    rows = []
    for n, (i, level, line) in enumerate(heads):
        stop = next((j for j, lv, _ in heads[n + 1 :] if lv <= level), len(lines))
        words = sum(len(x.split()) for x in lines[i:stop])
        rows.append(f"{body_line + i}-{body_line + stop - 1}\t{words}w\t{line}")
    return rows


@dataclass(frozen=True)
class _ShowMode:
    """How `show` renders a body: whole, as an outline (with line ranges) or as chosen sections."""

    sections: list[str] | None
    outline: bool
    ranges: bool


def _show_unresolved(arg: str, found: list[str] | None) -> str:
    """The block for an argument that names no single note; prints the ambiguity to stderr."""
    if found is None:
        return f"== {arg}\n(not found)"
    common._ambiguous(arg, found)
    return f"== {arg}\n(ambiguous: {len(found)} notes match)"


def _show_header(note_type: str, meta: Any) -> list[str]:
    """The lines before the body: what supersedes the note, its key facts and its synthesis."""
    out = []
    if isinstance(meta, dict) and isinstance(meta.get("superseded_by"), str):
        out.append(f"superseded by: {meta['superseded_by']}")
    if facts := _key_facts(note_type, meta):
        out.append(facts)
    if isinstance(meta, dict) and isinstance(meta.get("part_of"), str):
        ref = "s:" + meta["part_of"]
        out.append(f"part of: {ref} (extended version: mem show {ref})")
    return out


def _show_body(note_type: str, body: str, body_line: int, mode: _ShowMode) -> list[str]:
    lines = body.split("\n")
    if mode.outline and mode.ranges:
        return _outline_ranges(lines, body_line)
    if mode.outline:
        return [f"{body_line + i}: {line}" for i, _, line in _headings(lines)]
    if mode.sections:
        return _sections(lines, _expand_conclusion(note_type, lines, mode.sections))
    return lines


def _show_note(path: Path, rel: str, mode: _ShowMode) -> tuple[str, bool]:
    """The output block of one note and whether its file could be read."""
    note_type = rel.split("/", 1)[0]
    try:
        text = note_files._read_text(path)
    except note_files.FrontmatterError as exc:
        return f"== {rel}\n({exc})", False
    try:
        meta, body, body_line = note_files.split_frontmatter(text)
    except note_files.FrontmatterError:
        meta, body, body_line = None, text, 1
    out = [
        f"== {rel}",
        *_show_header(note_type, meta),
        *_show_body(note_type, body, body_line, mode),
    ]
    return "\n".join(out).rstrip("\n"), True


def show(
    root: Path,
    paths: list[str],
    *,
    sections: list[str] | None = None,
    outline: bool = False,
    ranges: bool = False,
) -> tuple[list[str], list[str], bool]:
    """Blocks of output, one per path; the resolved paths shown; whether every path was found."""
    mode = _ShowMode(sections, outline, ranges)
    blocks: list[str] = []
    shown: list[str] = []
    ok = True
    for arg in paths:
        path = common.resolve_note(root, arg)
        if not isinstance(path, Path):
            blocks.append(_show_unresolved(arg, path))
            ok = False
            continue
        rel = path.relative_to(root.resolve()).as_posix()
        shown.append(rel)
        block, readable = _show_note(path, rel, mode)
        blocks.append(block)
        ok = ok and readable
    return blocks, shown, ok


def source_text(root: Path, rel: str) -> Path | None:
    """The largest `.txt` (ties by name) of a literature note's `.sources/<note-stem>/` folder, else its largest `.md`."""
    folder = root / common.SOURCES_DIR / Path(rel).stem
    texts: list[Path] = []
    for pattern in ("*.txt", "*.md"):
        texts = (
            [p for p in folder.glob(pattern) if p.is_file() and not p.is_symlink()]
            if folder.is_dir()
            else []
        )
        if texts:
            break
    return min(texts, key=lambda p: (-p.stat().st_size, p.name), default=None)


def passages(
    text: str, query: str, *, count: int = 5, words: int = 500
) -> tuple[int, list[tuple[int, int, str]]]:
    """(word count, [(first, last, text)] of the `count` best windows by BM25 over this text, in document order).

    Windows of `words` words start half a window apart (BM25 k1 1.2, b 0.75); the last ends at the text's end;
    word numbers start at 1."""
    tokens = text.split()
    step = max(1, words // 2)
    starts = []
    for start in range(0, max(len(tokens), 1), step):
        starts.append(start)
        if start + words >= len(tokens):
            break
    wins = [" ".join(tokens[s : s + words]) for s in starts]
    counts = [collections.Counter(records.tokenize(w)) for w in wins]
    lengths = [sum(c.values()) for c in counts]
    average = sum(lengths) / len(wins)
    idf = {}
    for term in dict.fromkeys(records.tokenize(query)):
        n = sum(1 for c in counts if term in c)
        idf[term] = math.log(1 + (len(wins) - n + 0.5) / (n + 0.5))
    scored = []
    for i, (c, length) in enumerate(zip(counts, lengths, strict=False)):
        score = sum(
            idf[t] * c[t] * 2.2 / (c[t] + 1.2 * (1 - 0.75 + 0.75 * length / average))
            for t in idf
            if c.get(t) and average
        )
        if score > 0:
            scored.append((-score, i))
    best = sorted(i for _, i in sorted(scored)[:count])
    return len(tokens), [
        (starts[i] + 1, min(starts[i] + words, len(tokens)), wins[i]) for i in best
    ]


def _scopes(root: Path, paths: list[str]) -> list[str]:
    """Hub-relative form of existing files or folders inside the hub; ValueError names the first that is not."""
    out = []
    for arg in paths:
        path = (Path(arg) if Path(arg).is_absolute() else root / arg).resolve()
        if not path.exists() or not path.is_relative_to(root.resolve()):
            raise ValueError(f"no such file or folder in the hub: {arg}")
        out.append(path.relative_to(root.resolve()).as_posix())
    return out


def _in_scopes(rel: str, scopes: list[str]) -> bool:
    return not scopes or any(s in {".", rel} or rel.startswith(s + "/") for s in scopes)


def _page_footer(offset: int, shown: int, total: int) -> None:
    if shown and offset + shown < total:
        print(
            f"-- {offset + 1}-{offset + shown} of {total}; next: --offset {offset + shown} --",
            file=sys.stderr,
        )
    elif not shown and offset:
        print(f"-- offset {offset} is past the {total} matches --", file=sys.stderr)


def cmd_check(args: argparse.Namespace) -> int:
    try:
        scopes = _scopes(args.root, args.paths)
    except ValueError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    problems = [p for p in check_rules.check(args.root) if _in_scopes(p.path, scopes)]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def cmd_index(args: argparse.Namespace) -> int:
    try:
        changed = index_files.apply_index(args.root)
    except (note_files.FrontmatterError, OSError) as exc:
        print(f"mem: cannot build the index: {exc}", file=sys.stderr)
        return 1
    for rel in changed:
        print(f"updated {rel}")
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    try:
        notes = note_search._matching_notes(
            args.root,
            type=args.type,
            topic=args.topic,
            kind=args.kind,
            status=args.status,
            confidence=args.confidence,
            level=args.level,
            superseded=args.superseded,
        )
    except (note_files.FrontmatterError, OSError) as exc:
        print(f"mem: cannot find: {exc}", file=sys.stderr)
        return 1
    page = sorted(notes, key=lambda n: n.rel)[args.offset : args.offset + args.limit]
    names = short_handles(args.root) if args.handles else {}
    for note in page:
        print("\n".join(format_hit(note, args.detail, name=names.get(note.rel))))
    _page_footer(args.offset, len(page), len(notes))
    return 0


def topic_tree(root: Path, topic: str | None = None) -> list[tuple[int, str, int]]:
    """(depth, id, notes) in tree order; notes counts what `find --topic <id>` returns, descendants included."""
    known = note_files.load_topics(root)
    if topic and topic not in known:
        raise note_files.FrontmatterError(note_search._unknown_topic_message(topic, known))
    counts: collections.Counter = collections.Counter()
    for note in note_search._matching_notes(root):
        listed = note.meta.get("topics")
        direct = (
            {t for t in listed if isinstance(t, str) and t in known}
            if isinstance(listed, list)
            else set()
        )
        counts.update(direct.union(*(note_files.ancestors(known, t) for t in direct)))
    rows: list[tuple[int, str, int]] = []

    def walk(tid: str, depth: int) -> None:
        rows.append((depth, tid, counts[tid]))
        for child in sorted(
            t
            for t in known
            if note_files._parent(known, t) == tid and t not in {r[1] for r in rows}
        ):
            walk(child, depth + 1)

    for tid in [topic] if topic else sorted(note_files.root_topics(known)):
        walk(tid, 0)
    return rows


def cmd_topics(args: argparse.Namespace) -> int:
    try:
        rows = topic_tree(args.root, args.topic)
    except (note_files.FrontmatterError, OSError) as exc:
        print(f"mem: cannot find: {exc}", file=sys.stderr)
        return 1
    for depth, tid, count in rows:
        print(f"{'  ' * depth}{tid}\t{count}")
    return 0


def _memory_line(m: records.Memory, today: datetime.date) -> str:
    dead = common._memory_status(m, today)
    created = m.created.isoformat() if m.created else "undated"
    claim = " ".join(m.claim.split())  # a hand-edited tab or newline must not add a column
    return (
        f"m:{m.handle}\t[memory: {m.kind}, observed {m.observed}, {created}{common._unconfirmed(m)}"
        f"{', ' + dead if dead else ''}]\t{claim}"
    )


def _memory_facts(m: records.Memory) -> str:
    facts = f"kind: {m.kind} \u00b7 observed {m.observed} \u00b7 status {m.status} \u00b7 created {m.created.isoformat() if m.created else 'undated'}"
    if m.valid_until:
        facts += f" \u00b7 valid until {m.valid_until.isoformat()}"
    if m.context:
        facts += f" \u00b7 context: {m.context}"
    return facts


def _memory_source_lines(m: records.Memory) -> list[str]:
    out = []
    if m.sources:
        out.append(f"sources: {', '.join(m.sources)}")
    if m.short:
        out.append(f"short: {m.short}")
    return out


def _memory_tail_lines(m: records.Memory) -> list[str]:
    """The optional fields after the versions: what shortened it, why triage held it, its topic and load."""
    fields = (
        ("short_by", m.short_by),
        ("held at triage", m.triage_reason),
        ("topic", m.topic),
        ("load", m.load),
    )
    return [f"{label}: {value}" for label, value in fields if value]


def _memory_claim_lines(m: records.Memory, sections: list[str] | None) -> list[str]:
    """The claim, and the body unless the sections asked for are only the conclusion."""
    out = ["", "## Claim", " ".join(m.claim.split())]
    if (
        not (sections and any(s.strip().casefold() == "conclusion" for s in sections))
        and m.body.strip()
    ):
        out += ["", m.body.rstrip("\n")]
    return out


def _memory_block(m: records.Memory, sections: list[str] | None) -> str:
    out = [f"== m:{m.handle} ({m.scope})", _memory_facts(m), *_memory_source_lines(m)]
    found = records.tallies(m)
    ends = [t.since for t in found[1:]] + [datetime.date.today()]
    out += [common._tally_line(t, end) for t, end in zip(found, ends, strict=False)]
    out += _memory_tail_lines(m)
    out += _memory_claim_lines(m, sections)
    return "\n".join(out)


def _is_memory_arg(args: argparse.Namespace, arg: str) -> bool:
    """`m:<handle>`, or a bare handle that names no note and does name a memory."""
    if arg.startswith("m:"):
        return True
    if "/" in arg or arg.endswith(".md"):
        return False
    root = common._optional_store(args)
    if root is not None and common.resolve_note(root, arg) is not None:
        return False
    return common._find_memory(args, arg) is not None


def _synthesis_section_block(
    syn: document.Synthesis, handle: str, section: str, lines: list[str]
) -> str | None:
    """The text of one section of a synthesis; None after a message when it has no such section."""
    found = [s for s in syn.sections if s.handle == section]
    if not found:
        print(f"mem: no section {section} in s:{handle}", file=sys.stderr)
        return None
    start = found[0].line - 1
    stop = next((x.line - 1 for x in syn.sections if x.line > found[0].line), len(lines))
    return "\n".join([f"== s:{handle}#{section}", *lines[start:stop]]).rstrip("\n")


def _synthesis_body_lines(args: argparse.Namespace, text: str, lines: list[str]) -> list[str]:
    """The lines of a whole synthesis `mem show` prints: its outline, the chosen sections or the file."""
    frontmatter = cast("re.Match[str]", document._FRONTMATTER.match(text))  # `syn` parsed this text
    first = text[: frontmatter.end()].count("\n")
    body = lines[first:]
    if args.outline and not args.ranges:
        return [f"{first + 1 + i}: {line}" for i, _, line in _headings(body)]
    if args.section and not args.outline:
        return _sections(body, args.section)
    if args.all and not args.outline:
        return lines
    # a synthesis is long: the outline with ranges is the default, `--all` prints the file
    return _outline_ranges(body, first + 1)


def _synthesis_block(args: argparse.Namespace, ref: str) -> str | None:
    """`s:<h>` the whole file (or its outline or `--section`s), `s:<h>#<section handle>` one section; None after a message."""
    handle, section = document.split_ref(ref)
    path = document.path_of(args.root / document.SYNTHESES_DIR, handle)
    if path is None or not path.is_file():
        print(f"mem: no synthesis {ref}", file=sys.stderr)
        return None
    syn = document.load_one(path)
    if syn.error:
        print(f"mem: {path}: {syn.error}", file=sys.stderr)
        return None
    text = path.read_bytes().decode("utf-8", "replace")
    if not args.stored:  # a reader gets `[n]`, the note's place on the `Sources:` line, not the 29-token reference; line numbers stay
        text = document.shown_file(text)
    lines = text.split("\n")
    if section is not None:
        return _synthesis_section_block(syn, handle, section, lines)
    out = [f"== s:{handle}", *_synthesis_body_lines(args, text, lines)]
    return "\n".join(out).rstrip("\n")


def _project_synthesis_block(ref: str, memory_dir: Path, tree: Path) -> str:
    """The outline of `p:NAME` or the text of `p:NAME#HANDLE`; ProjectSynthesisError when it does not exist."""
    name, handle = common._split_part_ref(ref)
    found = common._load_project_syntheses(memory_dir, name)
    parts = found.get(name)
    if parts is None:
        raise project_syntheses.Unavailable(
            f"no project synthesis {name!r}; parts that exist: {common._existing_parts(found)}"
        )
    if handle is None:
        return "\n".join(common._part_line(name, p, tree) for p in parts)
    part = next((p for p in parts if p.handle == handle), None)
    if part is None:
        raise project_syntheses.Unavailable(
            f"no part {handle!r} in {name}; parts that exist: {common._existing_parts(found)}"
        )
    state = project_syntheses.describe(project_syntheses.freshness(tree, part.stamp))
    s = part.stamp
    stamp = project_syntheses._render_stamp(s.paths, s.date, s.commit)
    return f"== p:{name}#{part.handle} ({state})\n{part.heading}\n\n{part.body}\n{stamp}"


@dataclasses.dataclass(frozen=True)
class _ShowPart:
    """What showing one argument produced: its blocks, the paths shown, and whether it went well."""

    blocks: list[str]
    shown: list[str]
    ok: bool
    refused: bool = False


def _show_refused_options(args: argparse.Namespace) -> bool:
    """Whether the options of `mem show` are refused (a message is already printed); `--ranges` alone exits."""
    if args.ranges and not args.outline:
        raise common.UsageError("--ranges needs --outline")
    if args.outline and args.section:
        print("mem: --outline and --section cannot be used together", file=sys.stderr)
        return True
    return bool(args.project) and common._other_projects([args.project], False) is None


def _show_project_handle(args: argparse.Namespace, arg: str) -> _ShowPart | None:
    """A `p:` handle; None when there is no store to read it from."""
    if (
        args.project or args.section
    ):  # refused per handle, so other handles in the call are still shown
        print(
            f"mem: --project and --section do not apply to `p:` handles ({arg})",
            file=sys.stderr,
        )
        return _ShowPart([f"== {arg}\n(not found)"], [], ok=False, refused=True)
    context = common._project_synthesis_context()
    if context is None:
        return None
    try:
        return _ShowPart([_project_synthesis_block(arg, context[0], context[1])], [], ok=True)
    except project_syntheses.ProjectSynthesisError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        refused = not isinstance(exc, project_syntheses.Unavailable)
        return _ShowPart([f"== {arg}\n(not found)"], [], ok=False, refused=refused)


def _show_memory_handle(args: argparse.Namespace, arg: str) -> _ShowPart:
    found = common._find_memory(args, arg.removeprefix("m:"))
    if found is None:
        print(f"mem: no memory {arg}", file=sys.stderr)
        return _ShowPart([f"== {arg}\n(not found)"], [], ok=False)
    if found.error is not None:
        print(f"mem: skipped {found.path}: {found.error}", file=sys.stderr)
        return _ShowPart([], [], ok=False)
    return _ShowPart([_memory_block(found, args.section)], [], ok=True)


def _show_one_arg(args: argparse.Namespace, arg: str) -> _ShowPart | None:
    """One argument of a call that mixes handles and paths; None when the call must stop with exit 2."""
    if arg.startswith("p:"):
        return _show_project_handle(args, arg)
    if arg.startswith("s:"):
        block = _synthesis_block(args, arg)
        return _ShowPart([block or f"== {arg}\n(not found)"], [], ok=block is not None)
    if _is_memory_arg(args, arg):
        return _show_memory_handle(args, arg)
    return _ShowPart(
        *show(args.root, [arg], sections=args.section, outline=args.outline, ranges=args.ranges)
    )


def _show_mixed(args: argparse.Namespace) -> _ShowPart | None:
    """A call with handles among its arguments, shown one by one; None when it must stop with exit 2."""
    blocks: list[str] = []
    shown: list[str] = []
    ok, refused = True, False
    for arg in args.paths:
        part = _show_one_arg(args, arg)
        if part is None:
            return None
        blocks += part.blocks
        shown += part.shown
        ok = ok and part.ok
        refused = refused or part.refused
    return _ShowPart(blocks, shown, ok, refused)


def cmd_show(args: argparse.Namespace) -> int:
    if _show_refused_options(args):
        return 2
    if any(a.startswith(("s:", "p:")) or _is_memory_arg(args, a) for a in args.paths):
        part = _show_mixed(args)
        if part is None:
            return 2
    else:
        part = _ShowPart(
            *show(
                args.root,
                args.paths,
                sections=args.section,
                outline=args.outline,
                ranges=args.ranges,
            )
        )
    print("\n\n".join(part.blocks))
    if part.ok:
        common.log_usage(
            args.root,
            {
                "cmd": "show",
                "paths": list(dict.fromkeys(part.shown)),
                "sections": args.section or [],
                "outline": bool(args.outline),
            },
        )
    return 2 if part.refused else 0 if part.ok else 1


def _stats_orphans(args: argparse.Namespace) -> int:
    root = args.root
    try:
        scopes = _scopes(root, args.paths)
    except ValueError as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    for path in link_rules.orphan_notes(root):
        if _in_scopes(path, scopes):
            print(path)
    return 0


def _stats_topic_count(root: Path) -> int:
    try:
        return len(note_files.load_topics(root))
    except note_files.FrontmatterError:
        return 0


def _stats_note_lines(args: argparse.Namespace, notes: list[note_files.Note]) -> list[str]:
    """The store line, the count per note type and per domain, and the syntheses line."""
    root = args.root
    lines = [f"store: {root} (from {getattr(args, 'root_source', None) or 'unknown'})"]
    lines += [
        f"{kind}: {sum(1 for n in notes if n.type == kind)}" for kind in index_files.INDEX_FOLDERS
    ]
    for kind in ("literature", "knowledge"):
        domains = collections.Counter(n.path.parent.name for n in notes if n.type == kind)
        lines += [f"{kind}/{domain}: {domains[domain]}" for domain in sorted(domains)]
    synths = [s for s in document.load(root / document.SYNTHESES_DIR) if s.error is None]
    if synths:
        lines.insert(
            len(index_files.INDEX_FOLDERS) + 1,
            f"syntheses: {len(synths)} ({sum(len(s.parts) for s in synths)} parts)",
        )
    return lines


def _stats_memory_line(args: argparse.Namespace) -> str | None:
    """The count of project and global memories, or None when the store holds none."""
    today = datetime.date.today()
    counts = [
        records.load_memories(folder, scope) for scope, folder in common._memory_folders(args)
    ]
    if not any(counts):
        return None
    counts = [[m for m in group if not records.quarantined(m)] for group in counts]
    live = sum(records.is_live(m, today) for group in counts for m in group)
    return f"memories: {len(counts[0])} project, {len(counts[1])} global ({live} live)"


def _stats_usage_entries() -> int:
    log_path = common._usage_log(os.environ)
    try:
        return 0 if log_path is None else log_path.read_bytes().count(b"\n")
    except OSError:
        return 0


def cmd_stats(args: argparse.Namespace) -> int:
    root = args.root
    if args.paths and not args.orphans:
        raise common.UsageError("PATH needs --orphans")
    if args.orphans:
        return _stats_orphans(args)
    notes = note_files.discover_notes(root)
    topic_count = _stats_topic_count(root)
    chars = 0
    for note in notes:
        chars += len(note.text)
    lines = _stats_note_lines(args, notes)
    memory_line = _stats_memory_line(args)
    if memory_line is not None:
        lines.insert(1, memory_line)
    script = _MEM_PY.read_text(encoding="utf-8")
    lines.append(f"orphans: {len(link_rules.orphan_notes(root))}")
    lines += [
        f"topics: {topic_count}",
        f"characters: {chars}",
        f"tokens: {chars // 4}",
        f"mem.py lines: {len(script.splitlines())}",
    ]
    lines.append(f"usage log entries: {_stats_usage_entries()}")
    print("\n".join(lines))
    return 0


def _deeper_hit(args: argparse.Namespace, query: str, printed: int) -> bool:
    """True when a --deep search would print more note lines than the default one did (`printed`)."""
    try:
        full = note_search.build_corpus(
            args.root,
            topic=args.topic,
            kind=args.kind,
            status=args.status,
            confidence=args.confidence,
            level=args.level,
            superseded=args.superseded,
        )
        return (
            len(
                note_search.rank(full, query, limit=len(full.notes))[
                    args.offset : args.offset + args.limit
                ]
            )
            > printed
        )
    except (note_files.FrontmatterError, OSError):
        return False


@dataclass(frozen=True)
class _SearchContext:
    """What every query of one `mem search` run shares: the corpus, the memories and the syntheses."""

    args: argparse.Namespace
    with_notes: bool
    corpus: note_search.Corpus | None
    names: dict[str, str]
    memories: list[tuple[str, list[records.Memory]]]
    other_memories: list[tuple[str, list[records.Memory]]]
    all_syntheses: list[document.Synthesis]
    default_type: str | None
    filters: dict[str, Any]
    today: datetime.date


@dataclass(frozen=True)
class _QueryHits:
    """What one query found: notes, notes linked to them, memory handles printed and syntheses."""

    result: list[tuple[note_files.Note, float]]
    linked: list[tuple[note_files.Note, float]]
    printed: list[str]
    sections: list[tuple[document.Synthesis, document.Section]]


def _search_check_args(args: argparse.Namespace, queries: list[str]) -> None:
    if not all(records.tokenize(q) for q in queries):
        raise common.UsageError("query has no searchable words: use letters or digits")
    if args.links and args.offset:
        raise common.UsageError("--offset cannot be used with --links")


def _search_filters(args: argparse.Namespace) -> dict[str, Any]:
    return {
        k: getattr(args, k)
        for k in ("type", "topic", "kind", "status", "confidence", "level")
        if getattr(args, k) is not None
    }


def _search_rank(
    args: argparse.Namespace, queries: list[str], default_type: str | None
) -> tuple[
    note_search.Corpus | None,
    list[list[tuple[note_files.Note, float]]],
    list[list[tuple[note_files.Note, float]]],
]:
    """The corpus, and per query its ranked notes and the notes linked to them (none without notes)."""
    if args.scope == "memories":
        return None, [[] for _ in queries], [[] for _ in queries]
    corpus = note_search.build_corpus(
        args.root,
        type=args.type or default_type,
        topic=args.topic,
        kind=args.kind,
        status=args.status,
        confidence=args.confidence,
        level=args.level,
        superseded=args.superseded,
    )
    ranks = [note_search.rank(corpus, q, limit=len(corpus.notes)) for q in queries]
    linkeds = [
        note_search.linked_notes(args.root, corpus, r, args.limit) if args.links else []
        for r in ranks
    ]
    return corpus, ranks, linkeds


def _search_load_memories(
    args: argparse.Namespace, others: list[tuple[str, Path]]
) -> tuple[list[tuple[str, list[records.Memory]]], list[tuple[str, list[records.Memory]]]]:
    """The memories of this project and the global ones, then those of the other projects asked for."""
    memories: list[tuple[str, list[records.Memory]]] = []
    other_memories: list[tuple[str, list[records.Memory]]] = []
    for scope, folder in [
        *common._memory_folders(args),
        *((f"project: {n}", f) for n, f in others),
    ]:
        loaded = records.load_memories(folder, scope.split(":")[0])
        for m in loaded:
            if m.error is not None:
                print(f"mem: skipped {m.path}: {m.error}", file=sys.stderr)
        loaded = [m for m in loaded if not records.quarantined(m)]
        (other_memories if ":" in scope else memories).append((scope, loaded))
    return memories, other_memories


def _search_context(
    args: argparse.Namespace,
    corpus: note_search.Corpus | None,
    filters: dict[str, Any],
    others: list[tuple[str, Path]],
    default_type: str | None,
) -> _SearchContext:
    with_notes = args.scope != "memories"
    names = short_handles(args.root) if args.handles and with_notes else {}
    today = datetime.date.today()
    # memories stay out of any narrowed, paged or path-only note listing, unless they are all that was asked for
    memories, other_memories = (
        _search_load_memories(args, others)
        if args.scope != "notes"
        and not args.offset
        and not filters
        and (args.detail != "paths" or not with_notes)
        else ([], [])
    )
    # like memories, syntheses stay out of any narrowed, paged or path-only listing; they follow the notes
    all_syntheses = (
        document.load(args.root / document.SYNTHESES_DIR)
        if args.deep
        and args.scope == "all"
        and args.root is not None
        and not args.offset
        and not filters
        and args.detail != "paths"
        else []
    )
    return _SearchContext(
        args=args,
        with_notes=with_notes,
        corpus=corpus,
        names=names,
        memories=memories,
        other_memories=other_memories,
        all_syntheses=all_syntheses,
        default_type=default_type,
        filters=filters,
        today=today,
    )


def _search_print_memory_hits(ctx: _SearchContext, scope: str, hits: list[records.Memory]) -> None:
    if ctx.args.detail == "paths":
        print("\n".join(f"m:{m.handle}" for m in hits))
    else:
        print(f"-- memories ({scope}) --")
        print("\n".join(_memory_line(m, ctx.today) for m in hits))


def _search_memory_hits(ctx: _SearchContext, query: str) -> tuple[list[str], bool]:
    """Print the memories matching `query`: their handles (this project and global), and whether any
    came from another project."""
    printed: list[str] = []
    from_others = False
    for scope, loaded in [*ctx.memories, *ctx.other_memories]:
        hits = records.match_memories(
            loaded,
            records.tokenize(query),
            ctx.today,
            tokenize=records.tokenize,
            limit=3,
            include_dead=ctx.args.all_memories,
        )
        if not hits:
            continue
        _search_print_memory_hits(ctx, scope, hits)
        if ":" in scope:
            from_others = True
        else:
            printed += [f"m:{m.handle}" for m in hits]
    return printed, from_others


def _search_print_notes(
    ctx: _SearchContext,
    terms: list[str],
    weights: dict[str, float],
    hits: list[tuple[note_files.Note, float]],
) -> None:
    for note, score in hits:
        print(
            "\n".join(
                format_hit(
                    note,
                    ctx.args.detail,
                    score=score,
                    terms=terms,
                    weights=weights,
                    name=ctx.names.get(note.rel),
                )
            )
        )


def _search_log(ctx: _SearchContext, query: str, hits: _QueryHits) -> None:
    args = ctx.args
    extra = {"links": True, "linked": [note.rel for note, _ in hits.linked]} if args.links else {}
    if hits.printed:
        extra["memories"] = hits.printed
    if args.project or args.all_projects:
        extra["projects"] = len(ctx.other_memories)
    if hits.sections:
        extra["syntheses"] = [f"s:{syn.handle}#{sec.handle}" for syn, sec in hits.sections]
    if args.deep:
        extra["deep"] = True
    common.log_usage(
        args.root,
        {
            "cmd": "search",
            "query": query,
            "limit": args.limit,
            "detail": args.detail,
            "filters": ctx.filters,
            "results": [note.rel for note, _ in hits.result],
            **extra,
        },
    )


def _search_print_query(ctx: _SearchContext, query: str, hits: _QueryHits, found: bool) -> None:
    """Print the notes, the linked notes and the syntheses of one query after its memories."""
    args = ctx.args
    if ctx.with_notes and found and hits.result:
        print("-- notes --")
    if not hits.result and not found and not args.offset:
        print("no matches", file=sys.stderr)
    terms = records.tokenize(query)
    weights = note_search.term_idf(ctx.corpus, terms) if ctx.corpus is not None else {}
    _search_print_notes(ctx, terms, weights, hits.result)
    if hits.linked and args.detail != "paths":
        print("-- linked to the results above --")
    _search_print_notes(ctx, terms, weights, hits.linked)
    if hits.sections:
        print("-- syntheses (extended versions) --")
        for syn, sec in hits.sections:
            print(f"s:{syn.handle}#{sec.handle}\t{syn.title}: {sec.heading}")


def _search_one(
    ctx: _SearchContext,
    query: str,
    ranked: list[tuple[note_files.Note, float]],
    linked: list[tuple[note_files.Note, float]],
    more: bool,
) -> bool:
    """Run one query; True when a --deep search would show more (`more` carries earlier queries)."""
    args = ctx.args
    result = ranked[args.offset : args.offset + args.limit]
    if args.also:
        print(f"== {query} ==")
    printed, from_others = _search_memory_hits(ctx, query)
    sections = synthesis_edit.match_sections(
        ctx.all_syntheses, records.tokenize(query), tokenize=records.tokenize
    )
    hits = _QueryHits(result, linked, printed, sections)
    _search_print_query(ctx, query, hits, bool(printed or from_others))
    if ctx.default_type and ctx.with_notes and len(result) < _SPARSE_HITS and not more:
        more = _deeper_hit(args, query, len(result))
    if not args.also and ctx.with_notes:  # a footer names --offset, which applies to every query
        _page_footer(args.offset, len(result), len(ranked))
    _search_log(ctx, query, hits)
    return more


def cmd_search(args: argparse.Namespace) -> int:
    queries = [args.query, *args.also]
    _search_check_args(args, queries)
    others = (
        common._other_projects(args.project, args.all_projects)
        if args.project or args.all_projects
        else []
    )
    if others is None:
        return 2
    filters = _search_filters(args)
    default_type = None if args.deep or args.type else "knowledge"
    try:
        corpus, ranks, linkeds = _search_rank(args, queries, default_type)
    except (note_files.FrontmatterError, OSError) as exc:
        print(f"mem: cannot search: {exc}", file=sys.stderr)
        return 1
    ctx = _search_context(args, corpus, filters, others, default_type)
    more = False
    for query, ranked, linked in zip(queries, ranks, linkeds, strict=False):
        more = _search_one(ctx, query, ranked, linked, more)
    if more:
        print("mem: more in sources and syntheses: repeat with --deep.", file=sys.stderr)
    return 0


def cmd_passages(args: argparse.Namespace) -> int:
    if not records.tokenize(args.query):
        raise common.UsageError("query has no searchable words: use letters or digits")
    try:
        notes = {n.rel for n in note_files.discover_notes(args.root) if n.type == "literature"}
    except (note_files.FrontmatterError, OSError) as exc:
        print(f"mem: cannot read passages: {exc}", file=sys.stderr)
        return 1
    path = common.resolve_note(args.root, args.path)  # a path or handle, like `show`
    if isinstance(path, list):
        common._ambiguous(args.path, path)
        return 1
    rel = path.relative_to(args.root.resolve()).as_posix() if path else args.path
    source = source_text(args.root, rel) if rel in notes else None
    if source is None:
        print(
            f"mem: no source text for {args.path}: looked for a .txt in "
            f"{common.SOURCES_DIR}/{Path(rel).stem}/ (needs a literature note path); `mem fetch-sources {args.path}` "
            "downloads the source when it has a url, and writes a .txt only for a plain-text response "
            "or a PDF with pdftotext installed",
            file=sys.stderr,
        )
        return 1
    total, found = passages(
        source.read_text(encoding="utf-8", errors="replace"),
        args.query,
        count=args.count,
        words=args.words,
    )
    if not found:
        print(
            f"no matching passage in {source.relative_to(args.root).as_posix()} ({total} words)",
            file=sys.stderr,
        )
    else:
        print(f"source: {source.relative_to(args.root).as_posix()} ({total} words)")
        print("\n\n".join(f"== words {a}-{b} of {total} ==\n{t}" for a, b, t in found))
    common.log_usage(
        args.root,
        {
            "cmd": "passages",
            "path": rel,
            "query": args.query,
            "count": args.count,
            "words": args.words,
            "hits": len(found),
        },
    )
    return 0


def _related_load(
    args: argparse.Namespace, rel: str | None
) -> tuple[note_search.Corpus, dict[str, list[note_files.Note]]]:
    corpus = note_search.build_corpus(args.root, superseded=args.superseded)
    if rel is None:
        raise ValueError(f"not a note: {rel}")  # what `related` raises for it
    return corpus, note_search.related(args.root, rel, limit=args.limit, corpus=corpus)


def _related_print(
    args: argparse.Namespace,
    rel: str,
    corpus: note_search.Corpus,
    groups: dict[str, list[note_files.Note]],
) -> None:
    terms = records.tokenize(note_search._title(next(n for n in corpus.notes if n.rel == rel)))
    weights = note_search.term_idf(corpus, terms)
    if args.unlinked_mentions:
        groups = {"mentions": note_search.unlinked_mentions(args.root, rel, corpus)}
    for relation, notes in groups.items():
        for other in notes:
            first, *rest = format_hit(other, args.detail, terms=terms, weights=weights)
            print("\n".join([f"{relation}\t{first}", *rest]))
    print(
        " · ".join(f"{relation}: {len(notes)}" for relation, notes in groups.items()),
        file=sys.stderr,
    )


def cmd_related(args: argparse.Namespace) -> int:
    path = common.resolve_note(args.root, args.path)
    if isinstance(path, list):
        common._ambiguous(args.path, path)
        return 1
    rel = path.relative_to(args.root.resolve()).as_posix() if path else None
    try:
        corpus, groups = _related_load(args, rel)
    except ValueError:
        print(f"mem: not a note: {args.path}", file=sys.stderr)
        return 1
    except (note_files.FrontmatterError, OSError) as exc:
        print(f"mem: cannot relate: {exc}", file=sys.stderr)
        return 1
    assert rel is not None  # `_related_load` raised for a missing note
    _related_print(args, rel, corpus, groups)
    return 0


def cmd_search_eval(args: argparse.Namespace) -> int:
    try:
        outcome = note_search.search_eval(args.root)
    except (note_files.FrontmatterError, OSError) as exc:
        print(f"mem: cannot evaluate search: {exc}", file=sys.stderr)
        return 1
    if outcome is None:
        print(f"mem: {note_search._EVAL_FILE} not found", file=sys.stderr)
        return 0
    misses, found, expected, reciprocal = outcome
    for miss in misses:
        print(miss)
    recall = found / expected if expected else 1.0
    print(f"recall@10: {recall:.2f} ({found}/{expected})")
    mrr = reciprocal / expected if expected else 1.0
    print(f"MRR@10: {mrr:.3f}")
    if args.min is not None:
        return 1 if recall < args.min else 0
    if recall < RECALL_TRIGGER or mrr < MRR_TRIGGER:
        print(
            f"search-eval: below the revisit trigger (recall@10 {RECALL_TRIGGER:.2f}, MRR@10 {MRR_TRIGGER:.3f}): "
            "see C-6 in docs/requirements.md",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    today = args.today or datetime.date.today()
    for line in (
        due_queries.due_requirements(args.root, today)
        + due_queries.due_retests(args.root, today)
        + due_queries.due_rereads(args.root, today)
    ):
        print(line)
    return 0
