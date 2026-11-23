"""Notes: frontmatter, the YAML loaders, `Note`, topics and handles. Imports no other engine module."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DROPPED_TAGS = {"tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:bool"}


# The C parser is several times faster; searching reads every note. libyaml accepts a tab after a colon
# (`a:\tb`) and words parse errors differently. This is the one place that picks it.
_BaseLoader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class HubLoader(_BaseLoader):
    """SafeLoader that keeps dates and on/off/yes/no as strings."""


# Copy, never mutate: SafeLoader's table is shared with every other user of PyYAML.
HubLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag not in _DROPPED_TAGS]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _no_duplicate_keys(loader: HubLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            duplicate = key in seen
            seen.add(key)
        except TypeError:  # unhashable key: the default constructor reports it
            continue
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark)
    return yaml.constructor.SafeConstructor.construct_mapping(loader, node, deep=deep)


HubLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=HubLoader)


def safe_load(text: str):
    """Plain SafeLoader values (dates stay dates) from the same C parser; HubLoader's rules do not apply."""
    return yaml.load(text, Loader=_BaseLoader)


class FrontmatterError(Exception):
    def __init__(self, message: str, line: int = 1) -> None:
        super().__init__(message)
        self.line = line


def _yaml_problem(exc: yaml.YAMLError, first_line: int) -> tuple[str, int]:
    """One-line description and file line of a YAML error; first_line is where the YAML text starts."""
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
    return problem, (mark.line + first_line if mark is not None else first_line)


def _read_text(path: Path) -> str:
    """UTF-8 text without BOM and with LF newlines; FrontmatterError when unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise FrontmatterError("file is not valid UTF-8") from exc
    except OSError as exc:
        raise FrontmatterError(f"file cannot be read ({exc.strerror or exc})") from exc
    return text.removeprefix("\ufeff").replace("\r\n", "\n")


def split_frontmatter(text: str) -> tuple[Any, str, int]:
    """Return (data, body, 1-based line where the body starts)."""
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise FrontmatterError("missing frontmatter block (file must start with '---')")
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i] == "---":
            try:
                data = load_yaml("\n".join(lines[1:i]))
            except yaml.YAMLError as exc:
                problem, line = _yaml_problem(exc, 2)
                raise FrontmatterError(f"invalid YAML in frontmatter: {problem}", line) from exc
            return data, "\n".join(lines[i + 1 :]), i + 2
    raise FrontmatterError("frontmatter block is not closed with '---'")


@dataclass
class Note:
    type: str
    path: Path
    rel: str
    meta: Any
    body: str
    body_line: int
    text: str
    error: str | None
    error_line: int = 1


def _is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _read_note(note_type: str, path: Path, root: Path) -> Note:
    rel = path.relative_to(root).as_posix()
    try:
        text = _read_text(path)
    except FrontmatterError as exc:
        return Note(note_type, path, rel, None, "", 1, "", str(exc))
    try:
        meta, body, body_line = split_frontmatter(text)
        return Note(note_type, path, rel, meta, body, body_line, text, None)
    except FrontmatterError as exc:
        return Note(note_type, path, rel, None, text, 1, text, str(exc), exc.line)


def _note_files(root: Path) -> list[tuple[str, Path]]:
    """(type, path) of the typed notes: literature/*/*.md and knowledge/*/*.md (not README.md), research/*/README.md."""
    found = [(kind, path) for kind in ("literature", "knowledge") for path in (root / kind).glob("*/*.md")
             if path.name != "README.md"]
    found += [("research", path) for path in (root / "research").glob("*/README.md")]
    return [(kind, path) for kind, path in found if path.is_file() and not _is_hidden(path, root)]


def discover_notes(root: Path) -> list[Note]:
    """Typed notes (see `_note_files`), sorted by path."""
    return sorted((_read_note(kind, path, root) for kind, path in _note_files(root)), key=lambda n: n.rel)


def load_topics(root: Path) -> dict[str, dict]:
    path = root / "topics.yaml"
    if not path.is_file():
        raise FrontmatterError("topics.yaml is missing")
    try:
        data = load_yaml(_read_text(path))
    except yaml.YAMLError as exc:
        problem, line = _yaml_problem(exc, 1)
        raise FrontmatterError(f"invalid YAML in topics.yaml: {problem}", line) from exc
    if not isinstance(data, dict):
        raise FrontmatterError("topics.yaml must be a mapping of topic ids")
    return data


def _parent(topics: dict, tid: str) -> str | None:
    entry = topics.get(tid)
    parent = entry.get("parent") if isinstance(entry, dict) else None
    return parent if isinstance(parent, str) else None


def ancestors(topics: dict, tid: str) -> list[str]:
    """Known parents of tid, nearest first; an unknown or non-string parent and a cycle end the walk and are not included."""
    result: list[str] = []
    seen = {tid}
    current = _parent(topics, tid)
    while current is not None and current in topics and current not in seen:
        result.append(current)
        seen.add(current)
        current = _parent(topics, current)
    return result


def descendants(topics: dict, tid: str) -> set[str]:
    """tid plus every topic that has it as an ancestor."""
    return {tid} | {t for t in topics if tid in ancestors(topics, t)}


def root_topics(topics: dict) -> list[str]:
    """Topic ids with no parent: the domains."""
    return [t for t, e in topics.items() if isinstance(t, str) and isinstance(e, dict) and "parent" not in e]


def root_of(topics: dict, tid: str) -> str:
    """The domain of a known topic: its last ancestor, or itself when it has no parent."""
    return (ancestors(topics, tid) or [tid])[-1]


def leaf_topics(topics: dict, listed: list[str]) -> list[str]:
    return [
        t for t in listed
        if not any(o != t and t in ancestors(topics, o) for o in listed)
    ]


def slugify(s: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def key_line(text: str, key: str) -> int:
    """1-based line of a top-level `key:` inside the frontmatter, else 1."""
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return 1
    for i in range(1, len(lines)):
        if lines[i] == "---":
            break
        if re.match(rf"{re.escape(key)}[ \t]*:", lines[i]):
            return i + 1
    return 1


def _handle(rel: str) -> str:
    """What names a note: the file stem of a literature or knowledge note, the folder id of an investigation."""
    p = Path(rel)
    return p.parent.name if rel.startswith("research/") else p.stem
