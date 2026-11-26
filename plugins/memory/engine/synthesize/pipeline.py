"""The lean synthesis pipeline shared by `bin/mem-synthesize` and `evals/synthesis/run_trials.py`.

Lean loop (measured in docs/superpowers/plans/2026-11-17-memory-prompts-and-loop.md): check (one line per unsupported
claim) -> one fixer that changes only the listed sentences -> one check scoped to the parts and sentences the fixer
reports -> when it still lists claims, one delete-only step removes those sentences; no third pass. Every step is its
own `claude -p` session. Standard library and the engine's own modules (`records`, `syntheses`: PyYAML)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Required, TypedDict, Unpack

from core import headless
from memories import records
from syntheses import document

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

logger = logging.getLogger(__name__)

PLUGIN = Path(__file__).resolve().parents[2]
MEM = PLUGIN / "bin" / "mem"
BRIEFS = Path(__file__).resolve().parent / "briefs"
SKILL = PLUGIN / "skills" / "memory-synthesis" / "SKILL.md"
CHEAP = "high"  # effort of every Haiku checker and fixer (owner, 2026-11-17: raised from medium, unmeasured)
NOT_GIVEN = "(not given)"

COUNTS = re.compile(
    r"^COUNTS: checked=(\d+) unsupported=(\d+)(?: used=(\d+) unused=(\d+))?\s*$", re.MULTILINE
)
NOTE_LINE = re.compile(r"^NOTE: (\S+) (used|unused)\s*$", re.MULTILINE)
CLAIM_LINE = re.compile(
    r"^(?P<part>[^|\n]+?) \| (?P<start>[^|\n]*) \| (?P<kind>[^|\n]+?) \| (?P<note>[^|\n]*) \| (?P<fix>.*)$"
)
PARTS_LINE = re.compile(r"^PARTS: ?(.*)$", re.MULTILINE)
REF_LINE = re.compile(
    r"^REF: (?P<part>[^|\n]+?) \| (?P<number>\d+) \| (?:(?P<missing>missing)|wrong (?P<current>[^|\n]+?)) \| "
    r"(?P<target>[^|\n]*?)\s*$"
)
REFS_TOTAL = re.compile(r"^s:\S+: added (\d+), removed (\d+), refused (\d+)\s*$", re.MULTILINE)
DENIED = re.compile(
    r"requested permissions|haven't granted|permission.{0,40}denied|denied.{0,40}permission",
    re.IGNORECASE,
)
WRITE_COMMAND = re.compile(r"\s*mem synthesis (new|add|edit|append)\b")


DELETE_ONLY = """
## Additional instruction for this step: delete only

This is the last pass. For every claim the report lists, delete that sentence from its part: ignore any replacement
sentence, write no new text, and leave every other character of the part as it is.
"""


def brief(name: str, briefs: Path = BRIEFS, **values: str) -> str:
    text = (briefs / f"{name}-brief.md").read_text(encoding="utf-8")
    values.setdefault("SKILL_FILE", str(SKILL))
    values.setdefault("PARTS", NOT_GIVEN)
    values.setdefault("UNITS_FILE", NOT_GIVEN)
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    left = re.findall(r"\{[A-Z_]+\}", text)
    assert not left, f"{name}-brief.md has unfilled placeholders: {left}"
    return text


def mem(
    store: Path, env: dict, *args: str, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(MEM), *args],
        env={**env, "MEM_STORE": str(store)},
        input=stdin,
        capture_output=True,
        text=True,
        cwd=store,
        check=False,
    )


def model_family(model_id: str) -> str:
    return next((f for f in ("haiku", "sonnet", "opus") if f in model_id.lower()), model_id)


def cost_by_family(model_usage: dict) -> dict[str, float]:
    costs: dict[str, float] = {}
    for model, usage in model_usage.items():
        family = model_family(model)
        costs[family] = costs.get(family, 0.0) + float(usage.get("costUSD") or 0.0)
    return costs


def _events(stdout: str) -> Iterator[Any]:
    """The JSON value of each line of a stream-json session; a line that is not JSON is skipped."""
    for line in stdout.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _content(event: Any) -> Any:
    message = event.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _tool_uses(content: list) -> dict[str, tuple[str, str]]:
    """Tool call id -> (tool name, its `command` input) of the assistant message's tool_use parts."""
    return {
        part["id"]: (part["name"], (part.get("input") or {}).get("command", ""))
        for part in content
        if part.get("type") == "tool_use"
    }


def _result_text(body: Any) -> str:
    return body if isinstance(body, str) else " ".join(b.get("text", "") for b in body or [])


def _is_write(name: str, command: str) -> bool:
    return name == "Write" or (name == "Bash" and bool(WRITE_COMMAND.match(command)))


def _tally_result(out: dict, uses: dict[str, tuple[str, str]], part: dict) -> None:
    """Count one tool_result: an error, a denial, a write with its exit status."""
    name, command = uses.get(part.get("tool_use_id", ""), ("", ""))
    text = _result_text(part.get("content"))
    failed = bool(part.get("is_error"))
    if failed:
        out["tool_errors"] += 1
        out["denied"] += bool(DENIED.search(text))
    if _is_write(name, command):
        out["writes"] += 1
        out["write_errors"] += failed


def _tally_results(out: dict, uses: dict[str, tuple[str, str]], content: list) -> None:
    for part in content:
        if part.get("type") == "tool_result":
            _tally_result(out, uses, part)


def _tally_final(out: dict, event: Any) -> None:
    out["has_result"] = True
    out["answer"] = event.get("result") or ""
    out["model_usage"] = event.get("modelUsage") or {}
    out["cost"] = float(event.get("total_cost_usd") or 0.0)
    out["error"] = bool(event.get("is_error"))


def parse(stdout: str) -> dict:
    """Facts of one stream-json session: writes with their exit status, denials, cost per model, result."""
    out: dict[str, Any] = {
        "writes": 0,
        "write_errors": 0,
        "denied": 0,
        "tool_errors": 0,
        "model_usage": {},
        "cost": 0.0,
        "error": True,
        "answer": "",
        "has_result": False,
    }
    uses: dict[str, tuple[str, str]] = {}
    for event in _events(stdout):
        kind = event.get("type")
        content = _content(event)
        if kind == "assistant" and isinstance(content, list):
            uses.update(_tool_uses(content))
        elif kind == "user" and isinstance(content, list):
            _tally_results(out, uses, content)
        elif kind == "result":
            _tally_final(out, event)
    return out


# The `mem` subcommands the background sessions may run, one `Bash(mem <sub>*)` rule each. Sources: the curator
# (agents/memory-curator.md: `curate` with `apply --safe`, `show`, `memories`, `search`), the writer
# (agents/memory-synthesizer.md: `find`, `show`, `synthesis list|new|add|append|edit`, `check`), and the checker and
# fixer briefs (briefs/*.md: `search`, `show`, `synthesis edit`, `check`). No `import`, `fetch-sources`, `new`,
# `remember` or `history`: no brief names them, and `attach` and `refs` run from code (`mem()`), not in a session.
MEM_ALLOWED = (
    "curate",
    "show",
    "memories",
    "search",
    "find",
    "check",
    "synthesis list",
    "synthesis new",
    "synthesis add",
    "synthesis append",
    "synthesis edit",
)


def session_roots(store: Path, env: dict, work: Path) -> list[Path]:
    """The folders a background session may read: the store, the global memories folder when it lies outside the
    store, and the work folder."""
    memories = records.global_memories_root(env)
    roots = [store.resolve(), work.resolve()]
    if memories is not None and not records.inside(memories.resolve(), store.resolve()):
        roots.insert(1, memories.resolve())
    return roots


class SessionOptions(TypedDict, total=False):
    """`run_session`'s keyword arguments: `env` and `log` are required, the rest default (timeout 1500)."""

    env: Required[dict]
    log: Required[Path]
    timeout: int
    effort: str | None
    agent: str | None
    max_budget: float | None
    read_roots: Sequence[Path]


def _allowed_tools(work: Path, read_roots: Sequence[Path]) -> list[str]:
    """Headless --allowedTools also limits what a session may run: exactly what a step needs. Body files go in the
    work folder (`//` is an absolute path in a permission rule; a new file needs the Edit rule too); the web stays
    out. Reads only under `read_roots` and the skill folder (`//` again: an absolute path), so injected note text
    cannot make a session read other local files; `mem` runs only the subcommands of MEM_ALLOWED."""
    return [
        *(f"Bash(mem {sub}*)" for sub in MEM_ALLOWED),
        *(
            f"{tool}(/{root}/**)"
            for root in (*read_roots, SKILL.parent)
            for tool in ("Read", "Grep", "Glob")
        ),
        f"Write(/{work}/**)",
        f"Edit(/{work}/**)",
    ]


def _stream(cmd: list[str], work: Path, env: dict, timeout: int) -> str:
    """The session's stdout; the part of it written before the timeout when the session is killed."""
    return headless.run_raw(cmd, cwd=work, env=env, timeout=timeout).stdout


def run_session(
    claude: str,
    model: str,
    prompt: str,
    work: Path,
    settings: Path,
    **options: Unpack[SessionOptions],
) -> dict:
    read_roots = options.get("read_roots", ())
    cmd = headless.command(
        headless.Session(
            claude=claude,
            prompt=prompt,
            model=model,
            settings=settings,
            effort=options.get("effort") or None,
            plugin_dir=PLUGIN,
            allowed=tuple(_allowed_tools(work, read_roots)),
            disallowed=("WebSearch", "WebFetch"),
            # the session stops itself past this spend (--print only)
            max_budget=options.get("max_budget"),
            # the agent's body is the session's system prompt
            agent=options.get("agent") or None,
        )
    )
    env = {
        **options["env"],
        "MEM_SANDBOX": "1",
        "MEM_SANDBOX_ROOTS": os.pathsep.join(str(r) for r in read_roots),
    }
    start = time.monotonic()
    raw = _stream(cmd, work, env, options.get("timeout", 1500))
    options["log"].write_text(raw, encoding="utf-8")
    result = parse(raw)
    result["wall"] = time.monotonic() - start
    return result


def units_text(synthesis: Path) -> str:
    """What the checker's `{UNITS_FILE}` holds: per part (not the Summary) `## <handle>`, one line per unit
    `<number> | <text without references> | <targets, or ->`, then `Sources: <note targets>`."""
    lines = []
    for section in document.load_one(synthesis).parts:
        found, _ = document.units(section.text)
        lines.append(f"## {section.handle}")
        lines += [
            f"{u.n} | {' '.join(u.plain.split())} | {', '.join(u.refs) or '-'}" for u in found
        ]
        lines.append("Sources: " + ", ".join(t for t in section.sources if document._is_ref(t)))
    return "\n".join(lines) + "\n"


def write_units(synthesis: Path, target: Path) -> None:
    target.write_text(units_text(synthesis), encoding="utf-8")


def _ref_text(ln: str) -> str | None:
    """A `REF:` line as the model may write it: after a bullet, indented, in backticks."""
    s = ln.strip().lstrip("-*\u2022 \t").replace("`", "").strip()
    return s if s.startswith("REF:") else None


def _target(value: str | None) -> str | None:
    value = (value or "").strip().rstrip(".").strip()
    return None if value.lower() in {"", "none"} else value


def _reported_handle(value: str) -> str:
    """A model may write a heading where the brief asks for a handle: both become the handle `mem` gives the part."""
    return section_handle(value.strip().removeprefix("s:").split("#")[-1])


def _ref_row(m: re.Match[str]) -> dict:
    return {
        "part": _reported_handle(m["part"]),
        "number": int(m["number"]),
        "kind": "missing" if m["missing"] else "wrong",
        "current": _target(m["current"]),
        "target": _target(m["target"]),
    }


def _refs(lines: list[str]) -> tuple[list[dict], int]:
    """The `REF:` lines' rows and the count of malformed ones."""
    refs, malformed = [], 0
    for ln in lines:
        if (s := _ref_text(ln)) is None:
            continue
        if m := REF_LINE.match(s):
            refs.append(_ref_row(m))
        else:
            malformed += 1
    return refs, malformed


def _claims(lines: list[str]) -> list[dict]:
    found = [m.groupdict() for ln in lines if _ref_text(ln) is None and (m := CLAIM_LINE.match(ln))]
    for claim in found:
        claim["part"] = _reported_handle(claim["part"])
    return found


def _parts(text: str, claims: list[dict]) -> list[str]:
    listed = PARTS_LINE.search(text)
    parts = [
        _reported_handle(h) for h in (listed.group(1) if listed else "").split(",") if h.strip()
    ]
    return list(dict.fromkeys(parts + [c["part"] for c in claims]))


def _note_states(text: str) -> dict[str, str]:
    notes = {}
    for rel, state in NOTE_LINE.findall(text):
        at = rel.find("knowledge/")
        notes[rel[at:] if at >= 0 else rel] = state
    return notes


def parse_report(path: Path) -> dict | None:
    """The checker's report: its last COUNTS line, the PARTS line, the claim lines, the `REF:` lines (reference
    problems, never claims; a malformed one is only counted in `ref_malformed`) and the judge's NOTE lines.

    None when the file or the COUNTS line is missing. A report with no unsupported claim holds only the COUNTS line."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    found = COUNTS.fullmatch(lines[-1]) if lines else None
    if not found:
        return None
    claims = _claims(lines)
    refs, malformed = _refs(lines)
    unsupported = int(found.group(2))
    if not claims and (refs or malformed):
        # A checker that counted its reference problems as unsupported lists no claim: nothing is there to fix or
        # delete, and the delete-only step must not run for it.
        unsupported = 0
    return {
        "checked": int(found.group(1)),
        "unsupported": unsupported,
        "notes": _note_states(text),
        "claims": claims,
        "parts": _parts(text, claims),
        "refs": refs,
        "ref_malformed": malformed,
    }


def scope_text(report: dict, fixer_answer: str) -> str:
    """What the scoped second check receives in `{PARTS}`: the fixer's own report of the parts and sentences it
    changed; when the fixer said nothing usable, the parts and sentence starts the first report listed."""
    answer = fixer_answer.strip()
    if answer:
        return answer[:2000]
    return "; ".join(
        f"{c['part'].strip()}: {c['start'].strip()}" for c in report["claims"]
    ) or ", ".join(report["parts"])


def section_handle(heading: str) -> str:
    """As `document.section_handle` of the engine: the handle `mem` gives a part."""
    ascii_text = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def resolve_parts(parts: list[str], text: str) -> list[str]:
    """Reported parts as handles: a checker may name a part by the line range `mem show s:<slug>` prints
    (`12-30`), which is the part whose heading sits on the range's first line."""
    by_line = {
        n: section_handle(line[3:])
        for n, line in enumerate(text.splitlines(), 1)
        if line.startswith("## ")
    }
    out = []
    for part in parts:
        m = re.fullmatch(r"(\d+)-\d+", part)
        out.append(by_line.get(int(m.group(1)), part) if m else part)
    return list(dict.fromkeys(out))


def split_parts(text: str) -> dict[str, str]:
    """Part handle -> exact part text (heading line included); the front matter and anything before the first part
    are left out."""
    pieces = re.split(r"^(?=## )", text, flags=re.MULTILINE)[1:]
    return {section_handle(piece.splitlines()[0][3:]): piece for piece in pieces}


def changed_outside(before: str, after: str, allowed: list[str]) -> list[str]:
    """Handles of the parts that differ between the two texts although they are not in `allowed`: a fixer may touch
    only the parts its report lists, and an untouched part must stay byte-equal."""
    old, new = split_parts(before), split_parts(after)
    return sorted(
        h for h in old.keys() | new.keys() if old.get(h) != new.get(h) and h not in allowed
    )


class GuardOptions(TypedDict):
    allowed: list[str]


def guard_parts(
    store: Path, env: dict, topic: str, before: str, after: str, **options: Unpack[GuardOptions]
) -> tuple[list[str], list[str]]:
    """(violations, reverted): the parts changed outside `allowed` and those put back to their text in `before`
    through `mem synthesis edit --shrink`, so the undo log and `mem check` stay consistent. A part the fixer removed
    or added cannot be put back by `edit`: it stays in the violations only."""
    violations = changed_outside(before, after, options["allowed"])
    old, new = split_parts(before), split_parts(after)
    reverted = [
        handle
        for handle in violations
        if handle in old and handle in new and _put_back(store, env, topic, handle, old[handle])
    ]
    return violations, reverted


def _put_back(store: Path, env: dict, topic: str, handle: str, old_part: str) -> bool:
    text = old_part.split("\n", 1)[1].strip("\n") if "\n" in old_part else ""
    done = mem(
        store,
        env,
        "synthesis",
        "edit",
        f"s:{topic}#{handle}",
        "--body-file",
        "-",
        "--shrink",
        "--drop-references",
        stdin=text + "\n",
    )
    return done.returncode == 0


def summary(s: dict) -> dict:
    return {
        "role": s["role"],
        "model": s["model"],
        "costs": s["costs"],
        "cost": s["cost"],
        "wall": s["wall"],
        "writes": s["writes"],
        "write_errors": s["write_errors"],
        "denied": s["denied"],
        "tool_errors": s["tool_errors"],
        "ok": s["has_result"] and not s["error"],
    }


class StopError(Exception):
    """The loop ends: the budget is spent, or a session left no cost report."""


NO_COST = "a session ended without a cost report"


class LoopOptions(TypedDict, total=False):
    """`lean_loop`'s keyword arguments: `settings`, `topic` and `sessions` are required."""

    settings: Required[Path]
    topic: Required[str]
    sessions: Required[list[dict]]
    lean: bool
    left: Callable[[], float] | None
    briefs: Path
    read_roots: Sequence[Path]


def _ref_lines(refs: list[dict]) -> list[str]:
    """The reported `REF:` rows as `mem synthesis refs` proposal lines."""
    lines = []
    for r in refs:
        if r["kind"] == "wrong" and r["current"]:
            lines.append(f"{r['part']} | {r['number']} | remove {r['current']}")
        if r["target"]:
            lines.append(f"{r['part']} | {r['number']} | add {r['target']}")
    return lines


def _record_refs_result(row: dict, done: subprocess.CompletedProcess[str]) -> None:
    """What `mem synthesis refs` printed into the loop's row for the check."""
    total = REFS_TOTAL.findall(done.stdout)
    if done.returncode or not total:
        row["error"] = (done.stderr.strip() or done.stdout.strip() or f"exit {done.returncode}")[
            :200
        ]
        return
    added, removed, refused = map(int, total[-1])
    row.update(
        applied=added + removed,
        refused=refused,
        reasons=[
            ln[len("refused: ") :] for ln in done.stdout.splitlines() if ln.startswith("refused: ")
        ],
    )


@dataclass
class _Loop:
    claude: str
    env: dict
    base: Path
    store: Path
    work: Path
    settings: Path
    topic: str
    sessions: list[dict]
    lean: bool
    left: Callable[[], float] | None
    briefs: Path
    read_roots: Sequence[Path]
    out: dict[str, Any] = field(
        default_factory=lambda: {
            "arm_count": None,
            "why": "",
            "fixes": 0,
            "deleted": 0,
            "scope_violations": [],
            "reverted": [],
            "refs": [],
        }
    )

    @property
    def synthesis(self) -> Path:
        return self.store / "syntheses" / f"{self.topic}.md"

    @property
    def fill(self) -> dict[str, str]:
        return {
            "TOPIC": self.topic,
            "SLUG": self.topic,
            "STORE": str(self.store),
            "WORK_DIR": str(self.work),
        }

    def step(self, role: str, model: str, text: str, level: str | None = None) -> dict:
        remaining = self.left() if self.left else None
        if remaining is not None and remaining <= 0:
            raise StopError("budget spent")
        s = run_session(
            self.claude,
            model,
            text,
            self.work,
            self.settings,
            env=self.env,
            log=self.base / f"{len(self.sessions) + 1:02d}-{role}.jsonl",
            effort=level,
            max_budget=remaining,
            read_roots=self.read_roots,
        )
        s.update(role=role, model=model, costs=cost_by_family(s["model_usage"]))
        self.sessions.append(summary(s))
        if self.left and not s["has_result"]:
            raise StopError(NO_COST)
        return s

    def check(self, n: int, scope: str = NOT_GIVEN) -> dict | None:
        report = self.work / f"report-{n}.md"
        report.unlink(missing_ok=True)
        units = self.work / f"units-{n}.md"
        write_units(self.synthesis, units)  # rewritten per check: the fixer changed the text
        text = brief(
            "checker",
            self.briefs,
            **self.fill,
            REPORT_FILE=str(report),
            PARTS=scope,
            UNITS_FILE=str(units),
        )
        self.step("checker", "haiku", text, CHEAP)
        return parse_report(report)

    def apply_refs(self, n: int, report: dict | None) -> None:
        """The report's `REF:` lines through `mem synthesis refs`, before anything changes the text their numbers
        refer to. A failure is recorded, never raised."""
        if not report or not (report["refs"] or report["ref_malformed"]):
            return
        lines = _ref_lines(report["refs"])
        row = {
            "check": n,
            "reported": len(report["refs"]),
            "malformed": report["ref_malformed"],
            "lines": len(lines),
            "applied": 0,
            "refused": 0,
            "reasons": [],
            "error": "",
        }
        self.out["refs"].append(row)
        if not lines:
            return
        proposals = self.work / f"refs-{n}.txt"
        proposals.write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")
        try:
            done = mem(
                self.store,
                self.env,
                "synthesis",
                "refs",
                f"s:{self.topic}",
                "--file",
                str(proposals),
            )
        except OSError as exc:
            row["error"] = str(exc)
            return
        _record_refs_result(row, done)

    def guarded_fix(
        self, model: str, level: str | None, text: str, report: dict, role: str = "fixer"
    ) -> dict:
        """One fixer step; the parts it changed outside the report's PARTS are recorded and put back."""
        before = self.synthesis.read_text(encoding="utf-8")
        s = self.step(role, model, text, level)
        bad, back = guard_parts(
            self.store,
            self.env,
            self.topic,
            before,
            self.synthesis.read_text(encoding="utf-8"),
            allowed=resolve_parts(report["parts"], before),
        )
        self.out["scope_violations"].extend(bad)
        self.out["reverted"].extend(back)
        return s

    def delete_only(self, text: str, second: dict) -> None:
        report_1, report_2 = self.work / "report-1.md", self.work / "report-2.md"
        self.guarded_fix(
            "haiku",
            CHEAP,
            text.replace(str(report_1), str(report_2)) + DELETE_ONLY,
            second,
            "deleter",
        )
        self.out["deleted"] = len(second["claims"]) or second["unsupported"]

    def fix(self, first: dict) -> None:
        self.out["fixes"] = 1
        text = brief("fixer", self.briefs, **self.fill, REPORT_FILE=str(self.work / "report-1.md"))
        if not self.lean:
            self.guarded_fix("sonnet", None, text, first)
            return
        fixed = self.guarded_fix("haiku", CHEAP, text, first)
        second = self.check(2, scope_text(first, fixed["answer"]))
        self.apply_refs(2, second)
        if second is None:
            self.out["why"] = "scoped check report unreadable"
        elif second["unsupported"]:
            self.delete_only(text, second)

    def steps(self) -> None:
        first = self.out["arm_count"] = self.check(1)
        self.apply_refs(1, first)
        if first is None:
            self.out["why"] = "arm checker report unreadable"
        elif first["unsupported"]:
            self.fix(first)

    def run(self) -> dict:
        try:
            self.steps()
        except StopError as stop:
            self.out["why"] = str(stop)
        return self.out


def lean_loop(
    claude: str,
    env: dict,
    base: Path,
    store: Path,
    work: Path,
    **options: Unpack[LoopOptions],
) -> dict:
    """Check, fix, and (lean) scoped check and delete-only step for the synthesis `s:<topic>` already in `store`.

    Each session's summary is appended to `sessions`; session streams go to `base/NN-<role>.jsonl`. Returns
    `arm_count` (first check, None when its report is unreadable), `why` (empty when every step worked), `fixes`,
    `deleted`, `scope_violations`, `reverted` (the violations put back), `refs` (per check that reported `REF:` lines:
    `check`, `reported` lines, proposal `lines` sent, `applied` and `refused` as `mem synthesis refs` printed them,
    `error` when the command failed). `briefs` is the folder the brief files are read from; `read_roots` the folders
    the sessions may read (see `run_session`). `lean=False` is the trial's arm S: one Sonnet fixer, no second check.
    `left` (a function: USD still allowed) caps every step: none starts when nothing is left, each session gets
    `--max-budget-usd` of what is left, and a session without a result event (killed at its timeout: its spend is
    unknown) ends the loop with `why` = NO_COST."""
    return _Loop(
        claude,
        env,
        base,
        store,
        work,
        settings=options["settings"],
        topic=options["topic"],
        sessions=options["sessions"],
        lean=options.get("lean", True),
        left=options.get("left"),
        briefs=options.get("briefs", BRIEFS),
        read_roots=options.get("read_roots", ()),
    ).run()
