"""Memory records: one Markdown file with YAML frontmatter per memory.

Imports nothing from mem.py (mem.py imports this module), so similarity and match_memories take tokens or a tokenizer.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Protocol, Required, TypedDict, Unpack

import config
import safe_io
import yaml
from notes import safe_load

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence

logger = logging.getLogger(__name__)

KINDS = ("decision", "constraint", "pitfall", "lesson", "finding", "document", "state")
ORIGINS = ("web", "pipeline", "transcript")
REACHES = ("project", "general")
WEIGHTS = ("light", "medium", "strong")
# Distinct sessions that establish a transcript memory, by weight; a memory with no weight counts as medium.
SIGHTINGS_NEEDED = {"light": 1, "medium": 2, "strong": 3}
UNCONFIRMED_DAYS = 30
SESSION_PREFIX = "session "
OUTCOMES = ("worked", "failed", "seen")
TRIAGES = ("pending",)
PROJECT_KEY_LEN = 12
SHORT_DATE_LEN = 10  # characters of an ISO date
GLOBAL_MIN_PROJECTS = 2  # distinct projects that establish a global memory
SHORT_LIMIT = 120  # characters of the one-line form a lesson loads as at session start
TOPIC_LIMIT = 24
_TOPIC = re.compile(r"[a-z0-9][a-z0-9-]*( [a-z0-9][a-z0-9-]*)?")
STATUSES = ("active", "refuted", "superseded", "forgotten")
PROJECT_DIR = ".memory"
GLOBAL_DIR = "memories"
STORE_MARKER = "mem-store.yaml"
CURATION_LOG = ".curation-log"


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
    last_observed: datetime.date | None = None
    distinct_from: list[str] = field(default_factory=list)
    promote: str | None = None
    refuted: datetime.date | None = None
    superseded_by: str | None = None
    origin: str | None = None  # "web", "pipeline" or "transcript"; None: written in a session
    reach: str | None = None  # "project" or "general": how far the lesson reaches
    weight: str | None = None  # "light", "medium" or "strong": how much it weighs
    owner_confirmed: datetime.date | None = (
        None  # the owner vouched for the lesson: it is established
    )
    triage: str | None = None  # "pending": a global record that left quarantine and awaits triage
    triage_reason: str | None = (
        None  # why a lesson is held at triage; meaningful only while triage is "pending"
    )
    released: datetime.date | None = None  # the day a global record left quarantine
    general: str | None = None  # handle of the global record a project record was generalized into
    short: str | None = (
        None  # the claim in one line of at most SHORT_LIMIT characters, as it loads at session start
    )
    short_by: str | None = (
        None  # "model": the short form was written by a model and the owner has not read it
    )
    topic: str | None = None  # one or two lowercase words that group rules
    from_repository: bool = False  # a repository commits the file: its owner_confirmed is not the reader's (mark_repository)
    load: str | None = (
        None  # "no": the owner turned this lesson's rule off; "index": only counted by topic
    )
    log: list[str] = field(
        default_factory=list
    )  # valid case entries "<date> session <id> <outcome>", in file order
    versions: list[str] = field(
        default_factory=list
    )  # valid entries "<date> <short form>", sorted by date
    reviewed: datetime.date | None = None  # the day the owner looked at a lesson that got worse
    reworded: datetime.date | None = (
        None  # the day the automatic step reworded the short form (once, for good)
    )
    reword_failed: datetime.date | None = (
        None  # the date of the version the automatic step gave up on
    )


def _git_common_dir(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    line = out.stdout.strip()
    if out.returncode != 0 or not line:
        return None
    return Path(line)


def _main_worktree(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            first = Path(line[len("worktree ") :])
            # A submodule lists its git directory (under .git/modules), not its folder: ask for the folder.
            if (first / ".git").exists():
                return first
            return _toplevel(cwd)
    return None


def _toplevel(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
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


REGISTRY_FILE = "projects.json"


def read_registry(data: Path | None) -> dict[str, dict[str, str]]:
    """The registry of projects in the data folder: name -> {path, seen}. Empty when there is no file;
    ValueError when the file cannot be read or is not that shape."""
    if data is None:
        return {}
    try:
        text = (data / REGISTRY_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"the registry of projects cannot be read: {exc}") from exc
    try:
        reg = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"the registry of projects is not valid JSON: {exc}") from exc
    if not isinstance(reg, dict) or not all(
        isinstance(v, dict) and isinstance(v.get("path"), str) for v in reg.values()
    ):
        raise ValueError("the registry of projects has an unexpected shape")
    return reg


def _registry_name(
    reg: dict[str, dict[str, str]], project: Path, held: str | None, name: str | None
) -> str:
    """The name `project` takes in the registry: `name` when free or its own, else the one it holds, else its folder's."""
    if name is not None:
        if held != name and name in reg:
            raise ValueError(f"the name {name} is taken by {reg[name]['path']}")
        return name
    if held is not None:
        return held
    base = project.resolve().name or "project"
    name, n = base, 2
    while name in reg:
        name, n = f"{base}-{n}", n + 1
    return name


def _write_registry(data: Path, reg: dict[str, dict[str, str]]) -> None:
    tmp = data / f"{REGISTRY_FILE}.{os.getpid()}.tmp"
    try:
        tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, data / REGISTRY_FILE)
    finally:
        tmp.unlink(missing_ok=True)


def register_project(
    data: Path | None, project: Path, today: datetime.date, name: str | None = None
) -> str | None:
    """Register `project` (or refresh its `seen` date) in the data folder; its name, None without a data folder.

    The name is the folder's name, with -2, -3 ... when another path holds it; an explicit `name` held by another
    path is a ValueError. The file is replaced whole, so a failure leaves the old one."""
    if data is None:
        return None
    reg = read_registry(data)
    path = str(project.resolve())
    held = next((n for n, v in reg.items() if v["path"] == path), None)
    name = _registry_name(reg, project, held, name)
    if held is not None and held != name:
        del reg[held]
    reg[name] = {"path": path, "seen": today.isoformat()}
    data.mkdir(parents=True, exist_ok=True)
    _write_registry(data, reg)
    return name


def forget_project(data: Path | None, name: str) -> bool:
    """Remove a project from the registry; False when the name is unknown."""
    reg = read_registry(data)
    if data is None or name not in reg:
        return False
    del reg[name]
    _write_registry(data, reg)
    return True


def _configured_memories(env: Mapping[str, str]) -> str:
    """The first non-blank line of agent-memory/memories under the config folder, else an empty string."""
    lines = config.config_lines(env, "memories")
    return next((ln.strip() for ln in lines if ln.strip()), "")


def memories_root(env: Mapping[str, str], store: Path | None) -> Path | None:
    """Folder of global memories: MEM_MEMORIES, else the first line of agent-memory/memories, else the writable store's."""
    named = env.get("MEM_MEMORIES") or _configured_memories(env)
    if named:
        if named == "~" or named.startswith("~/"):
            named = (
                str(Path(env["HOME"]) / named[2:]) if env.get("HOME") else os.path.expanduser(named)
            )
        return Path(named)
    if store is not None and store_is_writable(store):
        return store / GLOBAL_DIR
    return None


def global_memories_root(env: Mapping[str, str]) -> Path | None:
    """The folder of global memories for a command that takes no store argument (the background commands):
    `memories_root` with the store that MEM_STORE names, else the default store. Without this a background run
    that is given only MEM_STORE, as the hooks give it, finds no global memory."""
    store = config.resolve_store(None, env)
    return memories_root(env, store if store is not None and store.is_dir() else None)


class FieldTypeError(ValueError):
    """A frontmatter value of the wrong type; a ValueError so every caller that catches one still catches it."""


def _date(value, name: str) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        raise FieldTypeError(f"{name} must be a date")
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        return datetime.date.fromisoformat(value)
    raise FieldTypeError(f"{name} must be an ISO date")


def _split(text: str) -> tuple[dict, str]:
    m = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
    if not m:
        raise ValueError("no YAML frontmatter")
    meta = safe_load(m.group(1))
    if not isinstance(meta, dict):
        raise FieldTypeError("frontmatter is not a mapping")
    return meta, text[m.end() :]


def valid_short(text) -> bool:
    return (
        isinstance(text, str)
        and bool(text.strip())
        and text == text.strip()
        and len(text) <= SHORT_LIMIT
        and len(text.splitlines()) == 1
    )


TRIAGE_REASON_LIMIT = 200


def valid_triage_reason(text) -> bool:
    return (
        isinstance(text, str)
        and bool(text.strip())
        and text == text.strip()
        and len(text) <= TRIAGE_REASON_LIMIT
        and len(text.splitlines()) == 1
    )


def valid_topic(text) -> bool:
    return (
        isinstance(text, str)
        and len(text) <= TOPIC_LIMIT
        and text != "other"
        and _TOPIC.fullmatch(text) is not None
    )


def _checked_kind(meta: dict) -> str:
    kind = meta.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    return kind


def _checked_claim(meta: dict) -> str:
    claim = meta.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("claim is missing")
    return claim


def _checked_observed(meta: dict) -> int:
    observed = meta.get("observed", 1)
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 1:
        raise ValueError("observed must be an integer of at least 1")
    return observed


def _checked_status(meta: dict) -> str:
    status = meta.get("status", "active")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return status


def _checked_context(meta: dict) -> str | None:
    context = meta.get("context")
    if context is not None and not isinstance(context, str):
        raise ValueError("context must be a string")
    return context


def _checked_sources(meta: dict) -> list[str]:
    sources = meta.get("sources") or []
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise ValueError("sources must be a list of strings")
    return list(sources)


def _required_fields(meta: dict) -> dict:
    """The fields a memory needs, each checked in this order; the first bad one raises ValueError."""
    return {
        "kind": _checked_kind(meta),
        "claim": _checked_claim(meta).strip(),
        "observed": _checked_observed(meta),
        "status": _checked_status(meta),
        "context": _checked_context(meta),
        "sources": _checked_sources(meta),
    }


# a bad value reads as absent: only curation reads these dates, and one must not hide the memory
_LENIENT_DATES = (
    "last_observed",
    "refuted",
    "reviewed",
    "reworded",
    "reword_failed",
    "owner_confirmed",
    "released",
)


def _lenient_date(meta: dict, key: str) -> datetime.date | None:
    try:
        return _date(meta.get(key), key)
    except ValueError:
        return None


_PROMOTE_NO = ("no", False)  # a tuple, not a set: a YAML list or mapping is unhashable


def _promote_of(meta: dict) -> str | None:
    value = meta.get("promote")  # YAML reads a bare no as False
    return "no" if value in _PROMOTE_NO else "done" if value == "done" else None


def _load_of(meta: dict) -> str | None:
    value = meta.get("load")  # YAML reads a bare no as False; 0 is not no
    return "index" if value == "index" else "no" if value == "no" or value is False else None


def _choice(meta: dict, key: str, allowed: Sequence[str]) -> str | None:
    value = meta.get(key)
    return value if value in allowed else None


def _text_fields(meta: dict) -> dict:
    """The optional text fields; a bad value reads as absent."""
    superseded_by = meta.get("superseded_by")
    general = meta.get("general")
    triage = _choice(meta, "triage", TRIAGES)
    reason = meta.get("triage_reason")
    return {
        "superseded_by": str(superseded_by) if superseded_by else None,
        "general": general if isinstance(general, str) and general.strip() else None,
        "short": meta.get("short") if valid_short(meta.get("short")) else None,
        "short_by": "model" if meta.get("short_by") == "model" else None,
        "triage": triage,
        "triage_reason": reason if triage == "pending" and valid_triage_reason(reason) else None,
        "topic": meta.get("topic") if valid_topic(meta.get("topic")) else None,
    }


def _list_fields(meta: dict) -> dict:
    """The optional list fields; a bad value reads as absent."""
    distinct = meta.get("distinct_from")
    raw_log = meta.get("log")
    raw_versions = meta.get("versions")
    return {
        "distinct_from": [str(h) for h in distinct] if isinstance(distinct, list) else [],
        "log": [e for e in raw_log if isinstance(e, str) and case(e)]
        if isinstance(raw_log, list)
        else [],
        "versions": sorted((e for e in raw_versions if _version(e)), key=lambda e: e[:10])
        if isinstance(raw_versions, list)
        else [],
    }


def _optional_fields(meta: dict) -> dict:
    return {
        **{key: _lenient_date(meta, key) for key in _LENIENT_DATES},
        **_text_fields(meta),
        **_list_fields(meta),
        "promote": _promote_of(meta),
        "load": _load_of(meta),
        "origin": _choice(meta, "origin", ORIGINS),
        "reach": _choice(meta, "reach", REACHES),
        "weight": _choice(meta, "weight", WEIGHTS),
    }


def _parse_text(base: Memory, text: str) -> Memory:
    meta, body = _split(text)
    required = _required_fields(meta)
    optional = _optional_fields(meta)
    return replace(
        base,
        **required,
        **optional,
        created=_date(meta.get("created"), "created"),
        valid_until=_date(meta.get("valid_until"), "valid_until"),
        body=body,
    )


def _parse(path: Path, scope: str) -> Memory:
    base = Memory(scope, path, path.stem, "lesson", "", None, 1, "active", None, None, [], "", None)
    try:
        return _parse_text(base, path.read_text(encoding="utf-8"))
    except Exception as e:  # one broken file must not break the rest
        logger.debug("cannot parse %s", path, exc_info=True)
        name = (
            "ValueError" if isinstance(e, FieldTypeError) else type(e).__name__
        )  # the error text predates the subclass
        return replace(base, error=f"{name}: {e}".splitlines()[0])


def load_memories(folder: Path | None, scope: str) -> list[Memory]:
    try:
        if folder is None or not folder.is_dir():
            return []
        if (
            scope == "project" and folder.is_symlink()
        ):  # a cloned repository's planted link; global folders may be synced links
            return []
        return [
            _parse(p, scope)
            for p in sorted(folder.glob("*.md"), key=lambda p: p.stem)
            if p.is_file() and not (scope == "project" and p.is_symlink())
        ]
    except OSError:
        return []


def slug_of(claim: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", claim).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", ascii_text.lower())[:8]
    slug = "-".join(words)[:60].strip("-")
    return slug or "memory"


# The frontmatter keys of a memory in file order; one is written when its value is set, `observed` and `status` always.
_RENDER_ORDER = (
    "created",
    "observed",
    "status",
    "context",
    "valid_until",
    "sources",
    "origin",
    "reach",
    "weight",
    "owner_confirmed",
    "triage",
    "triage_reason",
    "released",
    "general",
    "short",
    "short_by",
    "topic",
    "load",
    "log",
    "versions",
    "reviewed",
    "reworded",
    "reword_failed",
)
_RENDER_ALWAYS = ("observed", "status")


def _frontmatter_value(value: object) -> object:
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, list):
        return list(value)
    return value


def _render(m: Memory, extra: Mapping[str, str] | None = None) -> str:
    meta: dict = {"kind": m.kind, "claim": m.claim}
    for key in _RENDER_ORDER:
        value = getattr(m, key)
        if value or key in _RENDER_ALWAYS:
            meta[key] = _frontmatter_value(value)
    meta.update(extra or {})
    head = yaml.safe_dump(
        meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6
    )
    return f"---\n{head}---\n{m.body}"


class WriteOptions(TypedDict, total=False):
    """The keyword options of `write_memory`; an omitted one is None, except `sources` (empty)."""

    kind: Required[str]
    claim: Required[str]
    body: Required[str]
    today: Required[datetime.date]
    context: str | None
    valid_until: datetime.date | None
    sources: Sequence[str]
    origin: str | None
    reach: str | None
    weight: str | None
    short: str | None
    topic: str | None
    short_by: str | None
    outcome: str | None
    on: datetime.date | None


def _check_choice(label: str, value: str | None, allowed: Sequence[str]) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"unknown {label} {value!r}")


def _check_write(options: WriteOptions) -> None:
    """The first invalid option of a `write_memory` call raises ValueError."""
    kind, sources = options["kind"], options.get("sources", ())
    _check_choice("outcome", options.get("outcome"), OUTCOMES)
    short, topic = options.get("short"), options.get("topic")
    if short is not None and not valid_short(short):
        raise ValueError(f"the short form must be one line of at most {SHORT_LIMIT} characters")
    if topic is not None and not valid_topic(topic):
        raise ValueError(
            f"the topic must be one or two lowercase words of at most {TOPIC_LIMIT} characters"
        )
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    _check_choice("origin", options.get("origin"), ORIGINS)
    _check_choice("reach", options.get("reach"), REACHES)
    _check_choice("weight", options.get("weight"), WEIGHTS)
    if not options["claim"].strip():
        raise ValueError("claim is empty")
    if kind in {"finding", "document"} and not sources:
        raise ValueError(f"a {kind} needs at least one source")


_DEFAULT_DAYS = {"finding": 90, "state": 30}  # how long a kind lasts when the caller names no end


def _standing_fields(
    template: Memory, today: datetime.date, valid_until: datetime.date | None
) -> tuple[datetime.date | None, datetime.date | None, str | None]:
    """(valid_until, released, triage) of a new memory: a transcript memory's standing decides them, before the
    per-kind defaults."""
    if template.origin == "transcript":
        changes = standing_changes(None, template, today)
        return (
            changes["valid_until"] if valid_until is None else valid_until,
            changes.get("released"),
            changes.get("triage"),
        )
    days = _DEFAULT_DAYS.get(template.kind)
    if valid_until is None and days is not None:
        valid_until = today + datetime.timedelta(days=days)
    return valid_until, None, None


def _write_new(folder: Path, template: Memory) -> Memory:
    """Write the memory to a new file named after its claim, -2, -3 ... when the name is taken."""
    base = slug_of(template.claim)
    handle, n = base, 1
    while True:
        m = replace(template, handle=handle, path=folder / f"{handle}.md")
        try:
            with m.path.open("x", encoding="utf-8") as f:  # exclusive: never overwrite
                f.write(_render(m))
            return m
        except FileExistsError:
            n += 1
            handle = f"{base}-{n}"


def write_memory(folder: Path, scope: str, **options: Unpack[WriteOptions]) -> Memory:
    _check_write(options)
    kind, today, short = options["kind"], options["today"], options.get("short")
    claim, body = options["claim"].strip(), options["body"]
    sources = normalized_sources(options.get("sources", ()))
    origin, weight = options.get("origin"), options.get("weight")
    draft = Memory(
        scope,
        folder,
        "",
        kind,
        claim,
        today,
        1,
        "active",
        None,
        None,
        sources,
        "",
        None,
        origin=origin,
        weight=weight,
    )
    valid_until, released, triage = _standing_fields(draft, today, options.get("valid_until"))
    if scope == "project":
        safe_io.refuse_symlink_chain(folder, folder)
    folder.mkdir(parents=True, exist_ok=True)
    outcome = options.get("outcome")
    log = (
        [
            case_entry(options.get("on") or today, key, outcome)
            for key in dict.fromkeys(filter(None, map(session_key, sources)))
        ]
        if outcome
        else []
    )
    template = Memory(
        scope,
        folder,
        "",
        kind,
        claim,
        today,
        1,
        "active",
        options.get("context"),
        valid_until,
        list(sources),
        body if body.endswith("\n") or not body else body + "\n",
        None,
        origin=origin,
        reach=options.get("reach"),
        weight=weight,
        triage=triage,
        released=released,
        short=short,
        short_by=options.get("short_by") if short else None,
        topic=options.get("topic"),
        log=log,
        versions=[version_entry(today, short)] if short else [],
    )
    return _write_new(folder, template)


def is_live(memory: Memory, today: datetime.date) -> bool:
    return (
        memory.error is None
        and memory.status == "active"
        and (memory.valid_until is None or memory.valid_until >= today)
    )


def similarity(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def update(memory: Memory, today: datetime.date, **changes) -> Memory:
    """Rewrite the memory's file with the given frontmatter keys changed or added; a value of None removes the key.

    The reserved name `body` replaces the body instead. Keys this module does not know and the rest of the body
    survive; the file is replaced through a temporary one. `today` is the date of the action: callers put it into
    the keys they change, as dates are written as ISO strings. Returns the memory read back from the file."""
    meta, body = _split(memory.path.read_text(encoding="utf-8"))
    body = changes.pop("body", body)
    new_short = changes.get("short")
    if new_short is not None:
        current = _parse(memory.path, memory.scope)
        if new_short != current.short:
            kept = [(on, text) for on, text in version_list(current) if on != today]
            meta["versions"] = [
                version_entry(on, text)
                for on, text in sorted([*kept, (today, new_short)], key=lambda v: v[0])
            ]
    for key, value in changes.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value.isoformat() if isinstance(value, datetime.date) else value
    head = yaml.safe_dump(
        meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6
    )
    safe_io.replace_file(memory.path, f"---\n{head}---\n{body}".encode())
    return _parse(memory.path, memory.scope)


def observe(memory: Memory, today: datetime.date) -> Memory:
    return update(memory, today, observed=memory.observed + 1, last_observed=today)


MAX_SESSION_ID = 200  # characters of the id after "session "; longer is not a session
_PROJECT_PART = re.compile(r"(session \S.*?) project (\S+)")
_PROJECT_KEY = re.compile(rf"[0-9a-f]{{{PROJECT_KEY_LEN}}}")


def project_key(project: Path) -> str:
    """The first 12 hex characters of the SHA-1 of the resolved path: counts projects without naming them."""
    return hashlib.sha1(str(project.resolve()).encode("utf-8")).hexdigest()[:PROJECT_KEY_LEN]


def under_temp(path: Path) -> bool:
    """True when `path` is under a temporary folder: a trial copy of a project there is not a second project.
    Always false when MEM_COUNT_TEMP_PROJECTS is "1" (the tests, which run under a temporary folder)."""
    if os.environ.get("MEM_COUNT_TEMP_PROJECTS") == "1":
        return False
    resolved = path.resolve()
    roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
        Path("/var/tmp").resolve(),
    }
    return any(resolved == r or r in resolved.parents for r in roots)


def sighting(source: str) -> tuple[str, str | None] | None:
    """("session <id>", project key or None) of a sighting entry, normalized (stripped, whitespace collapsed,
    lower-cased), else None. A text after "project" that is not a 12-hex key makes the entry no sighting."""
    text = " ".join(source.split()).lower()
    if not text.startswith(SESSION_PREFIX) or len(text) == len(SESSION_PREFIX):
        return None
    key = None
    found = _PROJECT_PART.fullmatch(text)
    if found:
        text, key = found.group(1), found.group(2)
        if not _PROJECT_KEY.fullmatch(key):
            return None
    elif "project" in text[len(SESSION_PREFIX) :].split():
        return None  # "session a project" or "... project <key> extra": a keyed entry gone wrong, not a session id
    return (text, key) if len(text) - len(SESSION_PREFIX) <= MAX_SESSION_ID else None


def sighting_entry(session: str, key: str | None) -> str:
    return f"{session} project {key}" if key else session


def session_key(source: str) -> str | None:
    """The normalized "session <id>" part of a session source (the project, if any, is left out), else None:
    two spellings of one session are one key."""
    found = sighting(source)
    return found[0] if found else None


def _normalized_source(
    source: str, found: tuple[str, str | None] | None, first_key: dict[str, str]
) -> str | None:
    """`source` normalized, or None when it repeats a session that another entry names with a project."""
    if found is None:
        return source
    if found[0] in first_key and found[1] != first_key[found[0]]:
        return None
    return sighting_entry(*found)


def normalized_sources(sources: Iterable[str]) -> list[str]:
    """Session entries in their normalized form, one per session (the first one with a project when several
    occur: one session is one sighting, so it cannot count as two projects); other sources unchanged; order kept."""
    parsed = [(s, sighting(s)) for s in sources]
    first_key: dict[str, str] = {}
    for _, f in parsed:
        if f and f[1]:
            first_key.setdefault(f[0], f[1])
    out = (_normalized_source(s, f, first_key) for s, f in parsed)
    return list(dict.fromkeys(e for e in out if e is not None))


def sessions(memory: Memory) -> list[str]:
    """The distinct sessions of `sources` as normalized keys, in order."""
    return list(dict.fromkeys(k for k in map(session_key, memory.sources) if k))


def projects(memory: Memory) -> list[str]:
    """The distinct project keys of the sighting entries, in order: one per session, its first keyed entry, so a
    file that holds one session under two keys still counts one project."""
    first: dict[str, str] = {}
    for found in map(sighting, memory.sources):
        if found and found[1]:
            first.setdefault(found[0], found[1])
    return list(dict.fromkeys(first.values()))


def tracked_memories(project: Path) -> frozenset[str] | None:
    """Handles of the `.memory/*.md` files git tracks in `project`; None when `.memory` holds its own `.git` or is
    listed as a gitlink (every handle counts as tracked); empty when git is missing, fails or times out."""
    folder = project / PROJECT_DIR
    try:
        if (folder / ".git").exists():
            return None
        run = subprocess.run(
            [
                "git",
                "-C",
                str(project),
                "ls-files",
                "-z",
                "--recurse-submodules",
                "--",
                f"{PROJECT_DIR}/",
            ],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    if run.returncode != 0:
        return frozenset()
    names = [Path(n.decode("utf-8", "replace")) for n in run.stdout.split(b"\0") if n]
    if any(n.as_posix() == PROJECT_DIR for n in names):  # a gitlink lists as the folder itself
        return None
    return frozenset(
        n.stem for n in names if n.suffix == ".md" and n.parent.as_posix() == PROJECT_DIR
    )


def mark_repository(memories: Sequence[Memory], tracked: frozenset[str] | None) -> list[Memory]:
    """Copies of the tracked memories with `from_repository` set and the owner confirmation in the file dropped: a
    repository's author is not the reader. Sightings still count. `tracked` None marks them all."""
    return [
        replace(m, from_repository=True, owner_confirmed=None)
        if tracked is None or m.handle in tracked
        else m
        for m in memories
    ]


def standing(memory: Memory) -> str | None:
    """None unless the memory comes from a transcript; then "established" once the owner confirmed it or enough
    distinct sessions show it (by its weight), else "unconfirmed". A global record also needs two projects (C31).
    Never computed from `observed`: a plain confirm, a merge and a curation pass raise it without being
    independent evidence."""
    if memory.origin != "transcript":
        return None
    if memory.owner_confirmed:
        return "established"
    weight = memory.weight or "medium"
    if memory.scope == "global":
        enough = len(projects(memory)) >= GLOBAL_MIN_PROJECTS and (
            weight != "strong" or len(sessions(memory)) >= SIGHTINGS_NEEDED["strong"]
        )
    else:
        enough = len(sessions(memory)) >= SIGHTINGS_NEEDED[weight]
    return "established" if enough else "unconfirmed"


def quarantined(memory: Memory) -> bool:
    return memory.scope == "global" and standing(memory) == "unconfirmed"


def standing_changes(before: Memory | None, after: Memory, today: datetime.date) -> dict:
    """The frontmatter changes that follow from the standing of `after` (a transcript record): its end date, and
    the release of a global record the first time it is established, awaiting triage unless the owner confirmed it
    (that confirmation is the triage). `before` is None for a record being written."""
    established = standing(after) == "established"
    changes: dict = {
        "valid_until": None if established else today + datetime.timedelta(days=UNCONFIRMED_DAYS)
    }
    if after.scope == "global" and established:
        if before is None or before.released is None:
            changes["released"] = today
            if not after.owner_confirmed and (after.weight or "medium") == "strong":
                changes["triage"] = "pending"
        if after.owner_confirmed:
            changes["triage"] = None
    return changes


def counted(memory: Memory, source: str) -> bool:
    """True when the sighting entry adds nothing: its session is counted and either it names no project or the
    session already carries one."""
    found = sighting(source)
    if found is None or found[0] not in sessions(memory):
        return False
    return not found[1] or any(
        f and f[0] == found[0] and f[1] for f in map(sighting, memory.sources)
    )


class Case(NamedTuple):
    on: datetime.date
    session: str  # the normalized "session <id>"
    outcome: str


_CASE = re.compile(r"(\d{4}-\d{2}-\d{2}) (session \S.*) (" + "|".join(OUTCOMES) + ")")


def case(entry: str) -> Case | None:
    """The case of a log entry "<YYYY-MM-DD> session <id> <outcome>", else None."""
    found = _CASE.fullmatch(entry) if isinstance(entry, str) else None
    if not found:
        return None
    try:
        on = datetime.date.fromisoformat(found.group(1))
    except ValueError:
        return None
    if session_key(found.group(2)) != found.group(2):
        return None
    return Case(on, found.group(2), found.group(3))


def case_entry(on: datetime.date, session: str, outcome: str) -> str:
    return f"{on.isoformat()} {session} {outcome}"


def cases(memory: Memory) -> list[Case]:
    """The valid cases of the log by date; entries of one day keep their file order."""
    return sorted((c for c in map(case, memory.log) if c), key=lambda c: c.on)


def _version(entry) -> tuple[datetime.date, str] | None:
    """(date, short form) of a version entry "<YYYY-MM-DD> <short form>", else None."""
    if not isinstance(entry, str):
        return None
    day, _, text = entry.partition(" ")
    try:
        on = datetime.date.fromisoformat(day)
    except ValueError:
        return None
    return (on, text) if len(day) == SHORT_DATE_LEN and valid_short(text) else None


def version_entry(on: datetime.date, short: str) -> str:
    return f"{on.isoformat()} {short}"


def version_list(memory: Memory) -> list[tuple[datetime.date, str]]:
    """The versions of the short form by date; a lesson written before versions existed reads as one version dated
    `released`, or `created`."""
    found = [v for v in map(_version, memory.versions) if v]
    if found:
        return found
    on = memory.released or memory.created
    return [(on, memory.short)] if memory.short and on else []


def merged_versions(keep: Memory, drop: Memory, today: datetime.date) -> list[str]:
    """The versions of a merged lesson: both records' versions (implicit ones included), one per day with the kept
    record's text winning, and the kept record's short form last, because that is the text that loads."""
    by_day: dict[datetime.date, str] = {}
    for on, text in [*version_list(keep), *version_list(drop)]:
        by_day.setdefault(on, text)  # keep's entries come first, so they win
    result = sorted(by_day.items())
    if keep.short and (not result or result[-1][1] != keep.short):
        result = [v for v in result if v[0] != today] + [(today, keep.short)]
    return [version_entry(on, text) for on, text in result]


def merged_log(keep: Memory, drop: Memory) -> list[str]:
    """The log of a merged lesson by date: one entry per (session, outcome), the earlier day kept, and a `seen` entry
    only for a session with no other entry. An entry that is not a case is kept once, as it is."""
    entries = list(dict.fromkeys([*keep.log, *drop.log]))
    earliest: dict[tuple[str, str], tuple[datetime.date, str]] = {}
    for e in entries:
        c = case(e)
        if c is not None:
            held = earliest.get((c.session, c.outcome))
            if held is None or c.on < held[0]:
                earliest[c.session, c.outcome] = (c.on, e)
    best = {key: e for key, (_, e) in earliest.items()}
    cased = {session for session, outcome in best if outcome != "seen"}
    chosen = {
        e for (session, outcome), e in best.items() if outcome != "seen" or session not in cased
    }
    result = [e for e in entries if case(e) is None or e in chosen]
    result.sort(key=lambda e: e[:10])
    return result


class Tally(NamedTuple):
    number: int
    since: datetime.date
    text: str
    worked: int
    failed: int

    @property
    def balance(self) -> int:
        return self.worked - self.failed


FAILED_TO_LIST = 2


def tallies(memory: Memory) -> list[Tally]:
    """One tally per version; a case counts for the last version dated earlier than the case."""
    versions = version_list(memory)
    counts = [[0, 0] for _ in versions]
    for c in cases(memory):
        if c.outcome == "seen":
            continue
        owners = [i for i, (on, _) in enumerate(versions) if on < c.on]
        if owners:
            counts[owners[-1]][c.outcome == "failed"] += 1
    return [
        Tally(i + 1, on, text, w, f)
        for i, ((on, text), (w, f)) in enumerate(zip(versions, counts, strict=False))
    ]


def reword_note(memory: Memory) -> str:
    """What the automatic rewording did to this lesson, for the owner's queue; "" when it did nothing that still applies."""
    versions = version_list(memory)
    last = versions[-1][0] if versions else None
    if memory.reworded is not None:
        if memory.reworded == last:
            return f"the automatic rewording of {memory.reworded.isoformat()} got worse too"
        return f"an automatic rewording was made on {memory.reworded.isoformat()}; this wording is the owner's"
    if memory.reword_failed is not None and memory.reword_failed == last:
        return "an automatic rewording could not be written"
    return ""


def got_worse(memory: Memory) -> bool:
    """The current version failed at least FAILED_TO_LIST times since `reviewed`, and failed more than it worked or
    stands below the version before it."""
    found = tallies(memory)
    if not found:
        return False
    cur, prev = found[-1], found[-2] if len(found) > 1 else None
    since = memory.reviewed
    recent = sum(
        1
        for c in cases(memory)
        if c.outcome == "failed" and (since is None or c.on > since) and c.on > cur.since
    )
    return recent >= FAILED_TO_LIST and (
        cur.failed > cur.worked or (prev is not None and cur.balance < prev.balance)
    )


def mark_words(memory: Memory) -> str:
    found = tallies(memory)
    if not found or not found[-1].failed:
        return ""
    cur = found[-1]
    return f"version {cur.number}: worked {cur.worked}, failed {cur.failed}"


def has_case(memory: Memory, key: str, outcome: str) -> bool:
    """True when a case of session `key` with `outcome` adds nothing: the session has an entry with that outcome,
    or the outcome is `seen` and the session has any entry."""
    mine = [c.outcome for c in cases(memory) if c.session == key]
    return outcome in mine or (outcome == "seen" and bool(mine))


def _log_with(memory: Memory, key: str, on: datetime.date, outcome: str) -> list[str] | None:
    """The log after adding the case of session `key`, or None when it adds nothing (see `has_case`)."""
    if has_case(memory, key, outcome):
        return None
    return [*memory.log, case_entry(on, key, outcome)]


def add_case(
    memory: Memory, session: str, on: datetime.date, outcome: str, today: datetime.date
) -> tuple[Memory, bool]:
    """Add the case of `session` (any spelling of a session source) to the log; False and no write when it adds
    nothing. Not a session or an unknown outcome: ValueError."""
    key = session_key(session)
    if key is None:
        raise ValueError(f"{session!r} is not a session source: write it as 'session <id>'")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    log = _log_with(memory, key, on, outcome)
    if log is None:
        return memory, False
    return update(memory, today, log=log), True


class SightingOptions(TypedDict, total=False):
    """The keyword options of `add_sighting`."""

    outcome: str  # "seen"
    on: datetime.date | None  # None: today


def _checked_sighting(session: str, outcome: str) -> tuple[str, str | None]:
    """(key, project) of the session entry; ValueError when it is no session source or the outcome is unknown."""
    found = sighting(session)
    if found is None:
        raise ValueError(f"{session!r} is not a session source: write it as 'session <id>'")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    return found


def _noted_body(memory: Memory, note: str | None) -> dict:
    """The `body` change that appends `note`, empty without a note."""
    if not (note and note.strip()):
        return {}
    head = memory.body if memory.body.endswith("\n") or not memory.body else memory.body + "\n"
    return {"body": f"{head}{' '.join(note.split())}\n"}


def add_sighting(
    memory: Memory,
    session: str,
    today: datetime.date,
    note: str | None = None,
    **options: Unpack[SightingOptions],
) -> tuple[Memory, bool]:
    """Record that another session shows the memory: `session` is a full source entry ("session <id>", with
    " project <key>" when known).

    Not a session entry: ValueError. Already counted (under any spelling, with its project when given): the memory
    unchanged and False, with no write. A session counted without a project that now comes with one gains the
    project (True, `observed` unchanged). Else the normalized entry is added, `observed` raised as `observe`
    does and the note appended to the body; a transcript memory also gets `standing_changes`.

    The case (`outcome`, dated `on` or today) goes to the log in the same write, unless the log already holds it;
    a counted session whose case is new still writes, and the flag stays False."""
    outcome = options.get("outcome", "seen")
    key, project = _checked_sighting(session, outcome)
    log = _log_with(memory, key, options.get("on") or today, outcome)
    changes: dict = {} if log is None else {"log": log}
    if key in sessions(memory):
        if counted(memory, session):
            return (memory, False) if log is None else (update(memory, today, **changes), False)
        sources = normalized_sources([
            sighting_entry(key, project) if (f := sighting(s)) and f[0] == key else s
            for s in memory.sources
        ])
    else:
        sources = [*memory.sources, sighting_entry(key, project)]
        changes.update({"observed": memory.observed + 1, "last_observed": today})
        changes.update(_noted_body(memory, note))
    changes["sources"] = sources
    if memory.origin == "transcript":
        changes.update(standing_changes(memory, replace(memory, sources=sources), today))
    return update(memory, today, **changes), True


@dataclass
class Budget:
    """Claim comparisons a caller lets pair searches spend, shared by passing one object to several searches.

    `left` counts down by one per comparison. `exhausted` turns True when a search needed a comparison and `left`
    was 0: `left == 0` alone does not say it, because a budget spent to the last comparison compared everything."""

    left: int
    exhausted: bool = False

    def spend(self) -> bool:
        if self.left <= 0:
            self.exhausted = True
            return False
        self.left -= 1
        return True


def _terms(tokens: Iterable[str]) -> frozenset[str]:
    """The distinct terms `containment` counts: no all-digit token, no stop word."""
    return frozenset(t for t in tokens if not t.isdigit()) - STOPWORDS


def _containment_of_terms(terms: frozenset[str], other_tokens: Collection[str]) -> float:
    """`containment` over precomputed terms."""
    if len(terms) < MIN_TERMS:
        return 0.0
    return len(terms.intersection(other_tokens)) / len(terms)


def _among_order(
    live: Sequence[Memory], index: Mapping[str, int], among: Sequence[str]
) -> Iterator[tuple[int, int]]:
    """Index pairs with at least one `among` memory, each pair once, in the order of `among`."""
    seen: set[str] = set()
    for h in among:
        i = index.get(h)
        if i is None or h in seen:
            continue
        seen.add(h)
        for j in range(len(live)):
            if j != i and live[j].handle not in seen:
                yield min(i, j), max(i, j)


def pairs(
    memories: Sequence[Memory],
    today: datetime.date,
    *,
    tokenize: Callable[[str], list[str]],
    among: Sequence[str] | None = None,
    budget: Budget | None = None,
) -> list[tuple[Memory, Memory, float]]:
    """Pairs of live memories whose claims contain each other with at least STRONG, in either direction.

    A claim and its negation score as high as a near-copy: a pair means "same or opposite", never "duplicate".

    With `among` (handles, in the order to search) only pairs with at least one of them are compared, each pair
    once, searching `among` in its order. With `budget` each comparison spends 1 and the search stops when it is
    spent, returning what it found; the caller reads `budget.exhausted` (a comparison was needed with none left)."""
    live = sorted((m for m in memories if is_live(m, today)), key=lambda m: m.handle)
    index = {m.handle: i for i, m in enumerate(live)}
    tokens = [set(tokenize(m.claim)) for m in live]
    terms = [_terms(t) for t in tokens]
    if among is None:
        order = ((i, j) for i in range(len(live)) for j in range(i + 1, len(live)))
    else:
        order = _among_order(live, index, among)
    found = []
    for i, j in order:
        a, b = live[i], live[j]
        if b.handle in a.distinct_from or a.handle in b.distinct_from:
            continue
        if budget is not None and not budget.spend():
            break
        score = max(
            _containment_of_terms(terms[i], tokens[j]), _containment_of_terms(terms[j], tokens[i])
        )
        if score >= STRONG:
            found.append((a, b, score))
    found.sort(key=lambda t: (-t[2], t[0].handle, t[1].handle))
    return found


def _claim_terms(
    claim: str, tokenize: Callable[[str], list[str]]
) -> tuple[set[str], frozenset[str]]:
    tokens = set(tokenize(claim))
    return tokens, _terms(tokens)


def _may_refute(live: Memory, dead: Memory) -> bool:
    """Whether `live` could refute-contradict `dead`: not recorded as distinct, and written after the refutation."""
    if dead.handle in live.distinct_from or live.handle in dead.distinct_from:
        return False
    since = dead.refuted or dead.created
    return live.created is not None and (since is None or live.created > since)


def _refuted_scores(
    live: Memory,
    dead: Sequence[Memory],
    tokenize: Callable[[str], list[str]],
    dead_seen: dict[str, tuple[set[str], frozenset[str]]],
    budget: Budget | None,
) -> tuple[list[tuple[Memory, Memory, float]], bool]:
    """The pairs of `live` with a refuted memory that reach STRONG, and whether the budget ran out."""
    found = []
    mine: tuple[set[str], frozenset[str]] | None = None
    for r in dead:
        if not _may_refute(live, r):
            continue
        if budget is not None and not budget.spend():
            return found, True
        mine = mine or _claim_terms(live.claim, tokenize)
        if r.handle not in dead_seen:
            dead_seen[r.handle] = _claim_terms(r.claim, tokenize)
        (ta, terms_a), (tr, terms_r) = mine, dead_seen[r.handle]
        score = max(_containment_of_terms(terms_a, tr), _containment_of_terms(terms_r, ta))
        if score >= STRONG:
            found.append((live, r, score))
    return found, False


def refuted_pairs(
    memories: Sequence[Memory],
    today: datetime.date,
    *,
    tokenize: Callable[[str], list[str]],
    among: Sequence[str] | None = None,
    budget: Budget | None = None,
) -> list[tuple[Memory, Memory, float]]:
    """(live, refuted, score): a live memory whose claim and a refuted one's contain each other with at least STRONG,
    unless the two are recorded as distinct or the live one is not strictly newer than the refutation
    (its `refuted` date, else the refuted memory's `created`).

    `among` and `budget` work as in `pairs`; `among` restricts the live memories, in its order."""
    live = sorted((m for m in memories if is_live(m, today)), key=lambda m: m.handle)
    if among is not None:
        by_handle = {m.handle: m for m in live}
        live = [by_handle[h] for h in dict.fromkeys(among) if h in by_handle]
    dead = sorted(
        (m for m in memories if m.error is None and m.status == "refuted"), key=lambda m: m.handle
    )
    dead_seen: dict[str, tuple[set[str], frozenset[str]]] = {}  # tokenized when first compared
    found: list[tuple[Memory, Memory, float]] = []
    for a in live:
        scored, spent = _refuted_scores(a, dead, tokenize, dead_seen, budget)
        found.extend(scored)
        if spent:
            break
    found.sort(key=lambda t: (-t[2], t[0].handle, t[1].handle))
    return found


_WORD = re.compile(r"[a-z0-9]+(?:[.'\u2019][a-z0-9]+)*")
_NEGATIONS = frozenset({"not", "no", "never", "cannot", "without"})


def _claim_words(claim: str) -> set[str]:
    return set(_WORD.findall(claim.casefold()))


def differing_words(a: str, b: str) -> list[str]:
    """The words that occur in only one of the two claims, sorted; stop words are left out except negations,
    digits stay. Empty when nothing is left."""
    return sorted(
        w for w in _claim_words(a) ^ _claim_words(b) if w in _NEGATIONS or w not in STOPWORDS
    )


# Pairs of words that make two claims opposites; either member of a pair may be the one in each claim.
OPPOSITES = [
    "works/fails",
    "work/fail",
    "passes/fails",
    "pass/fail",
    "enable/disable",
    "enabled/disabled",
    "allow/deny",
    "allowed/denied",
    "before/after",
    "always/never",
    "on/off",
    "safe/unsafe",
    "increase/decrease",
    "with/without",
    "can/cannot",
    "must/may",
    "add/remove",
    "start/stop",
    "true/false",
    "required/optional",
    "sync/async",
    "up/down",
]


def _partners() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for pair in OPPOSITES:
        x, y = pair.split("/")
        found.setdefault(x, set()).add(y)
        found.setdefault(y, set()).add(x)
    return found


_PARTNERS = _partners()


def flagged_words(a: str, b: str) -> list[str]:
    """The words that differ between two claims and may mean opposites or different versions: any token with a
    digit, a negation, and a word of OPPOSITES whose partner is among the other claim's differing words."""
    wa, wb = _claim_words(a), _claim_words(b)
    only_a, only_b = wa - wb, wb - wa
    flagged = set()
    for mine, other in ((only_a, only_b), (only_b, only_a)):
        for w in mine:
            if (
                w in _NEGATIONS
                or w.endswith(("n't", "n\u2019t"))
                or any(c.isdigit() for c in w)
                or _PARTNERS.get(w, set()) & other
            ):
                flagged.add(w)
    return sorted(flagged)


class Logged(Protocol):
    """What the curation log needs of a record: a file and a handle (a memory or a synthesis)."""

    path: Path
    handle: str


def log_before(memory: Logged, action: str) -> None:
    """Append the file's whole current text to the `.curation-log` beside it, before an action changes the file."""
    entry = {
        "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": action,
        "handle": memory.handle,
        "before": memory.path.read_bytes().decode("utf-8"),
    }
    safe_io.append_text(
        memory.path.parent / CURATION_LOG, json.dumps(entry, ensure_ascii=False) + "\n"
    )


def _log_lines(memory: Logged) -> list[str] | None:
    try:
        # split on "\n" only: splitlines() would also cut at U+0085 or U+2028 inside a JSON string
        return (memory.path.parent / CURATION_LOG).read_text(encoding="utf-8").split("\n")
    except OSError:
        return None


def _parsed_log(lines: Sequence[str], handle: str) -> tuple[list[dict | None], int]:
    """The entries of the memory's handle, None for every other line, and the count of unreadable lines."""
    parsed: list[dict | None] = []
    skipped = 0
    for line in lines:
        entry = None
        if line.strip():
            try:
                entry = json.loads(line)
            except ValueError:
                skipped += 1
        parsed.append(entry if isinstance(entry, dict) and entry.get("handle") == handle else None)
    return parsed, skipped


def last_log_entry(memory: Logged) -> dict | None:
    """The newest `.curation-log` entry for the memory's handle that no restore has used yet, or None.

    Undo is a stack over an append-only log: a restore appends a marker naming the entry (by line number) it used.
    The entry returned gains `line` (its number) and `skipped` (the unreadable lines of the log)."""
    lines = _log_lines(memory)
    if lines is None:
        return None
    parsed, skipped = _parsed_log(lines, memory.handle)
    undone = {
        e["undone"]
        for e in parsed
        if e and e.get("action") == "restore" and isinstance(e.get("undone"), int)
    }
    for number in range(len(parsed) - 1, -1, -1):
        entry = parsed[number]
        if entry and isinstance(entry.get("before"), str) and number not in undone:
            return {**entry, "line": number, "skipped": skipped}
    return None


def restore(memory: Logged, entry: dict) -> None:
    """Put back the text a log entry holds, byte for byte, through a temporary file, then log that it was used."""
    safe_io.replace_file(memory.path, entry["before"].encode("utf-8"))
    marker = {
        "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": "restore",
        "handle": memory.handle,
        "undone": entry["line"],
    }
    safe_io.append_text(
        memory.path.parent / CURATION_LOG, json.dumps(marker, ensure_ascii=False) + "\n"
    )


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
    base = config.config_dir(env)
    return base / "forbidden-terms" if base is not None else None


def default_store(env: Mapping[str, str]) -> Path | None:
    """The store used when none is named: the path only, `mem init` creates it (see `config.default_store`)."""
    return config.default_store_path(env)


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


STOPWORDS = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "nor",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "from",
    "by",
    "with",
    "about",
    "as",
    "into",
    "over",
    "under",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "am",
    "do",
    "does",
    "did",
    "has",
    "have",
    "had",
    "will",
    "would",
    "can",
    "could",
    "should",
    "may",
    "might",
    "must",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
    "my",
    "your",
    "his",
    "its",
    "our",
    "their",
    "this",
    "that",
    "these",
    "those",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "when",
    "where",
    "why",
    "how",
    "not",
    "no",
    "if",
    "then",
    "than",
    "so",
    "there",
    "here",
])


class MatchOptions(TypedDict, total=False):
    """The keyword options of `match_memories`."""

    tokenize: Required[Callable[[str], list[str]]]
    limit: int  # 3
    include_dead: bool  # False


def match_memories(
    memories: Sequence[Memory],
    query_tokens: Sequence[str],
    today: datetime.date,
    **options: Unpack[MatchOptions],
) -> list[Memory]:
    """Memories holding at least half (rounded up) of the query's non-stop-word terms, best first."""
    tokenize, limit = options["tokenize"], options.get("limit", 3)
    include_dead = options.get("include_dead", False)
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
    scored.sort(
        key=lambda t: (
            -t[1],
            -t[2],
            -t[0].observed,
            -(t[0].created or datetime.date.min).toordinal(),
            t[0].handle,
        )
    )
    return [m for m, _, _ in scored[:limit]]


STRONG = 0.6  # chosen on evals/signal/set.json by the rule in the stage 6 plan
POSSIBLE = 0.5  # counted only, never named
MIN_TERMS = 2


_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase [a-z0-9]+ tokens after NFKD with combining marks removed (García -> garcia)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return _TOKEN.findall("".join(c for c in decomposed if not unicodedata.combining(c)).lower())


def containment(claim_tokens: Iterable[str], text_tokens: Collection[str]) -> float:
    """Share of the claim's distinct non-stop-word terms found in the text; 0.0 under MIN_TERMS terms.

    Measured from the claim's side: a brief has hundreds of words and a claim about ten. A token of only digits
    (a year, a count) is not a term: it matches unrelated briefs."""
    return _containment_of_terms(_terms(claim_tokens), set(text_tokens))


class Related(NamedTuple):
    handle: str
    kind: str  # "m" memory, "n" note
    score: float


def related_records(
    memories: Sequence[Memory],
    note_stems: Sequence[str],
    text: str,
    today: datetime.date,
    *,
    tokenize: Callable[[str], list[str]],
) -> tuple[list[Related], list[Related]]:
    """Records whose claim (a note: its file stem) is largely contained in the text: (strong, possible).

    A record whose handle occurs in the text as a whole token, with or without "m:", is left out: the text already
    names it."""
    text_tokens = set(tokenize(text))
    found: list[Related] = []
    candidates = [(m.handle, "m", m.claim) for m in memories if is_live(m, today)]
    candidates += [(stem, "n", stem.replace("-", " ")) for stem in note_stems]
    for handle, kind, claim in candidates:
        if re.search(rf"(?<![\w-]){re.escape(handle)}(?![\w-])", text):
            continue
        score = containment(tokenize(claim), text_tokens)
        if score >= POSSIBLE:
            found.append(Related(handle, kind, score))
    found.sort(key=lambda r: (-r.score, r.kind != "m", r.handle))
    return ([r for r in found if r.score >= STRONG], [r for r in found if r.score < STRONG])
