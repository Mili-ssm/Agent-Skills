"""Memory records: one Markdown file with YAML frontmatter per memory.

Imports nothing from mem.py (mem.py imports this module), so similarity and match_memories take tokens or a tokenizer.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Collection, Iterable, Mapping, NamedTuple, Protocol, Sequence

import yaml

KINDS = ("decision", "constraint", "pitfall", "lesson", "finding", "document", "state")
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
        try:
            last_observed = _date(meta.get("last_observed"), "last_observed")
        except ValueError:  # only curation reads it: a bad value must not hide the memory
            last_observed = None
        try:
            refuted = _date(meta.get("refuted"), "refuted")
        except ValueError:  # only curation reads it: a bad value must not hide the memory
            refuted = None
        distinct = meta.get("distinct_from")
        distinct = [str(h) for h in distinct] if isinstance(distinct, list) else []
        promote = "no" if meta.get("promote") in ("no", False) else "done" if meta.get("promote") == "done" else None  # YAML reads a bare no as False
        superseded_by = meta.get("superseded_by")
        superseded_by = str(superseded_by) if superseded_by else None
        return replace(base, kind=kind, superseded_by=superseded_by, last_observed=last_observed, refuted=refuted, distinct_from=distinct, promote=promote, claim=claim.strip(), created=_date(meta.get("created"), "created"),
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
    if kind == "state" and valid_until is None:
        valid_until = today + datetime.timedelta(days=30)
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


def update(memory: Memory, today: datetime.date, **changes) -> Memory:
    """Rewrite the memory's file with the given frontmatter keys changed or added; a value of None removes the key.

    The reserved name `body` replaces the body instead. Keys this module does not know and the rest of the body
    survive; the file is replaced through a temporary one. `today` is the date of the action: callers put it into
    the keys they change, as dates are written as ISO strings. Returns the memory read back from the file."""
    meta, body = _split(memory.path.read_text(encoding="utf-8"))
    body = changes.pop("body", body)
    for key, value in changes.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value.isoformat() if isinstance(value, datetime.date) else value
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10**6)
    tmp = memory.path.with_name(f".{memory.path.name}.tmp")
    tmp.write_text(f"---\n{head}---\n{body}", encoding="utf-8")
    os.replace(tmp, memory.path)
    return _parse(memory.path, memory.scope)


def observe(memory: Memory, today: datetime.date) -> Memory:
    return update(memory, today, observed=memory.observed + 1, last_observed=today)


def pairs(memories: Sequence[Memory], today: datetime.date, *,
          tokenize: Callable[[str], list[str]]) -> list[tuple[Memory, Memory, float]]:
    """Pairs of live memories whose claims contain each other with at least STRONG, in either direction.

    A claim and its negation score as high as a near-copy: a pair means "same or opposite", never "duplicate"."""
    live = sorted((m for m in memories if is_live(m, today)), key=lambda m: m.handle)
    tokens = [tokenize(m.claim) for m in live]
    found = []
    for i, a in enumerate(live):
        for j in range(i + 1, len(live)):
            score = max(containment(tokens[i], set(tokens[j])), containment(tokens[j], set(tokens[i])))
            if score >= STRONG and live[j].handle not in a.distinct_from and a.handle not in live[j].distinct_from:
                found.append((a, live[j], score))
    found.sort(key=lambda t: (-t[2], t[0].handle, t[1].handle))
    return found


def refuted_pairs(memories: Sequence[Memory], today: datetime.date, *,
                  tokenize: Callable[[str], list[str]]) -> list[tuple[Memory, Memory, float]]:
    """(live, refuted, score): a live memory whose claim and a refuted one's contain each other with at least STRONG,
    unless the two are recorded as distinct or the live one is not strictly newer than the refutation
    (its `refuted` date, else the refuted memory's `created`)."""
    live = sorted((m for m in memories if is_live(m, today)), key=lambda m: m.handle)
    dead = sorted((m for m in memories if m.error is None and m.status == "refuted"), key=lambda m: m.handle)
    found = []
    for a in live:
        ta = tokenize(a.claim)
        for r in dead:
            if r.handle in a.distinct_from or a.handle in r.distinct_from:
                continue
            since = r.refuted or r.created
            if a.created is None or (since is not None and a.created <= since):
                continue  # not written after the refutation
            tr = tokenize(r.claim)
            score = max(containment(ta, set(tr)), containment(tr, set(ta)))
            if score >= STRONG:
                found.append((a, r, score))
    found.sort(key=lambda t: (-t[2], t[0].handle, t[1].handle))
    return found


_WORD = re.compile(r"[a-z0-9]+(?:[.'\u2019][a-z0-9]+)*")
_NEGATIONS = frozenset({"not", "no", "never", "cannot", "without"})


def _claim_words(claim: str) -> set[str]:
    return set(_WORD.findall(claim.casefold()))


def differing_words(a: str, b: str) -> list[str]:
    """The words that occur in only one of the two claims, digits and negations included, sorted."""
    return sorted(_claim_words(a) ^ _claim_words(b))


# Pairs of words that make two claims opposites; either member of a pair may be the one in each claim.
OPPOSITES = ("works/fails work/fail passes/fails pass/fail enable/disable enabled/disabled allow/deny "
             "allowed/denied before/after always/never on/off safe/unsafe increase/decrease with/without "
             "can/cannot must/may add/remove start/stop true/false required/optional sync/async up/down").split()


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
            if (w in _NEGATIONS or w.endswith(("n't", "n\u2019t")) or any(c.isdigit() for c in w)
                    or _PARTNERS.get(w, set()) & other):
                flagged.add(w)
    return sorted(flagged)


class Logged(Protocol):
    """What the curation log needs of a record: a file and a handle (a memory or a synthesis)."""
    path: Path
    handle: str


def log_before(memory: Logged, action: str) -> None:
    """Append the file's whole current text to the `.curation-log` beside it, before an action changes the file."""
    entry = {"t": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "action": action,
             "handle": memory.handle, "before": memory.path.read_bytes().decode("utf-8")}
    with (memory.path.parent / CURATION_LOG).open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _log_lines(memory: Logged) -> list[str] | None:
    try:
        # split on "\n" only: splitlines() would also cut at U+0085 or U+2028 inside a JSON string
        return (memory.path.parent / CURATION_LOG).read_text(encoding="utf-8").split("\n")
    except OSError:
        return None


def last_log_entry(memory: Logged) -> dict | None:
    """The newest `.curation-log` entry for the memory's handle that no restore has used yet, or None.

    Undo is a stack over an append-only log: a restore appends a marker naming the entry (by line number) it used.
    The entry returned gains `line` (its number) and `skipped` (the unreadable lines of the log)."""
    lines = _log_lines(memory)
    if lines is None:
        return None
    parsed: list[dict | None] = []
    skipped = 0
    for line in lines:
        if not line.strip():
            parsed.append(None)
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            skipped += 1
            entry = None
        parsed.append(entry if isinstance(entry, dict) and entry.get("handle") == memory.handle else None)
    undone = {e["undone"] for e in parsed if e and e.get("action") == "restore" and isinstance(e.get("undone"), int)}
    for number in range(len(parsed) - 1, -1, -1):
        entry = parsed[number]
        if entry and isinstance(entry.get("before"), str) and number not in undone:
            return {**entry, "line": number, "skipped": skipped}
    return None


def restore(memory: Logged, entry: dict) -> None:
    """Put back the text a log entry holds, byte for byte, through a temporary file, then log that it was used."""
    tmp = memory.path.with_name(f".{memory.path.name}.tmp")
    tmp.write_bytes(entry["before"].encode("utf-8"))
    os.replace(tmp, memory.path)
    marker = {"t": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "action": "restore",
              "handle": memory.handle, "undone": entry["line"]}
    with (memory.path.parent / CURATION_LOG).open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(marker, ensure_ascii=False) + "\n")


def curation_due(memories: Sequence[Memory], last_pass: datetime.date | None, today: datetime.date) -> int:
    """Items for a pass: live memories created after the last pass (counted only at 10, or at 1 once the pass is 14
    days old; with no pass yet, once the oldest live memory is) plus active memories past their valid_until (not those
    already past it on the day of the last pass: that pass dealt with them)."""
    live = [m for m in memories if is_live(m, today)]
    new = [m for m in live if last_pass is None or (m.created is not None and m.created > last_pass)]
    if last_pass is not None:
        age = (today - last_pass).days
    else:
        dated = [m.created for m in live if m.created is not None]
        age = (today - min(dated)).days if dated else 0
    counted = len(new) if len(new) >= 10 or (new and age >= 14) else 0
    expired = sum(1 for m in memories if m.error is None and m.status == "active"
                  and m.valid_until is not None and m.valid_until < today
                  and (last_pass is None or m.valid_until >= last_pass))
    return counted + expired


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


_PLACEHOLDER = re.compile(r"^[\"']?(<[^>]*>|\u2026|\.{3}|x{3,}|changeme|example)", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|token)\b[\"']?\s*[:=]\s*[\"']?(\S{8,})")

# Deliberately conservative: a false refusal costs one rewrite, a stored secret may be synced elsewhere.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("API key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
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


STRONG = 0.6  # chosen on evals/signal/set.json by the rule in the stage 6 plan
POSSIBLE = 0.5  # counted only, never named
MIN_TERMS = 2


def containment(claim_tokens: Iterable[str], text_tokens: Collection[str]) -> float:
    """Share of the claim's distinct non-stop-word terms found in the text; 0.0 under MIN_TERMS terms.

    Measured from the claim's side: a brief has hundreds of words and a claim about ten. A token of only digits
    (a year, a count) is not a term: it matches unrelated briefs."""
    terms = {t for t in claim_tokens if not t.isdigit()} - STOPWORDS
    if len(terms) < MIN_TERMS:
        return 0.0
    return len(terms & set(text_tokens)) / len(terms)


class Related(NamedTuple):
    handle: str
    kind: str  # "m" memory, "n" note
    score: float


def related_records(memories: Sequence[Memory], note_stems: Sequence[str], text: str, today: datetime.date, *,
                    tokenize: Callable[[str], list[str]]) -> tuple[list[Related], list[Related]]:
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
