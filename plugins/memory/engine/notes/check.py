"""The check rule catalog and `check()`. Pure: no git, environment or writes; never mem."""

from __future__ import annotations

import collections
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from syntheses import document

from notes import index as index_mod
from notes import note as notes_mod
from notes.due import rule_requirements
from notes.fields import (
    _INSTRUCTION_FIX,
    _PART_OF,
    OPTIONAL_FIELDS,
    SCHEMAS,
    Problem,
    _authors,
    instruction_word,
)
from notes.index import INDEX_START, index_targets
from notes.links import rule_links
from notes.note import (
    FrontmatterError,
    ancestors,
    discover_notes,
    key_line,
    load_topics,
    root_of,
    root_topics,
    slugify,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from syntheses.document import Section, Synthesis

    from notes.note import Note


NAME_PATTERNS: dict[str, re.Pattern] = {
    "literature": re.compile(r"[0-9]{4}-[a-z0-9]+-[a-z0-9]+(-[a-z0-9]+)*\.md"),
    "knowledge": re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*\.md"),
    "research": re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])-[a-z0-9]+(-[a-z0-9]+)*"),
}
RESERVED_TOPIC = "general"
_TOPIC_ID = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
_NAME_FIX = {
    "literature": "rename to year-firstauthor-slug.md",
    "knowledge": "rename to lowercase-words-with-hyphens.md, starting with a letter",
    "research": "rename the folder to YYYY-MM-slug",
}


REQUIRED_HEADINGS: dict[str, list[str]] = {
    "literature": ["TL;DR", "What the source says", "Our interpretation", "Relevance"],
    "knowledge": ["Claim", "Evidence", "Applies when", "Does not apply when"],
    "research": ["Question", "Status", "Findings", "Contents"],
}
# An investigation with its own experiments (spec 5.5, ADR 0008) also states what it improves on.
BASELINE_HEADING = "Baseline and contribution"
EXPERIMENT_DIRS = ("code", "results")


def _visible(directory: Path, root: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if not notes_mod._is_hidden(p, root))


def _has_committable_file(folder: Path) -> bool:
    """Whether git would store anything from an investigation folder.

    Its `data/` and the folders `.gitignore` names stay local, so a folder holding only those (left
    behind when its branch was checked out here) is not an investigation on this branch."""
    for dirpath, dirnames, filenames in os.walk(folder):
        local = _LOCAL_DIRS | ({"data"} if Path(dirpath) == folder else set())
        dirnames[:] = [d for d in dirnames if d not in local]
        if filenames:
            return True
    return False


# Longest knowledge filename stem (characters); longer claims belong in `claim`, not the name (C-10).
MAX_KNOWLEDGE_NAME = 80
_LONG_NAME_FIX = (
    f"shorten the filename to at most {MAX_KNOWLEDGE_NAME} characters (keep the full sentence "
    "in `claim`) and update links"
)


def rule_names(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 1: filenames and research folder names; research/ holds only README.md and <id>/."""
    problems = []
    for kind in ("literature", "knowledge"):
        problems += _note_name_problems(root, kind)
    for p in _visible(root / "research", root):
        rel = p.relative_to(root).as_posix()
        if p.is_dir():
            problems += _research_folder_problems(p, rel)
        elif p.name != "README.md":
            problems.append(
                Problem(
                    rel,
                    1,
                    "not allowed here: research/ holds only README.md and "
                    "<id>/ folders; move the file into a research folder",
                )
            )
    return problems


def _name_message(kind: str, p: Path) -> str | None:
    """What is wrong with the file name of a literature or knowledge note, else None."""
    if not NAME_PATTERNS[kind].fullmatch(p.name):
        return f"invalid name: {_NAME_FIX[kind]}"
    if kind != "knowledge":
        return None
    if word := instruction_word(p.stem):
        return f'knowledge name reads as an instruction ("{word}-..."): {_INSTRUCTION_FIX}'
    if len(p.stem) > MAX_KNOWLEDGE_NAME:
        return f"knowledge name too long ({len(p.stem)} characters): {_LONG_NAME_FIX}"
    return None


def _note_name_problems(root: Path, kind: str) -> list[Problem]:
    problems = []
    for domain in _visible(root / kind, root):
        if not domain.is_dir():
            continue
        for p in _visible(domain, root):
            if p.is_file() and p.suffix == ".md" and p.name != "README.md":
                message = _name_message(kind, p)
                if message is not None:
                    problems.append(Problem(p.relative_to(root).as_posix(), 1, message))
    return problems


def _research_folder_problems(p: Path, rel: str) -> list[Problem]:
    problems = []
    if not NAME_PATTERNS["research"].fullmatch(p.name):
        problems.append(Problem(rel, 1, f"invalid name: {_NAME_FIX['research']}"))
    if not (p / "README.md").is_file() and _has_committable_file(p):
        problems.append(
            Problem(
                rel,
                1,
                f"missing readme: create {rel}/README.md "
                "by copying templates/research.md and filling it",
            )
        )
    return problems


def rule_flat(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 7: literature/ and knowledge/ hold README.md and domain folders; those hold only .md files."""
    problems = []
    domains = set(root_topics(topics)) if topics is not None else None
    for kind in ("literature", "knowledge"):
        for p in _visible(root / kind, root):
            rel = p.relative_to(root).as_posix()
            if p.is_dir():
                problems += _flat_folder_problems(root, kind, p, domains)
            elif p.name != "README.md":
                problems.append(
                    Problem(
                        rel,
                        1,
                        f"not allowed here: {kind}/ holds only README.md and "
                        f"domain folders; move the file into {kind}/<domain>/",
                    )
                )
    return problems


def _flat_folder_problems(
    root: Path, kind: str, p: Path, domains: set[str] | None
) -> list[Problem]:
    problems = []
    if domains is not None and p.name not in domains:
        problems.append(
            Problem(
                p.relative_to(root).as_posix(),
                1,
                f"not allowed here: {kind}/ holds only README.md "
                "and folders named after root topics of "
                "topics.yaml; rename or remove it",
            )
        )
    problems.extend(
        Problem(
            q.relative_to(root).as_posix(),
            1,
            f"not allowed here: {kind}/{p.name}/ holds only .md notes; move or remove it",
        )
        for q in _visible(p, root)
        if q.is_dir() or q.suffix != ".md"
    )
    return problems


def rule_domain(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 8: a literature or knowledge note lives under the root of at least one of its topics."""
    if topics is None:
        return []
    problems = []
    for note in notes:
        listed = note.meta.get("topics") if isinstance(note.meta, dict) else None
        if note.type == "research" or not isinstance(listed, list):
            continue
        domains = set(root_topics(topics))
        roots = list(
            dict.fromkeys(root_of(topics, t) for t in listed if isinstance(t, str) and t in topics)
        )
        roots = [r for r in roots if r in domains]
        if roots and note.path.parent.name not in roots:
            fix = " or ".join(f"{note.type}/{r}/" for r in roots)
            problems.append(
                Problem(note.rel, key_line(note.text, "topics"), f"wrong domain: move to {fix}")
            )
    return problems


def _nonempty_dir(path: Path) -> bool:
    """An empty folder does not count: git does not store it, so the staged snapshot would not see it."""
    return path.is_dir() and any(path.iterdir())


def _heading_problems(note: Note) -> list[Problem]:
    lines = [ln.rstrip() for ln in note.body.split("\n")]
    pos = 0
    problems = []
    for heading in REQUIRED_HEADINGS[note.type]:
        try:
            pos = lines.index(f"## {heading}", pos) + 1
        except ValueError:
            problems.append(
                Problem(
                    note.rel,
                    note.body_line,
                    f"missing heading '## {heading}': add it in the order of the template",
                )
            )
    if (
        note.type == "research"
        and f"## {BASELINE_HEADING}" not in lines
        and any(_nonempty_dir(note.path.parent / d) for d in EXPERIMENT_DIRS)
    ):
        problems.append(
            Problem(
                note.rel,
                note.body_line,
                f"missing heading '## {BASELINE_HEADING}' (required once code/ or results/ exists, "
                "spec 5.5): add it, naming the strongest published method that fits our constraints, "
                "the change tested against it and the result",
            )
        )
    return problems


def rule_schema(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 2: frontmatter present, closed schema, typed values, required headings."""
    problems = []
    for note in notes:
        shape = _frontmatter_shape_problem(note)
        if shape is not None:
            problems.append(shape)
            continue
        problems += _field_problems(note)
        problems += _heading_problems(note)
    return problems


def _frontmatter_shape_problem(note: Note) -> Problem | None:
    if note.error is not None:
        return Problem(
            note.rel,
            note.error_line,
            f"invalid frontmatter ({note.error}): fix the block at the top of the file",
        )
    if not isinstance(note.meta, dict):
        return Problem(
            note.rel,
            1,
            "invalid frontmatter (it must be a mapping of fields): rewrite it as key: value lines",
        )
    return None


def _field_problems(note: Note) -> list[Problem]:
    schema = SCHEMAS[note.type]
    problems = [
        Problem(note.rel, 1, f"missing field '{field}': add it to the frontmatter")
        for field in schema
        if field not in note.meta and field not in OPTIONAL_FIELDS
    ]
    for field, value in note.meta.items():
        line = key_line(note.text, str(field))
        if field not in schema:
            problems.append(
                Problem(
                    note.rel, line, f"unknown field '{field}': remove it (the schema is closed)"
                )
            )
        elif (fix := schema[field](value)) is not None:
            problems.append(Problem(note.rel, line, f"invalid value for '{field}': {fix}"))
    return problems


def _starts_with_author(tokens: list[str], first: str) -> bool:
    """True when the slug's first tokens spell the author again ("ethereum-org" for "ethereumorg")."""
    return any("".join(tokens[:k]) == first for k in range(1, len(tokens) + 1))


def rule_consistency(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 3: literature year/author and research started match the file name."""
    problems = []
    for note in notes:
        if not isinstance(note.meta, dict) or note.error is not None:
            continue
        if note.type == "literature":
            problems += _literature_consistency(note)
        elif note.type == "research":
            problems += _started_consistency(note)
    return problems


def _repeat_problem(note: Note, first: str, rest: list[str]) -> Problem | None:
    name = note.path.name
    if rest and _starts_with_author(rest, first):
        kind = "author"
    elif rest and rest[0] == name[:4]:
        kind = "year"
    else:
        return None
    return Problem(
        note.rel, 1, f"{kind} repeated in filename: rename to {name[:4]}-{first}-<rest>.md"
    )


def _literature_consistency(note: Note) -> list[Problem]:
    name = note.path.name
    if not NAME_PATTERNS["literature"].fullmatch(name):
        return []
    _, first, *rest = name.removesuffix(".md").split("-")
    problems = []
    if (repeat := _repeat_problem(note, first, rest)) is not None:
        problems.append(repeat)
    year = note.meta.get("year")
    if isinstance(year, int) and str(year) != name[:4]:
        problems.append(
            Problem(
                note.rel,
                key_line(note.text, "year"),
                f"year mismatch: set year to {name[:4]} or rename the file",
            )
        )
    authors = note.meta.get("authors")
    if isinstance(authors, list) and _authors(authors) is None and slugify(authors[0]) != first:
        problems.append(
            Problem(
                note.rel,
                key_line(note.text, "authors"),
                f"author mismatch: first author must slugify to '{first}'; "
                "fix authors or rename the file",
            )
        )
    return problems


def _started_consistency(note: Note) -> list[Problem]:
    folder = note.path.parent.name
    started = note.meta.get("started")
    if (
        NAME_PATTERNS["research"].fullmatch(folder)
        and isinstance(started, str)
        and started != folder[:7]
    ):
        return [
            Problem(
                note.rel,
                key_line(note.text, "started"),
                f'started mismatch: set started to "{folder[:7]}" or rename the folder',
            )
        ]
    return []


def rule_topics_used(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 4: topics exist, are listed with every ancestor, and are not empty."""
    if topics is None:
        return []
    problems = []
    for note in notes:
        listed = note.meta.get("topics") if isinstance(note.meta, dict) else None
        if not isinstance(listed, list):
            continue
        problems += _note_topic_problems(note, listed, topics)
    return problems


def _note_topic_problems(note: Note, listed: list, topics: dict) -> list[Problem]:
    line = key_line(note.text, "topics")
    problems = []
    if not listed:
        problems.append(
            Problem(
                note.rel, line, "at least one topic is required: list a topic id from topics.yaml"
            )
        )
    names = [t for t in listed if isinstance(t, str)]
    for t in names:
        if t not in topics:
            problems.append(
                Problem(
                    note.rel,
                    line,
                    f"unknown topic '{t}': use an id from topics.yaml or add it there",
                )
            )
            continue
        problems.extend(
            Problem(note.rel, line, f"missing ancestor '{a}' of '{t}': add '{a}' to topics")
            for a in ancestors(topics, t)
            if a not in names
        )
    return problems


def _topic_line(text: str, tid: object) -> int:
    for i, ln in enumerate(text.split("\n"), 1):
        if re.match(rf"{re.escape(str(tid))}[ \t]*:", ln):
            return i
    return 1


def rule_topics_file(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 5: topics.yaml follows 5.6."""
    if topics is None:
        return []
    text = notes_mod._read_text(root / "topics.yaml")
    problems = []
    for tid, entry in topics.items():
        problems += _topic_entry_problems(tid, entry, topics, text)
    problems += _topic_cycle_problems(topics, text)
    return problems


def _bad_topic(text: str, tid: object, why: str, fix: str) -> Problem:
    return Problem(
        "topics.yaml", _topic_line(text, tid), f"invalid topics file entry '{tid}' ({why}): {fix}"
    )


def _topic_entry_problems(tid: object, entry: object, topics: dict, text: str) -> list[Problem]:
    if not isinstance(tid, str) or not _TOPIC_ID.fullmatch(tid):
        return [
            _bad_topic(
                text,
                tid,
                "not a valid id",
                "use lowercase words with hyphens, starting with a letter",
            )
        ]
    if tid == RESERVED_TOPIC:
        return [
            Problem(
                "topics.yaml",
                _topic_line(text, tid),
                f"topic id '{tid}' is reserved (it is the fallback heading of "
                "domain indexes): rename it",
            )
        ]
    if not isinstance(entry, dict):
        return [
            _bad_topic(
                text, tid, "not a mapping", "write it as {parent: ..., description: ...} or {}"
            )
        ]
    return _topic_field_problems(tid, entry, topics, text)


def _topic_field_problems(tid: str, entry: dict, topics: dict, text: str) -> list[Problem]:
    problems = [
        _bad_topic(text, tid, f"unknown field '{key}'", "keep only parent and description")
        for key in entry
        if key not in {"parent", "description"}
    ]
    if "description" in entry and not isinstance(entry["description"], str):
        problems.append(
            _bad_topic(text, tid, "description is not a string", "write a one-line description")
        )
    parent = entry.get("parent")
    if "parent" in entry and not isinstance(parent, str):
        problems.append(
            _bad_topic(text, tid, "parent is not a string", "set parent to an existing topic id")
        )
    elif isinstance(parent, str) and parent not in topics:
        problems.append(
            Problem(
                "topics.yaml",
                _topic_line(text, tid),
                f"unknown parent '{parent}' of '{tid}': add '{parent}' "
                "or point parent at an existing topic",
            )
        )
    return problems


def _topic_cycle_problems(topics: dict, text: str) -> list[Problem]:
    problems = []
    for tid in topics:
        seen, current = set(), notes_mod._parent(topics, tid) if isinstance(tid, str) else None
        while isinstance(current, str) and current not in seen:
            if current == tid:
                problems.append(
                    Problem(
                        "topics.yaml",
                        _topic_line(text, tid),
                        f"cycle through '{tid}': break the parent chain",
                    )
                )
                break
            seen.add(current)
            current = notes_mod._parent(topics, current)
    return problems


def rule_placeholders(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 10: no TODO(hub): lines left in typed notes."""
    return [
        Problem(note.rel, i, "placeholder left from the template: replace the TODO(hub): text")
        for note in notes
        for i, line in enumerate(note.text.split("\n"), 1)
        if line.startswith("TODO(hub):")
    ]


MAX_FILE_BYTES = 5 * 1024 * 1024
_UNTRACKED_DIRS = frozenset({
    "__pycache__",
    ".venv",
    "target",
    "node_modules",
})  # .gitignore entries; hidden ones (.sources/) are skipped as hidden
_LOCAL_DIRS = _UNTRACKED_DIRS | {
    ".pytest_cache",
    ".sources",
    ".playwright-mcp",
}  # every folder name .gitignore keeps out of git


def rule_file_size(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 13: no file over 5 MB (sizes only; contents are never read)."""
    problems = []
    for dirpath, dirnames, filenames in os.walk(root):
        local_data = (
            {"data"} if Path(dirpath).parent == root / "research" else set()
        )  # research/*/data/ never reaches git
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".") and d not in _UNTRACKED_DIRS and d not in local_data
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if name.startswith("."):
                continue
            try:  # lstat: git stores a symlink, not its target; a broken or vanished file is not an error
                size = path.lstat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                problems.append(
                    Problem(
                        path.relative_to(root).as_posix(),
                        1,
                        "file over 5 MB: keep it out of git and link it by https:// URL (spec 5.1)",
                    )
                )
    return problems


def rule_handles(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 14: no two typed notes share a handle (`_handle`), so a handle names one note."""
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for note in notes:
        groups[notes_mod._handle(note.rel)].append(note.rel)
    return [
        Problem(
            rel,
            1,
            f'handle "{h}" is also used by {", ".join(r for r in rels if r != rel)}: '
            "rename one so a handle names one note",
        )
        for h, rels in groups.items()
        if len(rels) > 1
        for rel in rels
    ]


def rule_syntheses(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 15: each synthesis parses, repeats no section handle, uses known topics and ends every part with a
    valid `Sources:` line; a reference names a source and has a sentence before it, and no reference or source
    names a superseded note."""
    loaded = document.load(root / document.SYNTHESES_DIR)
    superseded = {
        (root / n.rel).resolve(): n.meta["superseded_by"]
        for n in notes
        if n.error is None
        and isinstance(n.meta, dict)
        and isinstance(n.meta.get("superseded_by"), str)
    }
    problems = []
    for note in notes:
        problem = _part_of_problem(note, loaded)
        if problem is not None:
            problems.append(problem)
    for syn in loaded:
        problems += _synthesis_problems(syn, root, topics, superseded)
    return problems


def _part_of_problem(note: Note, loaded: list[Synthesis]) -> Problem | None:
    part = note.meta.get("part_of") if note.error is None and isinstance(note.meta, dict) else None
    if not isinstance(part, str) or not _PART_OF.fullmatch(part):
        return None
    handle, _, section = part.partition("#")
    syn = next((x for x in loaded if x.handle == handle and x.error is None), None)
    if syn is None:
        return Problem(
            note.rel,
            key_line(note.text, "part_of"),
            f"part_of names s:{handle}, which does not exist: fix or remove part_of",
        )
    if not any(sec.handle == section for sec in syn.sections):
        return Problem(
            note.rel,
            key_line(note.text, "part_of"),
            f"part_of names the section {section} of s:{handle}, which does not exist: "
            "fix or remove part_of",
        )
    return None


def _section_messages(sec: Section, root: Path, superseded: dict) -> list[str]:
    if sec.handle == document.SUMMARY:
        return document.summary_problems(sec.text)
    msgs = document.validate_section(sec.text, root)
    base = (root / document.SYNTHESES_DIR).resolve()
    cited = [("reference", t) for t in dict.fromkeys(document.references(sec.text))]
    cited += [("source", t) for t in sec.sources]
    for kind, target in cited:
        successor = superseded.get(document._resolved(base, target))
        if successor:
            msgs.append(f"{kind} {target} is superseded by {successor}: point to it")
    return msgs


def _synthesis_problems(
    syn: Synthesis, root: Path, topics: dict | None, superseded: dict
) -> list[Problem]:
    rel = syn.path.relative_to(root).as_posix()
    if syn.error:
        return [
            Problem(
                rel,
                1,
                f"synthesis cannot be parsed ({syn.error}): fix the frontmatter "
                "and start the body with `## Summary`",
            )
        ]
    problems = [
        Problem(rel, 1, f"unknown topic '{t}': use an id from topics.yaml or add it there")
        for t in syn.topics
        if topics is not None and t not in topics
    ]
    seen: set[str] = set()
    for sec in syn.sections:
        if sec.handle in seen:
            problems.append(
                Problem(
                    rel, sec.line, f'repeated section handle "{sec.handle}": rename one heading'
                )
            )
        seen.add(sec.handle)
        problems.extend(
            Problem(rel, sec.line, f'section "{sec.heading}": {msg}')
            for msg in _section_messages(sec, root, superseded)
        )
    return problems


def rule_supersession(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 16: `superseded_by` and `distinct_from` name notes that exist."""
    handles = {notes_mod._handle(n.rel) for n in notes}
    problems = []
    for note in notes:
        if note.error is not None or not isinstance(note.meta, dict):
            continue
        named = [("superseded_by", note.meta.get("superseded_by"))]
        named += (
            [
                ("distinct_from", h)
                for h in (note.meta.get("distinct_from") or [])
                if isinstance(h, str)
            ]
            if isinstance(note.meta.get("distinct_from"), list)
            else []
        )
        for field, value in named:
            if isinstance(value, str) and value not in handles:
                problems.append(
                    Problem(
                        note.rel,
                        key_line(note.text, field),
                        f"{field} names {value}, which is not a note: fix or remove {field}",
                    )
                )
    return problems


def rule_index_fresh(root: Path, notes: list[Note], topics: dict | None) -> list[Problem]:
    """Rule 9: generated index blocks are current."""
    if topics is None:
        return []
    problems = []
    for path, block, default in index_targets(root, notes, topics):
        problem = _index_problem(path.relative_to(root).as_posix(), path, block, default)
        if problem is not None:
            problems.append(problem)
    return problems


def _index_start_line(text: str) -> int:
    start = text.find(INDEX_START)
    return text.count("\n", 0, start) + 1 if start >= 0 else 1


def _index_problem(rel: str, path: Path, block: str, default: object) -> Problem | None:
    if not path.is_file():
        return Problem(rel, 1, "missing readme: run mem index") if default is not None else None
    try:
        text = notes_mod._read_text(path)
    except FrontmatterError as exc:
        return Problem(rel, 1, f"unreadable index README ({exc}): save it as UTF-8 text")
    try:
        current = index_mod._with_index(text, block) == text
    except FrontmatterError as exc:
        return Problem(rel, _index_start_line(text), str(exc))
    return None if current else Problem(rel, _index_start_line(text), "index stale: run mem index")


RULES = [
    rule_names,
    rule_flat,
    rule_domain,
    rule_schema,
    rule_consistency,
    rule_topics_used,
    rule_topics_file,
    rule_links,
    rule_index_fresh,
    rule_placeholders,
    rule_requirements,
    rule_file_size,
    rule_handles,
    rule_syntheses,
    rule_supersession,
]


def check(root: Path) -> list[Problem]:
    problems: list[Problem] = []
    try:
        topics: dict | None = load_topics(root)
    except FrontmatterError as exc:
        topics = None
        problems.append(
            Problem(
                "topics.yaml",
                exc.line,
                f"topics file unusable ({exc}): restore topics.yaml as a mapping of topic ids",
            )
        )
    notes = discover_notes(root)
    for rule in RULES:
        problems += rule(root, notes, topics)
    return sorted(set(problems))


def invalid_changed(store: Path) -> Callable[[list[str]], list[str]]:
    """A validator for `store_git.commit_if_changed`: runs `check` once, on the working tree, and returns the given
    paths that have a problem. The working tree is checked, not the committed snapshot: a committed note may link to a
    held-back one."""

    def validate(paths: list[str]) -> list[str]:
        bad = {p.path for p in check(store)}
        return [
            p for p in paths if p in bad or any(p.startswith(b + "/") for b in bad)
        ]  # a problem may name a folder

    return validate
