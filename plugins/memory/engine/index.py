"""The generated index READMEs: rendering and `apply_index`. Imports only notes and safe_io."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import notes as notes_mod
from core import safe_io
from notes import FrontmatterError, discover_notes, leaf_topics, load_topics, root_of, root_topics

if TYPE_CHECKING:
    from pathlib import Path

    from notes import Note


INDEX_START = "<!-- hub:index:start -->"
INDEX_END = "<!-- hub:index:end -->"
INDEX_FOLDERS = ("literature", "knowledge", "research")

_INDEX_COLUMNS = {
    "literature": ("Year", "Title", "Kind", "Level", "Topics"),
    "knowledge": ("Claim", "Confidence", "Level", "Topics"),
    "research": ("Started", "Title", "Status", "Topics"),
}


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _index_row(note: Note, topics: dict) -> tuple[tuple, list[str]]:
    key, cells = _index_cells(note, topics)
    if note.meta.get("superseded_by") is not None:
        cells[0 if note.type == "knowledge" else 1] += (
            " (superseded)"  # the cell holding the note's link
        )
    return key, cells


def _index_cells(note: Note, topics: dict) -> tuple[tuple, list[str]]:
    meta = note.meta
    listed = meta.get("topics")
    leaves = (
        leaf_topics(topics, [t for t in listed if isinstance(t, str)])
        if isinstance(listed, list)
        else []
    )
    topic_cell = _cell(", ".join(sorted(leaves)))
    if note.type == "literature":
        name = note.path.name
        link = f"[{_cell(meta.get('title', name))}]({name})"
        year = meta.get("year")
        key = (-year if isinstance(year, int) else 0, name)
        return key, [
            _cell(year if year is not None else ""),
            link,
            _cell(meta.get("kind", "")),
            _cell(meta.get("level", "")),
            topic_cell,
        ]
    if note.type == "knowledge":
        name = note.path.name
        link = f"[{_cell(meta.get('claim', name))}]({name})"
        return (name,), [
            link,
            _cell(meta.get("confidence", "")),
            _cell(meta.get("level", "")),
            topic_cell,
        ]
    folder = note.path.parent.name
    link = f"[{_cell(meta.get('title', folder))}]({folder}/README.md)"
    started = str(meta.get("started", ""))
    return (started, folder), [_cell(started), link, _cell(meta.get("status", "")), topic_cell]


def _rows_table(folder: str, rows: list[tuple[tuple, list[str]]]) -> list[str]:
    if folder == "research":
        # started descending, then id ascending
        rows.sort(key=lambda r: r[0][1])
        rows.sort(key=lambda r: r[0][0], reverse=True)
    else:
        rows.sort(key=lambda r: r[0])
    cols = _INDEX_COLUMNS[folder]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    return lines + ["| " + " | ".join(cells) + " |" for _, cells in rows]


def _indexable(notes: list[Note], folder: str) -> list[Note]:
    return [n for n in notes if n.type == folder and n.error is None and isinstance(n.meta, dict)]


def _domain_notes(notes: list[Note], folder: str, domain: str) -> list[Note]:
    return [n for n in _indexable(notes, folder) if n.path.parent.name == domain]


def _subtopics(note: Note, domain: str, topics: dict) -> list[str]:
    """Headings of a note in its domain README: each most-specific topic under the domain, else `general`."""
    listed = note.meta.get("topics")
    leaves = (
        leaf_topics(topics, [t for t in listed if isinstance(t, str) and t in topics])
        if isinstance(listed, list)
        else []
    )
    found = sorted(t for t in leaves if t != domain and root_of(topics, t) == domain)
    return found or ["general"]


def render_index(root: Path, folder: str, notes: list[Note], topics: dict) -> str:
    """Block content between the markers of research/ or of a top-level literature/knowledge README."""
    if folder == "research":
        rows = [_index_row(n, topics) for n in _indexable(notes, folder)]
        return (
            "\n" + "\n".join(_rows_table(folder, rows)) + "\n" if rows else "\n_No entries yet._\n"
        )
    counts = {d: len(_domain_notes(notes, folder, d)) for d in sorted(root_topics(topics))}
    counts = {d: c for d, c in counts.items() if c}
    if not counts:
        return "\n_No entries yet._\n"
    lines = ["| Domain | Notes |", "| --- | --- |"]
    lines += [f"| [{d}]({d}/README.md) | {c} |" for d, c in counts.items()]
    return "\n" + "\n".join(lines) + "\n"


def render_domain_index(folder: str, domain: str, notes: list[Note], topics: dict) -> str:
    """Block content of <folder>/<domain>/README.md: one table per subtopic, `general` last."""
    groups: dict[str, list[tuple[tuple, list[str]]]] = {}
    for n in _domain_notes(notes, folder, domain):
        for heading in _subtopics(n, domain, topics):
            groups.setdefault(heading, []).append(_index_row(n, topics))
    if not groups:
        return "\n_No entries yet._\n"
    out: list[str] = []
    for name in sorted(groups, key=lambda g: (g == "general", g)):
        out += ["", f"### {name}", "", *_rows_table(folder, groups[name])]
    return "\n".join(out) + "\n"


def _with_index(text: str, block: str) -> str:
    """Replace the block between the markers, or append one when there are no markers at all."""
    starts, ends = text.count(INDEX_START), text.count(INDEX_END)
    start, end = text.find(INDEX_START), text.find(INDEX_END)
    if (starts, ends) != (0, 0) and not (starts == ends == 1 and start < end):
        raise FrontmatterError(
            "index markers must be exactly one start marker followed by one "
            "end marker: remove the stray or duplicated markers"
        )
    if starts:
        return text[: start + len(INDEX_START)] + block + text[end:]
    sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + INDEX_START + block + INDEX_END + "\n"


_DOMAIN_PURPOSE = {
    "literature": "Our readings of external sources about {domain}.",
    "knowledge": "Reusable conclusions about {domain}.",
}


class IndexTarget(NamedTuple):
    path: Path
    block: str
    default: str | None  # initial text when the README is missing; None: do not create it


def index_targets(root: Path, notes: list[Note], topics: dict) -> list[IndexTarget]:
    """Every README that carries a generated block."""
    targets = []
    for folder in INDEX_FOLDERS:
        targets.append(
            IndexTarget(
                root / folder / "README.md", render_index(root, folder, notes, topics), None
            )
        )
        if folder == "research":
            continue
        for domain in sorted(root_topics(topics)):
            readme = root / folder / domain / "README.md"
            if readme.is_file() and not _domain_notes(notes, folder, domain):
                targets.append(
                    IndexTarget(readme, render_domain_index(folder, domain, notes, topics), None)
                )
            elif _domain_notes(notes, folder, domain):
                default = (
                    f"# {folder.capitalize()}: {domain}\n\n"
                    f"{_DOMAIN_PURPOSE[folder].format(domain=domain)}\n"
                )
                targets.append(
                    IndexTarget(
                        root / folder / domain / "README.md",
                        render_domain_index(folder, domain, notes, topics),
                        default,
                    )
                )
    return targets


def _new_text(root: Path, target: IndexTarget) -> str | None:
    """The README text with its block rewritten; None when nothing is to be written."""
    path, block, default = target
    if not path.is_file():
        return None if default is None else _with_index(default, block)
    try:
        text = notes_mod._read_text(path)
        new = _with_index(text, block)
    except FrontmatterError as exc:
        raise FrontmatterError(f"{path.relative_to(root).as_posix()}: {exc}") from exc
    return new if new != text else None


def apply_index(root: Path) -> list[str]:
    """Rewrite every index block; return the hub-relative paths that changed."""
    topics = load_topics(root)
    notes = discover_notes(root)
    pending: list[tuple[Path, str]] = []
    for target in index_targets(root, notes, topics):
        new = _new_text(root, target)
        if new is not None:
            pending.append((target.path, new))
    for path, new in pending:  # write only after every README was accepted
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_io.replace_file(path, new.encode("utf-8"))
    return [path.relative_to(root).as_posix() for path, _ in pending]
