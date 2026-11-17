"""Memory records: one Markdown file with YAML frontmatter per memory.

Imports nothing from mem.py (mem.py imports this module), so similarity takes token iterables.
"""
from __future__ import annotations

import datetime
import re
import subprocess
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml

KINDS = ("decision", "constraint", "pitfall", "lesson", "finding", "state")
STATUSES = ("active", "refuted", "superseded")
PROJECT_DIR = ".memory"
GLOBAL_DIR = "memories"
STORE_MARKER = "mem-store.yaml"


@dataclass
class Memory:
    scope: str
    path: Path
    handle: str
    kind: str
    claim: str
    created: datetime.date | None
    observed: int
    status: str
    context: str | None
    valid_until: datetime.date | None
    sources: list[str]
    body: str
    error: str | None


def _git_common_dir(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=False,
        )
    except (OSError, ValueError):
        return None
    line = out.stdout.strip()
    if out.returncode != 0 or not line:
        return None
    return Path(line)


def project_root(cwd: Path, env: Mapping[str, str]) -> Path | None:
    override = env.get("MEM_PROJECT")
    if override:
        return Path(override)
    common = _git_common_dir(cwd)
    return common.parent if common else None


def memory_dir(scope: str, *, store: Path | None, project: Path | None) -> Path | None:
    if scope == "project":
        return project / PROJECT_DIR if project is not None else None
    return store / GLOBAL_DIR if store is not None else None


def _date(value, name: str) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        raise ValueError(f"{name} must be a date")
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        return datetime.date.fromisoformat(value)
    raise ValueError(f"{name} must be an ISO date")


def _split(text: str) -> tuple[dict, str]:
    m = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not m:
        raise ValueError("no YAML frontmatter")
    meta = yaml.safe_load(m.group(1))
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a mapping")
    return meta, text[m.end():]


def _parse(path: Path, scope: str) -> Memory:
    base = Memory(scope, path, path.stem, "lesson", "", None, 1, "active", None, None, [], "", None)
    try:
        meta, body = _split(path.read_text(encoding="utf-8"))
        kind = meta.get("kind")
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        claim = meta.get("claim")
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError("claim is missing")
        observed = meta.get("observed", 1)
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 1:
            raise ValueError("observed must be an integer of at least 1")
        status = meta.get("status", "active")
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        context = meta.get("context")
        if context is not None and not isinstance(context, str):
            raise ValueError("context must be a string")
        sources = meta.get("sources") or []
        if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
            raise ValueError("sources must be a list of strings")
        return replace(base, kind=kind, claim=claim.strip(), created=_date(meta.get("created"), "created"),
                       observed=observed, status=status, context=context,
                       valid_until=_date(meta.get("valid_until"), "valid_until"),
                       sources=list(sources), body=body)
    except Exception as e:  # one broken file must not break the rest
        return replace(base, error=f"{type(e).__name__}: {e}".splitlines()[0])


def load_memories(folder: Path | None, scope: str) -> list[Memory]:
    try:
        if folder is None or not folder.is_dir():
            return []
        return [_parse(p, scope) for p in sorted(folder.glob("*.md"), key=lambda p: p.stem) if p.is_file()]
    except OSError:
        return []


def slug_of(claim: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", claim).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", ascii_text.lower())[:8]
    slug = "-".join(words)[:60].strip("-")
    return slug or "memory"


def _render(m: Memory, extra: Mapping[str, str] | None = None) -> str:
    meta: dict = {"kind": m.kind, "claim": m.claim}
    if m.created:
        meta["created"] = m.created.isoformat()
    meta["observed"] = m.observed
    meta["status"] = m.status
    if m.context:
        meta["context"] = m.context
    if m.valid_until:
        meta["valid_until"] = m.valid_until.isoformat()
    if m.sources:
        meta["sources"] = list(m.sources)
    meta.update(extra or {})
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6)
    return f"---\n{head}---\n{m.body}"


def write_memory(folder: Path, scope: str, *, kind: str, claim: str, body: str, today: datetime.date,
                 context: str | None = None, valid_until: datetime.date | None = None,
                 sources: Sequence[str] = ()) -> Memory:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    claim = claim.strip()
    if not claim:
        raise ValueError("claim is empty")
    folder.mkdir(parents=True, exist_ok=True)
    base = slug_of(claim)
    handle, n = base, 1
    while True:
        path = folder / f"{handle}.md"
        m = Memory(scope, path, handle, kind, claim, today, 1, "active", context, valid_until,
                   list(sources), body if body.endswith("\n") or not body else body + "\n", None)
        try:
            with path.open("x", encoding="utf-8") as f:  # exclusive: never overwrite
                f.write(_render(m))
            return m
        except FileExistsError:
            n += 1
            handle = f"{base}-{n}"


def is_live(memory: Memory, today: datetime.date) -> bool:
    return (memory.error is None and memory.status == "active"
            and (memory.valid_until is None or memory.valid_until >= today))


def similarity(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def observe(memory: Memory, today: datetime.date) -> Memory:
    updated = replace(memory, observed=memory.observed + 1)
    memory.path.write_text(_render(updated, {"last_observed": today.isoformat()}), encoding="utf-8")
    return updated


def ensure_excluded(project: Path) -> bool:
    try:
        if (project / PROJECT_DIR).exists():
            return False
        common = _git_common_dir(project)
        if common is None:
            return False
        exclude = common / "info" / "exclude"
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        lines = {ln.strip() for ln in existing.splitlines()}
        if lines & {".memory/", ".memory", "/.memory/", "/.memory"}:
            return False
        exclude.parent.mkdir(parents=True, exist_ok=True)
        sep = "" if not existing or existing.endswith("\n") else "\n"
        exclude.write_text(f"{existing}{sep}{PROJECT_DIR}/\n", encoding="utf-8")
        return True
    except Exception:
        return False


def forbidden_line(text: str, env: Mapping[str, str]) -> int | None:
    if env.get("XDG_CONFIG_HOME"):
        base = Path(env["XDG_CONFIG_HOME"])
    elif env.get("HOME"):
        base = Path(env["HOME"]) / ".config"
    else:
        return None
    try:
        terms = (base / "agent-memory" / "forbidden-terms").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    low = text.lower()
    for i, term in enumerate(terms, 1):
        term = term.strip()
        if term and term.lower() in low:
            return i
    return None


def store_is_writable(store: Path, env: Mapping[str, str]) -> bool:
    return (store / STORE_MARKER).is_file() or env.get("MEM_ALLOW_WRITE") == "1"
