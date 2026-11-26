"""The forbidden-terms list, the secret patterns and the checks on a store folder that keep them out of the global scope."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from core import config

from memories.model import KINDS, STORE_MARKER

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


def forbidden_file(env: Mapping[str, str]) -> Path | None:
    base = config.config_dir(env)
    return base / "forbidden-terms" if base is not None else None


class ForbiddenListError(ValueError):
    """The forbidden-terms file exists but cannot be read or decoded."""


TERMS_HEADER = (
    "# Terms that must not reach the global scope, one per line; matching ignores case and accents.\n"
    '# A plain line is a hard term: the write is refused. "soft: <term>" or "soft[<kind>]: <term>" '
    "is a soft term: the owner must approve the write.\n"
    "# Manage the list with: mem terms list | add | remove.\n"
)
TERM_KINDS = (*KINDS, "note", "synthesis")
_SOFT_LINE = re.compile(r"^soft(?:\[([a-z]+)\])?:(.*)$")


class Term(NamedTuple):
    line: int  # line number in the file
    text: str
    soft: bool
    kind: str | None  # a soft term that applies to one kind only


def parse_term(raw: str, line: int = 0) -> Term | None:
    """A term of the list, or None for a blank line or a comment."""
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    m = _SOFT_LINE.match(raw)
    if m:
        return Term(line, m.group(2).strip(), True, m.group(1))
    return Term(line, raw, False, None)


def read_terms(env: Mapping[str, str]) -> list[Term]:
    """The terms of the list; empty when there is no file. Raises ForbiddenListError when it cannot be read."""
    path = forbidden_file(env)
    if path is None or not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ForbiddenListError(str(path)) from exc
    return [t for i, raw in enumerate(lines, 1) if (t := parse_term(raw, i)) is not None]


def ensure_terms_file(env: Mapping[str, str]) -> Path | None:
    """Create the list with its comment header when it does not exist; the path, or None when no folder locates it."""
    path = forbidden_file(env)
    if path is not None and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as f:
            f.write(TERMS_HEADER)
    return path


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    bare = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return " ".join(bare.split())  # a line break between two words must not hide a term


def term_hits(texts: Iterable[str], env: Mapping[str, str], kind: str | None = None) -> list[Term]:
    """The terms found in any text, or in all of them joined, in file order; a soft term with a kind counts only
    for that kind.

    Raises ForbiddenListError when the file exists but cannot be read: the check must fail closed.
    """
    terms = read_terms(env)
    texts = list(texts)
    items = [_fold(t) for t in texts] + [_fold("\n".join(texts))]
    hits = []
    for term in terms:
        if term.kind is not None and term.kind != kind:
            continue
        folded = _fold(term.text)
        if folded and any(folded in item for item in items):
            hits.append(term)
    return hits


def forbidden_line(texts: Iterable[str], env: Mapping[str, str]) -> int | None:
    """Line number of the first hard term found in any text; None when clean or no file."""
    return next((t.line for t in term_hits(texts, env) if not t.soft), None)


_PLACEHOLDER = re.compile(r"^[\"']?(<[^>]*>|\u2026|\.{3}|x{3,}|changeme|example)", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|token)\b[\"']?\s*[:=]\s*[\"']?(\S{8,})"
)

# Deliberately conservative: a false refusal costs one rewrite, a stored secret may be synced elsewhere.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}")),
    (
        "API key",
        re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    ),  # not the "sk-" inside "risk-parity-…"
    ("Slack token", re.compile(r"xox[bpars]-\S{10,}")),
    ("credential in a URL", re.compile(r"://[^/\s:@]+:[^/\s@]+@")),
)


def secret_in(texts: Iterable[str]) -> str | None:
    """Name of the first secret pattern found in any text, or None. The texts are checked one by one and joined."""
    texts = list(texts)
    for text in [*texts, "\n".join(texts)]:
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                return name
        for match in _ASSIGNMENT.finditer(text):
            if not _PLACEHOLDER.match(match.group(1)):
                return "secret assignment"
    return None


def inside(path: Path, folder: Path) -> bool:
    """True when path is folder or lies inside it (symlinks resolved)."""
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except (OSError, ValueError):
        return False


def store_is_writable(store: Path) -> bool:
    return (store / STORE_MARKER).is_file()
