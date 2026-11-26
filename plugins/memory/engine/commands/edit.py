"""The `new`, `note` (edit and marks), `rename` and `unify` handlers (A5, ADR 0028): the commands that write notes, with `new_note`, the attach-to-section helpers and `_NEW_FIELDS`."""

from __future__ import annotations

import collections
import contextlib
import dataclasses
import datetime
import json
import os
import re
import sys
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

import yaml
from core import safe_io
from memories import records
from notes import check as check_rules
from notes import fields as note_fields
from notes import index as index_files
from notes import links as link_rules
from notes import note as note_files
from notes import search as note_search
from syntheses import document, units
from syntheses import edit as synthesis_edit

from commands import common

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

_NOTE_PATH_PARTS = 3  # `<folder>/<domain>/<file>.md`


class NoteFormatError(ValueError):
    """A note file that a command cannot edit as it is."""


def _dump_frontmatter(data: dict) -> str:
    dumped = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=None, width=float("inf")
    )
    return f"---\n{dumped}---\n"


def _knowledge_name_problem(stem: str) -> str | None:
    if word := note_fields.instruction_word(stem):
        return (
            f'knowledge name reads as an instruction ("{word}-..."): {note_fields._INSTRUCTION_FIX}'
        )
    if len(stem) > check_rules.MAX_KNOWLEDGE_NAME:
        return f"knowledge name too long ({len(stem)} characters): {check_rules._LONG_NAME_FIX}"
    return None


def _note_template_and_topics(root: Path, note_type: str) -> tuple[str, dict]:
    """The template body of a note type and the known topics, from the hub."""
    template = root / "templates" / f"{note_type}.md"
    try:
        _, template_body, _ = note_files.split_frontmatter(note_files._read_text(template))
        known = note_files.load_topics(root)
    except note_files.FrontmatterError as exc:
        raise common.NewNoteError(f"cannot read template or topics: {exc}") from exc
    return template_body, known


def _note_domain_and_topics(known: dict, topics: list[str]) -> tuple[str, list[str]]:
    """The root topic (the folder) of the first topic, and every topic with its ancestors."""
    if not topics:
        raise common.NewNoteError("at least one topic is required")
    for t in topics:
        if t not in known:
            raise common.NewNoteError(
                f"unknown topic '{t}': use an id from topics.yaml or add it there"
            )
    domain = note_files.root_of(known, topics[0])
    if domain not in note_files.root_topics(known):
        raise common.NewNoteError(
            f"topic '{topics[0]}' has no root topic (its parent chain ends at "
            f"'{domain}'): fix its parent in topics.yaml"
        )
    all_topics = list(topics)
    for t in topics:
        all_topics += [a for a in note_files.ancestors(known, t) if a not in all_topics]
    return domain, all_topics


def _note_literature_target(
    root: Path, domain: str, slug: str, meta: dict[str, Any], today: datetime.date
) -> tuple[Path, str]:
    """Fill the literature fields of `meta`; return the target path and the name to check."""
    author = meta.pop("author", "")
    names = [a.strip() for a in author.split(",") if a.strip()] if isinstance(author, str) else []
    meta["authors"] = names
    first = note_files.slugify(names[0]) if names else ""
    if not first:
        raise common.NewNoteError(
            "author must contain at least one ASCII letter or digit to form the filename"
        )
    if check_rules._starts_with_author(slug.split("-"), first):
        raise common.NewNoteError(
            f"slug '{slug}' repeats the first author '{first}', which the "
            f"filename already holds: drop '{first}-' from --slug"
        )
    if slug.split("-", maxsplit=1)[0] == str(meta.get("year")):
        raise common.NewNoteError(
            f"slug '{slug}' repeats the year; `new` adds '<year>-<author>-' "
            "itself: pass only the descriptive part as --slug"
        )
    name = f"{meta.get('year')}-{first}-{slug}.md"
    meta["added"] = today.isoformat()
    return root / "literature" / domain / name, name


def _note_knowledge_target(
    root: Path, domain: str, slug: str, meta: dict[str, Any], today: datetime.date
) -> tuple[Path, str]:
    """Fill the knowledge fields of `meta`; return the target path and the name to check."""
    if problem := _knowledge_name_problem(slug):
        raise common.NewNoteError(problem)
    meta["updated"] = today.isoformat()
    pattern_name = f"{slug}.md"
    return root / "knowledge" / domain / pattern_name, pattern_name


def _note_research_target(
    root: Path, domain: str, slug: str, meta: dict[str, Any], today: datetime.date
) -> tuple[Path, str]:
    """Fill the research fields of `meta`; return the target path and the name to check."""
    meta.update(status="idea", started=f"{today:%Y-%m}")
    pattern_name = f"{today:%Y-%m}-{slug}"
    return root / "research" / pattern_name / "README.md", pattern_name


_NOTE_TARGETS = {
    "literature": _note_literature_target,
    "knowledge": _note_knowledge_target,
}


def _note_ordered_fields(note_type: str, meta: dict[str, Any]) -> dict[str, Any]:
    """`meta` in schema order, every value validated; raises on a missing, invalid or extra field."""
    ordered = {}
    for field, validator in note_fields.SCHEMAS[note_type].items():
        if field not in meta and field in note_fields.OPTIONAL_FIELDS:
            continue
        if field not in meta:
            raise common.NewNoteError(f"missing value for '{field}'")
        if (fix := validator(meta[field])) is not None:
            raise common.NewNoteError(f"invalid value for '{field}': {fix}")
        ordered[field] = meta[field]
    extra = set(meta) - set(ordered)
    if extra:
        raise common.NewNoteError(f"unexpected fields for {note_type}: {', '.join(sorted(extra))}")
    return ordered


def _note_refuse_existing(root: Path, note_type: str, target: Path) -> None:
    if note_type == "research" and target.parent.exists():
        raise common.NewNoteError(
            f"folder {target.parent.relative_to(root).as_posix()} already exists: "
            "choose another slug"
        )
    if target.exists():
        raise common.NewNoteError(f"{target.relative_to(root).as_posix()} already exists")


def new_note(
    root: Path,
    note_type: str,
    *,
    slug: str,
    topics: list[str],
    today: datetime.date,
    **fields: Any,
) -> Path:
    """Create a note from its template (or with the `body` field in place of the template body),
    refusing bad slugs, unknown topics and existing paths."""
    if note_type not in note_fields.SCHEMAS:
        raise common.NewNoteError(f"unknown note type '{note_type}'")
    body = fields.pop("body", None)
    template_body, known = _note_template_and_topics(root, note_type)
    domain, all_topics = _note_domain_and_topics(known, topics)

    meta: dict[str, Any] = dict(fields)
    plan_target = _NOTE_TARGETS.get(note_type, _note_research_target)
    target, pattern_name = plan_target(root, domain, slug, meta, today)
    meta["topics"] = all_topics

    if not check_rules.NAME_PATTERNS[note_type].fullmatch(pattern_name):
        raise common.NewNoteError(
            f"invalid name '{pattern_name}': {check_rules._NAME_FIX[note_type]}"
        )
    ordered = _note_ordered_fields(note_type, meta)
    _note_refuse_existing(root, note_type, target)

    target.parent.mkdir(parents=True, exist_ok=True)
    safe_io.replace_file(
        target,
        (_dump_frontmatter(ordered) + (template_body if body is None else body)).encode("utf-8"),
    )
    try:
        index_files.apply_index(root)
    except note_files.FrontmatterError as exc:
        raise common.NewNoteError(
            f"{target.relative_to(root).as_posix()} was created but the index "
            f"was not updated ({exc}): fix it, then run mem index"
        ) from exc
    return target


def _link_points_at(base: Path, target: str, raw: str, old: Path) -> bool:
    """Whether the link `target` (`raw` is its path part) in the file `base` points at the file `old`."""
    if target.startswith(("#", "mailto:")) or link_rules._SCHEME.match(target) or not raw:
        return False
    try:
        return (base.parent / urllib.parse.unquote(raw)).resolve() == old
    except (OSError, ValueError):
        return False


def _link_edits(
    text: str, base: Path, old: Path, new_name: str, new_path: Path | None = None
) -> tuple[str, int]:
    """`text` of the file `base` with each relative link to `old` pointing at `new_name`, and their count.

    Links are found as `_relative_links` finds them (code is masked in place, so offsets stay valid);
    only the file name of the path part changes: prefix, `#anchor` and link text are kept. With `new_path`
    (resolved, like `old` and `base`) the whole path part is recomputed from `base`'s folder instead, because
    the note may sit in another folder.
    """
    lines = text.split("\n")
    masked = link_rules._CODE_SPAN.sub(
        lambda m: re.sub(r"[^\n]", " ", m.group(0)),
        "\n".join(
            " " * len(l) if f else l
            for l, f in zip(lines, link_rules._in_fence(lines), strict=False)
        ),
    )
    count = 0
    for i, line in enumerate(masked.split("\n")):
        for start, end in reversed(link_rules._target_spans(line, True)):
            target = line[start:end]
            raw = target.split("#", 1)[0]
            hit = _link_points_at(base, target, raw, old)
            if hit and new_path is not None:
                lines[i] = (
                    lines[i][:start]
                    + Path(os.path.relpath(new_path, base.parent)).as_posix()
                    + lines[i][start + len(raw) :]
                )
                count += 1
            elif hit:
                cut = start + len(raw) - len(raw.rsplit("/", 1)[-1])
                lines[i] = lines[i][:cut] + new_name + lines[i][start + len(raw) :]
                count += 1
    return "\n".join(lines), count


def _rename_handle_fields(text: str, old: str, new: str) -> tuple[str, int]:
    """`text` with `superseded_by` and `distinct_from` values that name the note `old` naming `new`, and their count."""
    # `part_of` is not renamed here: it names a synthesis, and `rename` takes only literature and knowledge notes.
    try:
        meta, _, _ = note_files.split_frontmatter(text)
    except note_files.FrontmatterError:
        return text, 0
    count = 0
    if isinstance(meta, dict):
        if meta.get("superseded_by") == old:
            text, count = common._set_field(text, "superseded_by", new), count + 1
        names = meta.get("distinct_from")
        if isinstance(names, list) and old in names:
            text, count = (
                common._set_field(
                    text, "distinct_from", sorted(new if h == old else h for h in names)
                ),
                count + 1,
            )
    return text, count


def _rename_source(root: Path, arg: str) -> Path:
    """The literature or knowledge note `arg` names exactly, else a refusal."""
    old = common.resolve_note(root, arg, prefix=False)
    if isinstance(old, list):
        raise common.NewNoteError(
            f"ambiguous: {arg} matches {len(old)} notes: {', '.join(old[:10])}"
        )
    parts = old.relative_to(root).parts if old else ()
    if (
        old is None
        or len(parts) != _NOTE_PATH_PARTS
        or parts[0] not in {"literature", "knowledge"}
        or old.name == "README.md"
        or note_files._is_hidden(old, root)
    ):
        raise common.NewNoteError(
            f"{arg} is not a literature or knowledge note: give its path or exact handle "
            "(no prefix; investigations are not renamed)"
        )
    return old


def _rename_keep_literature_prefix(root: Path, old: Path, stem: str) -> None:
    """Refuse a new literature name that drops the `<year>-<author>-` prefix or repeats it after it."""
    meta = note_files._read_note("literature", old, root).meta
    authors = meta.get("authors") if isinstance(meta, dict) else None
    year, *tokens = old.stem.split("-")
    slug = (
        note_files.slugify(cast("list[str]", authors)[0])  # `_authors` found a valid list
        if note_fields._authors(authors) is None
        else tokens[0]
    )  # as rule_consistency: may span tokens
    n = next((k for k in range(1, len(tokens)) if "".join(tokens[:k]) == slug), 1)
    new_year, *new_tokens = stem.split("-")
    if new_year != year or tokens[:n] != new_tokens[:n]:
        raise common.NewNoteError(f"the name must keep the prefix {'-'.join([year, *tokens[:n]])}-")
    if (rest := new_tokens[n:]) and (
        check_rules._starts_with_author(rest, slug) or rest[0] == year
    ):
        raise common.NewNoteError("the name repeats the author or the year after the prefix")


def _rename_check_name(root: Path, old: Path, kind: str, stem: str) -> None:
    """Refuse a new name that breaks the naming rules of the kind or is taken by another note."""
    name = f"{stem}.md"
    if not check_rules.NAME_PATTERNS[kind].fullmatch(name):
        raise common.NewNoteError(f"invalid name '{name}': {check_rules._NAME_FIX[kind]}")
    if kind == "knowledge" and (problem := _knowledge_name_problem(stem)):
        raise common.NewNoteError(problem)
    if kind == "literature":
        _rename_keep_literature_prefix(root, old, stem)
    if old.with_name(name).exists() or any(
        note_files._handle(p.relative_to(root).as_posix()) == stem
        for _, p in note_files._note_files(root)
    ):
        raise common.NewNoteError(f"a note named '{stem}' already exists")


def _rename_link_edits(root: Path, old: Path, stem: str) -> tuple[dict[Path, str], int]:
    """The new text of every markdown file that links to, or names the handle or copy of, `old`; and the count."""
    edits: dict[Path, str] = {}
    links = 0
    copy = f"{common.SOURCES_DIR}/{old.stem}/"
    for path in link_rules._markdown_files(root):
        try:
            text = note_files._read_text(path)
        except note_files.FrontmatterError as exc:
            raise common.NewNoteError(
                f"cannot read {path.relative_to(root).as_posix()} to rewrite its links ({exc}): "
                "fix it, then rename"
            ) from exc
        edited, count = _link_edits(text, path, old, f"{stem}.md")
        count += edited.count(copy)  # a note's text naming its local copy
        edited, named = _rename_handle_fields(edited, old.stem, stem)
        count += named
        if count:
            edits[path], links = (
                edited.replace(copy, f"{common.SOURCES_DIR}/{stem}/"),
                links + count,
            )
    return edits, links


def _rename_refuse_locked(root: Path, paths: list[Path]) -> None:
    locked = [p for p in paths if not os.access(p, os.W_OK)]
    if locked:
        raise common.NewNoteError(
            f"not writable: {', '.join(p.relative_to(root).as_posix() for p in locked)}"
        )


def rename_note(root: Path, arg: str, new_stem: str) -> tuple[Path, int, int]:
    """Rename a literature or knowledge note in its folder; return (new path, links rewritten, files changed).

    Every edit is computed before anything is written, so a refusal leaves the hub untouched.
    """
    root = root.resolve()
    old = _rename_source(root, arg)
    stem = new_stem.removesuffix(".md")
    new = old.with_name(f"{stem}.md")
    _rename_check_name(root, old, old.relative_to(root).parts[0], stem)
    sources, new_sources = root / common.SOURCES_DIR / old.stem, root / common.SOURCES_DIR / stem
    if new_sources.exists():
        raise common.NewNoteError(f"{common.SOURCES_DIR}/{stem} already exists")
    edits, links = _rename_link_edits(root, old, stem)
    _rename_refuse_locked(
        root, [*edits, old, old.parent, *((sources, sources.parent) if sources.is_dir() else ())]
    )
    originals = {(new if p == old else p): p.read_bytes() for p in (*edits, old)}
    listings = _index_files(root)
    for path, text in edits.items():
        safe_io.replace_file(path, text.encode("utf-8"))
    old.rename(new)
    if sources.is_dir():
        sources.rename(new_sources)
    try:
        index_files.apply_index(root)
    except note_files.FrontmatterError as exc:
        raise common.NewNoteError(
            f"{new.relative_to(root).as_posix()} was renamed but the index was not "
            f"updated ({exc}): fix it, then run mem index"
        ) from exc
    common._log_group(root, _with_changed_listings(originals, listings), "rename", {new: old})
    return new, links, len(edits)


_CONFIDENCE_ORDER = ("low", "medium", "high")


def _index_files(root: Path) -> dict[Path, bytes]:
    """The README listing files that `apply_index` may rewrite, with their bytes now (those that exist)."""
    try:
        targets = index_files.index_targets(
            root, note_files.discover_notes(root), note_files.load_topics(root)
        )
    except note_files.FrontmatterError:
        return {}
    return {t.path: t.path.read_bytes() for t in targets if t.path.is_file()}


def _with_changed_listings(
    originals: dict[Path, bytes], listings: Mapping[Path, bytes]
) -> dict[Path, bytes]:
    """`originals` plus each listing file in `listings` whose bytes are not what they were."""
    return {**{p: b for p, b in listings.items() if p.read_bytes() != b}, **originals}


def _resolve_notes(root: Path, args: Sequence[str]) -> list[Path]:
    typed = {p.resolve() for _, p in note_files._note_files(root)}
    found = []
    for arg in args:
        path = common.resolve_note(root, arg)
        if isinstance(path, list):
            raise common.NewNoteError(
                f"ambiguous: {arg} matches {len(path)} notes: {', '.join(path[:10])}"
            )
        if path is None or path not in typed:
            raise common.NewNoteError(f"no note {arg}")
        found.append(path)
    return found


@dataclass(frozen=True)
class UnifyRequest:
    """What the owner asked `unify_notes` to write: the unified text, whether dropped links are meant, the date."""

    body: str
    drop: bool
    today: datetime.date


def _unify_readable_notes(root: Path, paths: list[Path]) -> list[note_files.Note]:
    """The parsed notes of `paths`, refusing the same note twice, an unreadable one and mixed types."""
    if len(set(paths)) != len(paths):
        raise common.NewNoteError("the same note is named twice: unify needs different notes")
    notes = [note_files._read_note(p.relative_to(root).parts[0], p, root) for p in paths]
    for note in notes:
        if note.error is not None or not isinstance(note.meta, dict):
            raise common.NewNoteError(
                f"{note.rel} cannot be read ({note.error or 'frontmatter is not a mapping'})"
            )
    if len({n.type for n in notes}) > 1:
        raise common.NewNoteError("the notes are of different types: unify joins notes of one type")
    return notes


def _unify_refuse_superseded(root: Path, notes: list[note_files.Note]) -> None:
    """Refuse a note already superseded, and any note in the store that a note to unify supersedes."""
    for note in notes:
        if note.meta.get("superseded_by") is not None:
            raise common.NewNoteError(
                f"{note.rel} is already superseded by {note.meta['superseded_by']}"
            )
    handles = {note_files._handle(n.rel) for n in notes}
    for note in note_files.discover_notes(root):
        if isinstance(note.meta, dict) and note.meta.get("superseded_by") in handles:
            raise common.NewNoteError(
                f"{note.rel} is already superseded by {note.meta['superseded_by']}: unify into the "
                "note that replaced it, or leave it"
            )


def _unify_refuse_lost_links(
    root: Path, notes: list[note_files.Note], body: str, drop: bool
) -> None:
    """Refuse a unified text that drops links of the notes, unless the owner passed `--drop`."""
    unified = {n.rel for n in notes}
    had = set().union(*(note_search._link_targets(root, n) for n in notes))
    lost = sorted(
        had - note_search._link_targets(root, dataclasses.replace(notes[0], body=body)) - unified
    )
    if lost and not drop:
        raise common.NewNoteError(
            f"the unified text drops the links {', '.join(lost)}; use --drop if that is meant."
        )


def _unify_keep_text(notes: list[note_files.Note], request: UnifyRequest) -> str:
    """The text of the kept note: the new body, the union of the topics, the lowest confidence."""
    keep, others = notes[0], notes[1:]
    keep_text = note_files._read_text(keep.path)
    m = common._split_frontmatter_block(keep_text)
    if m is None:
        raise common.NewNoteError(f"{keep.rel} has no frontmatter")
    union = list(keep.meta.get("topics") or [])
    union += [t for o in others for t in (o.meta.get("topics") or []) if t not in union]
    new_text = common._set_field(keep_text[: m.end()] + request.body, "topics", union)
    if "confidence" in note_fields.SCHEMAS[keep.type]:
        ranks = [
            _CONFIDENCE_ORDER.index(n.meta["confidence"])
            for n in notes
            if n.meta.get("confidence") in _CONFIDENCE_ORDER
        ]
        if ranks:
            new_text = common._set_field(new_text, "confidence", _CONFIDENCE_ORDER[min(ranks)])
    if keep.type == "knowledge":
        new_text = common._set_field(new_text, "updated", request.today.isoformat())
    return new_text


def _unify_current_text(root: Path, path: Path, edits: dict[Path, str]) -> str:
    """The text of a file as it stands with the edits so far."""
    original = edits.get(path.resolve())
    if original is not None:
        return original
    try:
        return note_files._read_text(path)
    except note_files.FrontmatterError as exc:
        raise common.NewNoteError(
            f"cannot read {path.relative_to(root).as_posix()} to rewrite its links ({exc}): "
            "fix it, then unify"
        ) from exc


def _unify_rewrite_links(
    root: Path, edits: dict[Path, str], others: list[note_files.Note], keep_path: Path
) -> int:
    """Point every link to an other note at the kept note, adding the files to `edits`; the count."""
    links = 0
    skip = {o.path for o in others}
    for path in link_rules._markdown_files(root):
        rel = path.relative_to(root).as_posix()
        if path.resolve() in skip or link_rules._is_index_readme(rel):
            continue
        resolved = path.resolve()
        original = _unify_current_text(root, path, edits)
        text = original
        for o in others:
            text, count = _link_edits(text, resolved, o.path, "", keep_path)
            links += count
        if text != original:
            edits[resolved] = text
    return links


def _unify_write(root: Path, edits: dict[Path, str]) -> None:
    for path in edits:  # a note resolved outside the store raises ValueError here, before any write
        path.relative_to(root)
    for path, text in edits.items():
        safe_io.replace_file(path, text.encode("utf-8"))


def _unify_new_problems(
    root: Path, keep_rel: str, before: collections.Counter[tuple[str, str]]
) -> list[note_fields.Problem]:
    """The `check` problems the edits introduced; an index that cannot be updated is one."""
    try:
        index_files.apply_index(root)
        after = check_rules.check(root)
        more = (
            collections.Counter((p.path, p.message) for p in after) - before
        )  # counted: a second copy is new
        return [p for p in after if (p.path, p.message) in more]
    except note_files.FrontmatterError as exc:
        return [note_fields.Problem(keep_rel, 1, f"the index was not updated ({exc})")]


def _unify_undo_on_problems(
    root: Path, originals: dict[Path, bytes], problems: list[note_fields.Problem]
) -> None:
    """With problems, put every file back and raise them; with none, do nothing."""
    if not problems:
        return
    for path, data in originals.items():
        safe_io.replace_file(path, data)
    with contextlib.suppress(note_files.FrontmatterError, OSError):
        index_files.apply_index(root)
    raise common.NewNoteError(
        f"the unified notes have {len(problems)} problems, so nothing was written:\n"
        + "\n".join(str(p) for p in problems)
    )


def unify_notes(
    root: Path, keep_arg: str, other_args: Sequence[str], request: UnifyRequest
) -> tuple[Path, int, int]:
    """Make `keep_arg` the unified note of itself and `other_args`; return (keep path, notes unified, links rewritten).

    The kept note takes the request's body, the union of the topics and the lowest confidence; each other note
    gets `superseded_by` and stays as a file; every link to an other note in the store points at the kept note.
    The result must pass `check`, else every file is put back and the problems are raised."""
    root = root.resolve()
    notes = _unify_readable_notes(root, _resolve_notes(root, [keep_arg, *other_args]))
    keep, others = notes[0], notes[1:]
    _unify_refuse_superseded(root, notes)
    _unify_refuse_lost_links(root, notes, request.body, request.drop)

    edits: dict[Path, str] = {keep.path: _unify_keep_text(notes, request)}
    for o in others:
        edits[o.path] = common._set_field(
            note_files._read_text(o.path), "superseded_by", note_files._handle(keep.rel)
        )
    links = _unify_rewrite_links(root, edits, others, keep.path)
    _rename_refuse_locked(root, list(edits))

    # Line numbers move with the edit, so a problem is known by its file and message: the store may hold
    # problems older than this change (an imported note that links a document left behind), and they do not block it.
    before = collections.Counter((p.path, p.message) for p in check_rules.check(root))
    originals = {p: p.read_bytes() for p in edits}
    listings = _index_files(root)
    _unify_write(root, edits)
    _unify_undo_on_problems(root, originals, _unify_new_problems(root, keep.rel, before))
    common._log_group(root, _with_changed_listings(originals, listings), "unify")
    return keep.path, len(notes), links


SIMILAR_LIMIT = 3


def _own_topics(known: dict, topics: Sequence[str]) -> list[str]:
    """The topics a note was filed under: those that are not the ancestor of another listed topic."""
    return [
        t for t in topics if not any(t in note_files.ancestors(known, o) for o in topics if o != t)
    ]


def _covering(root: Path, topics: Sequence[str]) -> list[document.Synthesis]:
    """Syntheses that list one of `topics` by its exact id (no ancestors, no descendants)."""
    try:
        known = note_files.load_topics(root)
    except note_files.FrontmatterError:
        known = {}
    own = set(_own_topics(known, topics))
    return [
        x
        for x in document.load(root / document.SYNTHESES_DIR)
        if x.error is None and own & set(x.topics)
    ]


def _log_note(root: Path, path: Path, rel: str, action: str) -> None:
    """The note's current text, appended to the store's `.curation-log` before a curation action changes it."""
    entry = {
        "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": action,
        "handle": rel,
        "before": path.read_bytes().decode("utf-8"),
    }
    safe_io.append_text(root / records.CURATION_LOG, json.dumps(entry, ensure_ascii=False) + "\n")


def _set_part_of(text: str, part_of: str, digest: str) -> str:
    m = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
    if m is None:
        raise ValueError("the note has no frontmatter")
    kept = [ln for ln in m.group(1).split("\n") if not re.match(r"part_of(_hash)?:", ln)]
    head = (
        "---\n"
        + "\n".join([
            *kept,
            f"part_of: {json.dumps(part_of)}",
            f"part_of_hash: {json.dumps(digest)}",
        ])
        + "\n---\n"
    )
    return head + text[m.end() :]


def _attach(args: argparse.Namespace) -> int:
    root = args.root
    found = common.resolve_note(root, args.note)
    if isinstance(found, list):
        common._ambiguous(args.note, found)
        return 2
    if found is None:
        print(f"mem: no note {args.note}", file=sys.stderr)
        return 2
    rel = found.relative_to(root.resolve()).as_posix()
    if not rel.startswith("knowledge/"):
        print(
            f"mem: {rel} is not a knowledge note: only knowledge notes are part of a synthesis",
            file=sys.stderr,
        )
        return 2
    try:
        syn, sec = common._section_ref(root, args.target)
        text = note_files._read_text(found)
        _log_note(root, found, rel, "attach")
        safe_io.replace_file(
            found,
            _set_part_of(
                text,
                f"{syn.handle}#{sec.handle}",
                units.note_fingerprint(sec.text, common._note_target(rel)),
            ).encode("utf-8"),
        )
    except (ValueError, OSError, note_files.FrontmatterError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    print(f"{note_files._handle(rel)}\tpart of s:{syn.handle}#{sec.handle}")
    common.log_usage(root, {"cmd": "synthesis", "action": "attach"})
    return 0


def _lf(text: str, rel: str) -> str:
    if "\r" in text:
        raise ValueError(f"{rel} has CRLF line ends: convert it to LF first")
    return text


@dataclass(frozen=True)
class _NoteWritten:
    """A note `mem new` wrote and the text it was given (None when the command gave none)."""

    path: Path
    body: str | None


def _new_link_part(args: argparse.Namespace, fields: dict[str, Any]) -> str | None:
    """With `--part-of`, add the link to the section it names to `fields`; returns that section's text."""
    if not getattr(args, "part_of", None):
        return None
    syn, sec = common._section_ref(args.root, args.part_of)
    fields["part_of"] = f"{syn.handle}#{sec.handle}"
    fields["part_of_hash"] = units.fingerprint(sec.text)
    return sec.text


def _new_write(
    args: argparse.Namespace, fields: dict[str, Any], topics: list[str]
) -> int | _NoteWritten:
    """Write the note after the secret and term checks; the exit code of a refusal instead. `fields` gains the
    `--part-of` link."""
    body = common._read_body(args.body_file) if args.body_file else None
    if common._refuse_secret([*(v for v in fields.values() if isinstance(v, str)), body or ""]):
        return 4
    texts = [
        str(fields[k])
        for k in ("title", "claim", "url", "question", "author", "slug")
        if k in fields
    ]
    if refused := common._check_terms(
        [*texts, args.slug, body or ""], "note", getattr(args, "owner_approved", False)
    ):
        return refused
    part_text = _new_link_part(args, fields)  # the text of the section `--part-of` names
    path = new_note(
        args.root,
        args.type,
        slug=args.slug,
        topics=topics,
        today=datetime.date.today(),
        body=body,
        **fields,
    )
    if part_text is not None:
        stamp = units.note_fingerprint(
            part_text, common._note_target(path.relative_to(args.root).as_posix())
        )
        if stamp != fields["part_of_hash"]:
            safe_io.replace_file(
                path,
                common._set_field(note_files._read_text(path), "part_of_hash", stamp).encode(
                    "utf-8"
                ),
            )
    return _NoteWritten(path, body)


def _new_covering_hint(args: argparse.Namespace, fields: dict[str, Any], topics: list[str]) -> None:
    """Name the syntheses that cover the topics of a knowledge note that is part of none."""
    if args.type != "knowledge" or "part_of" in fields:
        return
    for syn in _covering(args.root, topics):
        print(
            f"mem: s:{syn.handle} ({syn.title}) covers this topic; a curation pass can attach this note to it "
            "(mem curate --notes).",
            file=sys.stderr,
        )


def _new_check_hint(root: Path, rel: str, body: str | None) -> None:
    """List the check problems of the new note when the command gave it a text."""
    if body is not None and (found := [p for p in check_rules.check(root) if p.path == rel]):
        print(f"check: {len(found)} problems in {rel}:", file=sys.stderr)
        for problem in found:
            print(problem, file=sys.stderr)


def _new_similar_hint(args: argparse.Namespace, fields: dict[str, Any], rel: str) -> None:
    """List the notes that look like the new one."""
    query = fields.get("claim") or fields.get("title") if args.type != "research" else None
    if not (query and records.tokenize(query)):
        return
    try:
        similar = [
            r for r in note_search.search(args.root, query, limit=SIMILAR_LIMIT + 1) if r[0] != rel
        ]
    except (note_files.FrontmatterError, OSError):  # the note exists; the hint is optional
        similar = []
    if similar:
        print(
            "Similar notes exist: link them, or edit the existing note if it states the same claim.",
            file=sys.stderr,
        )
        for other, score, title in similar[:SIMILAR_LIMIT]:
            print(f"similar: {other}\t{score:.2f}\t{title}", file=sys.stderr)


def _new_research_hint(args: argparse.Namespace, rel: str) -> None:
    """Say that an investigation with its own material lives on a branch."""
    if args.type != "research":
        return
    branch = f"research/{Path(rel).parent.name}"
    print(
        f"An investigation with its own material lives on a branch (ADR 0006): before committing, "
        f"git switch -c {branch} (uncommitted files move with you); add literature and knowledge "
        "notes on main, then merge main into it.",
        file=sys.stderr,
    )


def _new_report(
    args: argparse.Namespace, fields: dict[str, Any], topics: list[str], written: _NoteWritten
) -> None:
    """The new note's path, then the hints about syntheses, check problems, similar notes and branches."""
    rel = written.path.relative_to(args.root).as_posix()
    print(rel)
    _new_covering_hint(args, fields, topics)
    _new_check_hint(args.root, rel, written.body)
    _new_similar_hint(args, fields, rel)
    _new_research_hint(args, rel)


def cmd_new(args: argparse.Namespace) -> int:
    fields = {k: getattr(args, k) for k in _NEW_FIELDS[args.type]}
    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    try:
        written = _new_write(args, fields, topics)
    except (common.NewNoteError, OSError, ValueError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    if isinstance(written, int):
        return written
    _new_report(args, fields, topics, written)
    return 0


def cmd_unify(args: argparse.Namespace) -> int:
    try:
        body = common._read_body(args.body_file)
        if common._refuse_secret([body]):
            return 4
        if refused := common._check_terms([body], "note", getattr(args, "owner_approved", False)):
            return refused
        keep, count, links = unify_notes(
            args.root,
            args.keep,
            args.others,
            UnifyRequest(body, args.drop, datetime.date.today()),
        )
    except (common.NewNoteError, OSError, ValueError, note_files.FrontmatterError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    print(
        f"{note_files._handle(keep.relative_to(args.root.resolve()).as_posix())}\tunified from {count} notes, {links} links rewritten"
    )
    common.log_usage(args.root, {"cmd": "unify", "notes": count, "links": links, "drop": args.drop})
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    try:
        path, links, files = rename_note(args.root, args.note, args.new_stem)
    except (common.NewNoteError, OSError) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 1
    print(path.relative_to(args.root.resolve()).as_posix())
    print(f"rewrote {links} links in {files} files", file=sys.stderr)
    return 0


def _section_span(text: str, heading: str) -> tuple[list[str], int, int]:
    """The note's lines and the index of the `## heading` line and of the line that ends its text."""
    lines, heads = document._scan(text)
    want = " ".join(heading.removeprefix("## ").split())
    hits = [k for k, (_, h) in enumerate(heads) if " ".join(h.split()) == want]
    if not hits:
        raise ValueError(f"no section '## {want}' in the note")
    if len(hits) > 1:
        raise ValueError(f"the heading '## {want}' is repeated in the note: edit it by hand")
    k = hits[0]
    return lines, heads[k][0], heads[k + 1][0] if k + 1 < len(heads) else len(lines)


class _NoteEditOptions(TypedDict):
    """The keyword part of `_edited_note_text`: what to replace and whether a shrinking edit is allowed."""

    section: str | None
    body: str | None
    claim: str | None
    topics: list[str] | None
    shrink: bool
    today: datetime.date


def _note_replace_section(text: str, section: str, body: str | None, shrink: bool) -> str:
    """The note's text with the text of the `## section` replaced; ValueError when it is empty or shrinks."""
    lines, head, end = _section_span(text, section)
    new = synthesis_edit._clean(body or "")
    if not new:
        raise ValueError("the section text is empty")
    synthesis_edit._check_body(new)
    if not shrink:
        synthesis_edit._guard_shrink("\n".join(lines[head + 1 : end]).strip("\n"), new)
    lines[head + 1 : end] = ["", *new.split("\n"), ""]
    return "\n".join(lines)


def _note_replace_claim(text: str, meta: dict, claim: str, shrink: bool) -> str:
    """The note's text with its claim replaced; ValueError when the note has none, the new one is empty or shrinks."""
    if not isinstance(meta.get("claim"), str):
        raise NoteFormatError("the note has no claim: only a knowledge note does")
    if not claim:
        raise ValueError("the claim is empty")
    if not shrink:
        synthesis_edit._guard_shrink(meta["claim"], claim, sentences=False)
    return common._set_field(text, "claim", claim)


def _note_require_topic(topic: str, topics: list[str], known: dict, path: Path) -> None:
    """ValueError unless the topic exists, belongs to the domain of the note's folder and comes with its ancestors."""
    if topic not in known:
        raise ValueError(f"unknown topic '{topic}': use an id from topics.yaml")
    domain = path.parent.name
    if (
        path.parent.parent.name in {"literature", "knowledge"}
        and note_files.root_of(known, topic) != domain
    ):
        raise ValueError(
            f"topic '{topic}' belongs to the domain {note_files.root_of(known, topic)}, not to {domain}, "
            "where the note lives"
        )
    if missing := [a for a in note_files.ancestors(known, topic) if a not in topics]:
        raise ValueError(f"topic '{topic}' needs its ancestor '{missing[0]}' in the list too")


def _note_replace_topics(text: str, path: Path, topics: list[str], known: dict) -> str:
    """The note's text with its topics replaced; ValueError when the list is empty or a topic is refused."""
    if not topics:
        raise ValueError("at least one topic is required")
    for t in topics:
        _note_require_topic(t, topics, known, path)
    return common._set_field(text, "topics", topics)


def _edited_note_text(
    text: str, path: Path, meta: dict, known: dict, **options: Unpack[_NoteEditOptions]
) -> tuple[str, list[str]]:
    """The note's text with the section text, the claim and the topics replaced (every other byte stays), and what
    changed; ValueError when a change is refused."""
    what = []
    section, claim, topics = options["section"], options["claim"], options["topics"]
    if section is not None:
        text = _note_replace_section(text, section, options["body"], options["shrink"])
        what.append("section " + " ".join(section.removeprefix("## ").split()))
    if claim is not None:
        text = _note_replace_claim(text, meta, claim, options["shrink"])
        what.append("claim")
    if topics is not None:
        text = _note_replace_topics(text, path, topics, known)
        what.append("topics")
    if "updated" in meta:
        text = common._set_field(text, "updated", options["today"].isoformat())
    return text, what


@dataclass(frozen=True)
class _NoteSnapshot:
    """A note as it was read: its file, hub-relative path, bytes, text and frontmatter mapping."""

    found: Path
    rel: str
    original: bytes
    text: str
    meta: dict


def _note_snapshot(root: Path, found: Path) -> _NoteSnapshot:
    """Read the note; ValueError when it has CRLF line ends, NoteFormatError when its frontmatter is no mapping."""
    rel = found.relative_to(root).as_posix()
    original = found.read_bytes()
    text = _lf(original.decode("utf-8"), rel)
    meta = note_files.split_frontmatter(text)[0]
    if not isinstance(meta, dict):
        raise NoteFormatError(f"{rel} has no frontmatter mapping")
    return _NoteSnapshot(found, rel, original, text, meta)


def _note_locate(root: Path, name: str) -> Path | int:
    """The note file `name` names; 2 after listing the candidates when it is ambiguous, ValueError when it is none."""
    found = common.resolve_note(root, name)
    if isinstance(found, list):
        common._ambiguous(name, found)
        return 2
    if found is None or found not in {p.resolve() for _, p in note_files._note_files(root)}:
        raise ValueError(f"no note {name}")
    return found


@dataclass(frozen=True)
class _NoteEditBackup:
    """What a note edit needs to put things back: the listings' bytes, the curation log and its bytes (None when
    it did not exist)."""

    listings: dict[Path, bytes]
    log: Path
    log_before: bytes | None


def _note_edit_backup(root: Path) -> _NoteEditBackup:
    log = root / records.CURATION_LOG
    return _NoteEditBackup(_index_files(root), log, log.read_bytes() if log.exists() else None)


def _note_edit_rollback(snap: _NoteSnapshot, backup: _NoteEditBackup, swapped: bool) -> None:
    """Put the note (when it was swapped), the listings and the log back as they were."""
    if swapped:
        common._swap_file(snap.found, snap.original)
        for path, data in backup.listings.items():
            if path.read_bytes() != data:
                common._swap_file(path, data)
    if backup.log_before is None:
        backup.log.unlink(missing_ok=True)
    else:
        safe_io.replace_file(backup.log, backup.log_before)


def _commit_note_edit(root: Path, snap: _NoteSnapshot, new: str) -> None:
    """Write `new` over the note through the undo log; any failure leaves the note, the listings and the log as
    they were (`mem restore` undoes it)."""
    group = uuid.uuid4().hex
    backup = _note_edit_backup(root)
    entry = {
        "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": "note-edit",
        "handle": snap.rel,
        "group": group,
        "before": snap.text,
        "after": common._sha(new.encode("utf-8")),
    }
    safe_io.append_text(backup.log, json.dumps(entry, ensure_ascii=False) + "\n")
    swapped = False
    try:
        if snap.found.read_bytes() != snap.original:
            raise ValueError(
                f"{snap.rel} changed since it was read, so nothing was written: run the command again"
            )
        common._swap_file(snap.found, new.encode("utf-8"))
        swapped = True
        index_files.apply_index(root)
    except BaseException:  # any failure leaves the note, the listings and the log as they were
        _note_edit_rollback(snap, backup, swapped)
        raise
    common._log_group(root, _with_changed_listings({}, backup.listings), "note-edit", group=group)


def _note_edit_options(args: argparse.Namespace) -> tuple[str | None, list[str] | None]:
    """The claim and the topics of `note edit`, normalized; the parser's error when the options do not fit."""
    if args.section is None and args.claim is None and args.topics is None:
        raise common.UsageError("note edit needs --section, --claim or --topics")
    if (args.section is None) != (args.body_file is None):
        raise common.UsageError("--section and --body-file go together")
    claim = " ".join(args.claim.split()) if args.claim is not None else None
    topics = (
        list(dict.fromkeys(t.strip() for t in args.topics.split(",") if t.strip()))
        if args.topics is not None
        else None
    )
    return claim, topics


def _note_edit(
    args: argparse.Namespace, root: Path, claim: str | None, topics: list[str] | None
) -> int | tuple[str, list[str]]:
    """Edit the note; (its hub-relative path, what changed), or the exit code of a refusal."""
    body = common._read_body(args.body_file) if args.body_file else None
    texts = [args.section or "", body or "", claim or "", *(topics or [])]
    if common._refuse_secret(texts):
        return 4
    if refused := common._check_terms(texts, "note", getattr(args, "owner_approved", False)):
        return refused
    found = _note_locate(root, args.note)
    if isinstance(found, int):
        return found
    snap = _note_snapshot(root, found)
    new, what = _edited_note_text(
        snap.text,
        found,
        snap.meta,
        note_files.load_topics(root),
        section=args.section,
        body=body,
        claim=claim,
        topics=topics,
        shrink=args.shrink,
        today=datetime.date.today(),
    )
    _commit_note_edit(root, snap, new)
    return snap.rel, what


def cmd_note(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    claim, topics = _note_edit_options(args)
    try:
        edited = _note_edit(args, root, claim, topics)
    except (
        common.NewNoteError,
        OSError,
        ValueError,
        note_files.FrontmatterError,
        yaml.YAMLError,
    ) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if isinstance(edited, int):
        return edited
    rel, what = edited
    print(f"{note_files._handle(rel)}\tedited {', '.join(what)}")
    common.log_usage(root, {"cmd": "note", "action": "edit"})
    return 0


def _source_mark(fact: str, source: str, quote: str) -> tuple[str, str, str]:
    """The texts of a confirm or dispute, whitespace collapsed; ValueError when one is empty or the source is no URL."""
    fact, quote, source = (" ".join(t.split()) for t in (fact, quote, source))
    if not fact or not quote:
        raise ValueError("the fact and the quote must not be empty")
    parts = urllib.parse.urlsplit(source)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or note_fields._url(source) is not None
    ):
        raise ValueError("the source must be an http(s) URL")
    return fact, source, quote


def _evidence_line(text: str, line: str) -> str:
    """`text` with `line` appended to its `## Evidence` section (added at the end when the note has none)."""
    if not re.search(r"^## Evidence[ \t]*$", text, re.MULTILINE):
        return text.rstrip("\n") + f"\n\n## Evidence\n\n{line}\n"
    lines, head, end = _section_span(text, "Evidence")
    last = max((i for i in range(head + 1, end) if lines[i].strip()), default=head)
    lines.insert(last + 1, line)
    if last == head:
        lines.insert(last + 1, "")
    return "\n".join(lines)


def _note_mark_require_options(args: argparse.Namespace, clear: bool) -> None:
    """The parser's error when the options of `note confirm | dispute` do not fit."""
    given = [args.fact, args.source, args.quote]
    if clear and any(v is not None for v in given):
        raise common.UsageError("--clear goes alone")
    if not clear and any(v is None for v in given):
        raise common.UsageError(
            f"note {args.note_command} needs --fact, --source and --quote"
            + (" (or --clear)" if args.note_command == "dispute" else "")
        )


def _note_mark_refused(marks: tuple[str, str, str], approved: bool) -> int:
    """0 when the texts may be written, else the exit code after a message on stderr."""
    if common._refuse_secret(list(marks)):
        return 4
    return common._check_terms(list(marks), "note", approved)


def _note_require_knowledge(root: Path, found: Path) -> None:
    """ValueError unless the note is a knowledge note."""
    rel = found.relative_to(root).as_posix()
    if not rel.startswith("knowledge/"):
        raise ValueError(
            f"{rel} is not a knowledge note: only a knowledge note carries evidence and can be disputed"
        )


def _note_mark_text(
    snap: _NoteSnapshot, action: str, clear: bool, marks: tuple[str, str, str], today: str
) -> str:
    """The note's text with the evidence line of a confirm, the dispute of a dispute, or no dispute for `--clear`."""
    fact, source, quote = marks
    if action == "confirm":
        host = urllib.parse.urlsplit(source).netloc
        return _evidence_line(
            snap.text, f'- {today} confirmed: {fact} "{quote}" ([{host}]({source}))'
        )
    if clear:
        if not snap.meta.get("disputed"):
            raise ValueError(f"{snap.rel} is not disputed")
        return common._set_field(snap.text, "disputed", None)
    entry = {"date": today, "fact": fact, "source": source, "quote": quote}
    disputed = snap.meta.get("disputed")
    return common._set_field(
        snap.text, "disputed", [*(disputed if isinstance(disputed, list) else []), entry]
    )


def _note_mark_edit(args: argparse.Namespace, root: Path, clear: bool) -> int | str:
    """Write the verdict; the note's hub-relative path, or the exit code of a refusal."""
    marks = ("", "", "")  # not read with `--clear`
    if not clear:
        marks = _source_mark(args.fact, args.source, args.quote)
        if refused := _note_mark_refused(marks, args.owner_approved):
            return refused
    found = _note_locate(root, args.note)
    if isinstance(found, int):
        return found
    _note_require_knowledge(root, found)
    snap = _note_snapshot(root, found)
    today = datetime.date.today().isoformat()
    new = _note_mark_text(snap, args.note_command, clear, marks, today)
    if "updated" in snap.meta:
        new = common._set_field(new, "updated", today)
    _commit_note_edit(root, snap, new)
    return snap.rel


def _note_mark_verdict(action: str, clear: bool) -> str:
    """The past tense of the command, as the output line words it."""
    if clear:
        return "cleared the dispute"
    return action + ("ed" if action == "confirm" else "d")


def cmd_note_mark(args: argparse.Namespace) -> int:
    """`mem note confirm|dispute`: a source's verdict on a knowledge note, through the `note edit` write path."""
    root = args.root.resolve()
    action = args.note_command
    clear = action == "dispute" and args.clear
    _note_mark_require_options(args, clear)
    try:
        marked = _note_mark_edit(args, root, clear)
    except (
        common.NewNoteError,
        OSError,
        ValueError,
        note_files.FrontmatterError,
        yaml.YAMLError,
    ) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2
    if isinstance(marked, int):
        return marked
    print(f"{note_files._handle(marked)}\t{_note_mark_verdict(action, clear)}")
    common.log_usage(root, {"cmd": "note", "action": action})
    return 0


_NEW_FIELDS = {
    "literature": ("title", "author", "year", "kind", "level", "url"),
    "knowledge": ("claim", "confidence", "level", "origin"),
    "research": ("title", "question"),
}
