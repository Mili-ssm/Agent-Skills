"""Memory records: one Markdown file with YAML frontmatter per memory.

Imports nothing from mem.py (mem.py imports this module), so similarity and match_memories take tokens or a tokenizer.
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import yaml

KINDS = ("decision", "constraint", "pitfall", "lesson", "finding", "document", "state")
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


def _main_worktree(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(cwd), "worktree", "list", "--porcelain"],
                             capture_output=True, text=True, check=False)
    except (OSError, ValueError):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            first = Path(line[len("worktree "):])
            # A submodule lists its git directory (under .git/modules), not its folder: ask for the folder.
            if (first / ".git").exists():
                return first
            return _toplevel(cwd)
    return None


def _toplevel(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=False)
    except (OSError, ValueError):
        return None
    line = out.stdout.strip()
    return Path(line) if out.returncode == 0 and line else None


def project_root(cwd: Path, env: Mapping[str, str]) -> Path | None:
    override = env.get("MEM_PROJECT")
    if override:
        return Path(override).expanduser().resolve()
    return _main_worktree(cwd)


def project_dir(project: Path) -> Path:
    return project / PROJECT_DIR


def _config_base(env: Mapping[str, str]) -> Path | None:
    if env.get("XDG_CONFIG_HOME"):
        return Path(env["XDG_CONFIG_HOME"])
    if env.get("HOME"):
        return Path(env["HOME"]) / ".config"
    return None


def memories_root(env: Mapping[str, str], store: Path | None) -> Path | None:
    """Folder of global memories: MEM_MEMORIES, else the first line of agent-memory/memories, else the writable store's."""
    named = env.get("MEM_MEMORIES")
    if not named:
        base = _config_base(env)
        if base is not None:
            try:
                lines = (base / "agent-memory" / "memories").read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                lines = []
            named = next((ln.strip() for ln in lines if ln.strip()), "")
    if named:
        if named == "~" or named.startswith("~/"):
            named = str(Path(env["HOME"]) / named[2:]) if env.get("HOME") else os.path.expanduser(named)
        return Path(named)
    if store is not None and store_is_writable(store):
        return store / GLOBAL_DIR
    return None


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
    if kind in ("finding", "document") and not sources:
        raise ValueError(f"a {kind} needs at least one source")
    if kind == "finding":
        if valid_until is None:
            valid_until = today + datetime.timedelta(days=90)
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
    try:
        meta, body = _split(memory.path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        meta, body = None, None
    if meta is None:
        text = _render(updated, {"last_observed": today.isoformat()})
    else:  # edit the file's own frontmatter so keys this module does not know survive
        meta["observed"] = updated.observed
        meta["last_observed"] = today.isoformat()
        head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6)
        text = f"---\n{head}---\n{body}"
    tmp = memory.path.with_name(f".{memory.path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, memory.path)
    return updated


def ensure_excluded(project: Path) -> bool:
    """Add `.memory/` to the repository's .git/info/exclude; raises OSError when the line should be written and cannot."""
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


def forbidden_file(env: Mapping[str, str]) -> Path | None:
    base = _config_base(env)
    return base / "agent-memory" / "forbidden-terms" if base is not None else None


class ForbiddenListError(ValueError):
    """The forbidden-terms file exists but cannot be read or decoded."""


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    bare = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return " ".join(bare.split())  # a line break between two words must not hide a term


def forbidden_line(texts: Iterable[str], env: Mapping[str, str]) -> int | None:
    """Line number of the first forbidden term found in any text, or in all of them joined; None when clean or no file.

    Raises ForbiddenListError when the file exists but cannot be read: the check must fail closed.
    """
    path = forbidden_file(env)
    if path is None or not path.exists():
        return None
    try:
        terms = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ForbiddenListError(str(path)) from exc
    texts = list(texts)
    items = [_fold(t) for t in texts] + [_fold("\n".join(texts))]
    for i, term in enumerate(terms, 1):
        term = _fold(term)
        if term and any(term in item for item in items):
            return i
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


STOPWORDS = frozenset("""a an the and or but nor of in on at to for from by with about as into over under
is are was were be been being am do does did has have had will would can could should may might must
i you he she it we they me him her us them my your his its our their this that these those
what which who whom whose when where why how not no if then than so there here""".split())


def match_memories(memories: Sequence[Memory], query_tokens: Sequence[str], today: datetime.date, *,
                   tokenize: Callable[[str], list[str]], limit: int = 3,
                   include_dead: bool = False) -> list[Memory]:
    """Memories holding at least half (rounded up) of the query's non-stop-word terms, best first."""
    terms = set(query_tokens) - STOPWORDS
    if not terms:
        return []
    need = (len(terms) + 1) // 2
    scored = []
    for m in memories:
        if m.error is not None or not (include_dead or is_live(m, today)):
            continue
        in_claim = terms & set(tokenize(m.claim))
        overall = terms & set(tokenize(" ".join([m.claim, m.context or "", m.body])))
        if len(overall) >= need:
            scored.append((m, len(in_claim), len(overall)))
    scored.sort(key=lambda t: (-t[1], -t[2], -t[0].observed, -(t[0].created or datetime.date.min).toordinal(), t[0].handle))
    return [m for m, _, _ in scored[:limit]]
