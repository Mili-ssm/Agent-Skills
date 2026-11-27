"""mem-corroborate: the model sessions, the briefs, the applier and `execute` (one run); what the three jobs share."""

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from capture import state as cs
from core import codex_pass, headless, jobs
from core import runner as runners
from memories import records
from synthesize import pipeline as sp

from corroborate import decide as corroborate_decide
from corroborate import state as corroborate_state

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


PROPOSE_MODEL = VERIFY_MODEL = "haiku"


CHECK_MODEL = "haiku"  # the second session of the automatic fill; chosen by the gate of 2026-11-22 (the plan's Results)


SESSION_TIMEOUT = 600


MAX_FILE_BYTES = 1_000_000


# the exit of `mem remember` and `mem confirm` for a claim or a case that is already there
ALREADY_THERE = 3


ROW_FIELDS = 2  # a `remember` row that says what happened: the handle, then "sighting" or the like


REMEMBER_BODY = (
    "Written by the corroboration pass; its sightings are the sessions and projects in `sources`.\n"
)


# Not resolved: `fake_plugin` in the tests links `engine/`, and a resolved path would reach the real `bin/mem`.
MEM = Path(__file__).parent.parent.parent / "bin" / "mem"


MEM_TIMEOUT = 60


SETTLE_STATE = ".settle-state.json"  # beside the global records; `settle.STATE_NAME`


SESSION_VARS = (
    "CLAUDE_ENV_FILE",
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDE_PLUGIN_DATA",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_PID",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
)


# `settle.state.maybe_start` starts a run from these
SETTLE_VARS = ("MEM_SETTLE_AUTO", "MEM_SETTLE_MINUTES", "MEM_SETTLE_CLAUDE")


ANSWERS = ("same", "faithful", "general")


MAX_RETRIES = 2  # runs that end with a failed action or an unusable answer on the same lessons before the run gives up


# a `mem merge` refuses with any non-zero exit; any other exit is a failure
REFUSED_MEM_EXITS = {"remember": (4, 5)}


class StopError(Exception):
    """A run that cannot go on: `short` is the fixed reason the log line keeps, the message goes to the run's log.txt."""

    def __init__(self, short: str, detail: str):
        super().__init__(detail)
        self.short = short


PROPOSE_BRIEF = """You compare short lessons that coding sessions wrote down, and say which of them state the same lesson.

Read {lessons}. Each line is: an id, a reach (general or project), the lesson, and when it applies, separated by tabs.
Ids starting with g: are lessons already kept for every project; ids starting with p1:, p2: ... belong to one project each.
An id is copied whole, exactly as written, with its g: or p1: start; a line number that your reading tool shows before a line is not an id.

Two lessons are the same when a reader who follows one would do what the other asks, in the same kind of situation,
even if the words, the example or the numbers differ. Lessons about the same topic that advise different things are
not the same. When you are not sure, leave them apart: a wrong group merges two lessons and loses one.

Write {out} as JSON: {{"groups": [{{"ids": ["..."], "claim": "...", "context": "..."}}]}}
- One group for each set of two or more lessons that are the same.
- Also one group for each general lesson with a p id that is in no other group and matches no g: lesson: a group of one.
- Never a group of one for a g: lesson or a project lesson.
- An id appears in at most one group.
- claim: the lesson in one to three sentences, as a suggestion or a recommendation that says what was seen and what
  is not known, never an order. It must hold in any project: name no project, company, client, person, repository,
  file, path, product or internal system. Keep what a reader needs to act: the situation, the action, the reason.
- context: one sentence on when the lesson applies, under the same rule about names.
Write nothing else and use no other tool.
"""


VERIFY_BRIEF = """You check proposals to treat several short lessons as one. Another reader made the proposals; it is often wrong, and
a wrong "yes" merges two different lessons and loses one, so say yes only when you are sure.

Read {groups}. Each block starts with "group <n>", then one line per lesson (an id, the lesson, when it applies,
separated by tabs), then a line starting with "proposed": the single wording that would replace them for every project.

For each group, answer in this order:
- reason: one sentence saying what each lesson asks the reader to do and whether that is the same thing.
- same: true only if a reader who follows any one of the lessons would do what each of the others asks, in the same
  kind of situation. The same topic with different advice is false. For a group of one lesson, write true.
- faithful: true only if the proposed wording keeps the situation, the action and the reason of the lessons, adds no
  claim they do not make, turns no suggestion into an order, and names no project, company, client, person,
  repository, file, path, product or internal system.
- general: true only if the lesson is about how to work (planning, delegating, verifying, using tools, reading what
  was asked) and would hold in another project; false if it only makes sense inside one codebase or product.

Write {out} as JSON: {{"verdicts": [{{"group": 1, "reason": "...", "same": true, "faithful": true, "general": true}}]}}
One entry per group, in order. Write nothing else and use no other tool.
"""


FILL_BRIEF = """You write the short form and the topic of lessons that coding sessions wrote down.
Read {lessons}: one block per lesson, with an id, a claim and sometimes a context.
For each lesson write: short: one sentence of at most 120 characters (aim for 100) that says what may be worth doing and when, as a suggestion, never stronger than the claim. Name the action as a thing or an -ing form ("quoting the source line may catch errors"), not as a command to the reader ("quote the source line"), unless the claim itself is a command. Keep the claim's hedge (may, once, sometimes, untested, provisional); if it is too long, drop alternatives and detail first, never the hedge. It must stand on its own, say "the user" and never "the owner", name no project, person or company, and add nothing the claim does not say. Use the context only to see when it applies. topic: one or two lowercase words for the area (for example: testing, process, shell, review, docs). An id is copied whole.
Write {out} as JSON: {{"items": [{{"id": "g:example", "short": "...", "topic": "..."}}]}}
One item per lesson. Write nothing else and use no other tool.
"""


CHECK_BRIEF = """You check one-sentence short forms of lessons against the lessons they were drawn from. Another writer made them; it sometimes makes a short form stronger or wider than its lesson, and a short form is loaded into every later session, so say faithful only when you are sure.
Read {pairs}: one block per lesson, with an id, a claim, sometimes a context that says when the lesson applies, and a short.
For each block answer in this order:
- reason: one sentence comparing what the claim asks, and when, with what the short asks, and when.
- faithful: true only if the short asks for nothing the claim does not, in no wider a situation, with no more certainty (a "may" or "once" in the claim is still there in the short), as a suggestion and not an order unless the claim is an order (a command addressed to the reader, such as "remove the files" or "confirm it first", is an order even when a "may" stands elsewhere in the sentence), and names no project, person or company. A short that leaves out examples or alternatives is still faithful; one that leaves out the situation the claim is about is not.
Write {out} as JSON: {{"verdicts": [{{"id": "g:example", "reason": "...", "faithful": true}}]}}
One entry per block. Write nothing else and use no other tool.
"""


REWORD_BRIEF = """You rewrite the short form of lessons that coding sessions wrote down. Each short form below was loaded into later sessions and the thing the lesson warns about still happened, so the present wording did not reach its reader.
Read {lessons}: one block per lesson, with an id, a claim, sometimes a context, every wording tried so far with how often the lesson then worked and failed, and what kind of failure followed where it is recorded.
For each lesson write: short: one sentence of at most 120 characters (aim for 100), drawn from the claim and not from the earlier wordings, that differs from all of them. Start with the situation in which it applies, in words a reader in that situation would recognize, then name what may be worth doing as a thing or an -ing form ("quoting the source line may catch errors"), not as a command to the reader, unless the claim itself is a command. It is a suggestion and never stronger than the claim: keep the claim's hedge (may, once, sometimes, untested, provisional); if it is too long, drop alternatives and detail first, never the hedge. It must stand on its own, say "the user" and never "the owner", name no project, person or company, and add nothing the claim does not say. An id is copied whole.
Write {out} as JSON: {{"items": [{{"id": "g:example", "short": "..."}}]}}
One item per lesson. Write nothing else and use no other tool.
"""


DIGEST_BRIEF = """You write, for groups of lessons that coding sessions wrote down, the text that later sessions read at their start. The lessons of one topic are printed together under one heading, so the heading says once what they share and each lesson's line does not repeat it.
Read {topics}: one block per topic, with its name, its heading (marked keep and followed by its text, or the word write), and its lessons. Each lesson has an id, a claim, sometimes a context, its short form, and the word write or keep; a kept lesson shows the line it already has, for you to read and not to change.
For a topic whose heading says write, write: heading: at most 80 characters, the situation in which the topic's lessons apply, as a clause a line can follow ("when briefing or reading a subagent"), true of every lesson under it, holding no advice, ending without a period, and naming no project, person or company.
For each lesson that says write, write: line: one sentence of at most 120 characters (aim for 100) that reads on from the heading. It does not repeat the situation the heading names; it says what may be worth doing, and why when the claim says why, drawn from the claim and not from the short form. It is a suggestion and never stronger than the claim: keep the claim's hedge (may, once, sometimes, untested, provisional); if it is too long, drop alternatives and detail first, never the hedge. Name the action as a thing or an -ing form ("quoting the source line may catch errors"), not as a command to the reader, unless the claim itself is a command. If the claim applies in a narrower situation than the heading, say so in the line. Say "the user" and never "the owner", name no project, person or company, and add nothing the claim does not say. An id is copied whole.
Write {out} as JSON: {{"topics": [{{"topic": "example", "heading": "...", "lines": [{{"id": "g:example", "line": "..."}}]}}]}}
Leave "heading" out for a topic whose heading is kept, and write lines only for lessons that say write. Write nothing else and use no other tool.
"""


DIGEST_CHECK_BRIEF = """You check texts that are loaded into every later coding session. The lessons of one topic are printed under a heading that names a situation, each as a line that reads on from it. Another writer made the headings and lines; it sometimes makes a line stronger or wider than its lesson, so say true only when you are sure.
Read {pairs}: one block per lesson, with an id, a claim, sometimes a context that says when the lesson applies, the heading of its topic, and its line.
For each block answer in this order:
- reason: one sentence comparing what the claim asks, and when, with what the heading and the line ask together, and when.
- fits: true only if the situation the claim is about lies inside the situation the heading names.
- faithful: true only if the heading and the line, read together, ask for nothing the claim does not, in no wider a situation than the claim's (when the heading is wider, the line must narrow it), with no more certainty (a "may" or "once" in the claim is still there), as a suggestion and not an order unless the claim is an order, and name no project, person or company. A line that leaves out examples or alternatives is still faithful; one that adds a reason or a condition the claim does not state is not.
Write {out} as JSON: {{"verdicts": [{{"id": "g:example", "reason": "...", "fits": true, "faithful": true}}]}}
One entry per block. Write nothing else and use no other tool.
"""


class SessionLimits(NamedTuple):
    """The model name and the maximum budget in USD of one session."""

    model: str
    max_budget: float


@dataclass
class Spend:
    """The runner of one run, resolved once, and the tokens its Codex sessions have used (Codex reports no money)."""

    runner: str = "claude"
    tokens: int = 0

    @property
    def spent_up(self) -> bool:
        return self.runner == "codex" and codex_pass.over_cap(self.tokens)


class AskJob(NamedTuple):
    """What `_ask` runs: the brief template, the text for the session, the template's key for that text and the
    output file name."""

    template: str
    text: str
    text_key: str
    out_name: str
    spend: Spend | None = None


def session_spec(
    claude: str, work: Path, brief: str, settings: Path, limits: SessionLimits
) -> headless.Session:
    model, max_budget = limits
    return headless.Session(
        claude=claude,
        prompt=brief,
        model=model,
        effort="medium",
        settings=settings,
        tools=("Read", "Write"),
        allowed=(f"Read(/{work}/**)", f"Write(/{work}/**)", f"Edit(/{work}/**)"),
        disallowed=("Bash", "WebSearch", "WebFetch"),
        max_budget=max_budget,
    )


def session_cmd(
    claude: str, work: Path, brief: str, settings: Path, limits: SessionLimits
) -> list[str]:
    """One session. Only Read and Write exist (`--tools`, no MCP server) and the rules allow them inside `work`
    only; no Bash, no web, hooks disabled by `settings`."""
    return headless.command(session_spec(claude, work, brief, settings, limits))


def run_session(cmd: list[str], work: Path) -> dict:
    raw = headless.run_raw(
        cmd, cwd=work, env=headless.session_env(), timeout=SESSION_TIMEOUT, errors="replace"
    ).stdout
    return sp.parse(raw)


def run_on(spend: Spend, work: Path, spec: headless.Session) -> dict:
    """One session on the run's runner; the `sp.parse` dict, with `tokens` from Codex. Codex writes its output file
    in `work`, which is its whole sandbox."""
    if spend.runner == "codex":
        done = codex_pass.ask(spec, work, writes=True, timeout=SESSION_TIMEOUT)
        spend.tokens += done["tokens"]
        return done
    return run_session(headless.command(spec), work)


def missing_codex(spend: Spend) -> str | None:
    """Why a Codex run cannot start a session, or None (also for a Claude run)."""
    if spend.runner == "codex" and runners.find_codex() is None:
        return codex_pass.NO_CODEX
    return None


def read_object(path: Path) -> object:
    """The JSON of `path`, or None when it is missing, too large or not JSON (the validators then say why)."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _remember_args(a) -> list[str]:
    """The `mem remember --global` call that writes the record of a `write_global` action."""
    args = ["remember", "--global", f"--kind={a.record_kind}", f"--claim={a.claim}"]
    if a.context:
        args.append(f"--context={a.context}")
    args += ["--origin", "transcript", "--reach", "general", "--weight", a.weight]
    return [*args, *(f"--source={e}" for e in a.entries), "--body-file", "-"]


def _first_row(done: subprocess.CompletedProcess[str]) -> list[str]:
    """The tab-separated fields of the first line `mem` printed (a handle, then what happened)."""
    text = done.stdout.strip()
    return text.splitlines()[0].split("\t") if text else []


class Applier:
    """Applies the kept groups through `bin/mem`; the counts of what happened are in `counts`.

    A refusal (exit 4 or 5 of `remember`, a non-zero `merge`) is counted and marked so the group is not tried again.
    Any other result of a `mem` call (an undocumented exit code, a timeout, no process) is a failure: it stops the
    group, marks nothing and keeps the run from saving its fingerprint, so the next run tries again."""

    def __init__(
        self,
        journal: corroborate_state.Journal,
        lessons: dict,
        gfolder: Path | None,
        cwd: Path,
        log: Callable[[str], None],
    ):
        self.journal, self.lessons, self.gfolder, self.cwd, self.log = (
            journal,
            lessons,
            gfolder,
            cwd,
            log,
        )
        self.counts = {
            "written": 0,
            "sightings": 0,
            "links": 0,
            "merges": 0,
            "refused": 0,
            "failed_actions": 0,
            "cases": 0,
        }
        self.refused_ids: set[str] = set()
        self.current: corroborate_decide.Group | None = None
        self.written: str | None = (
            None  # the global record that this group's write_global made or found
        )

    def mem(
        self,
        args: list[str],
        project: Path | None = None,
        stdin: str | None = None,
        drop_env: tuple = (),
    ) -> subprocess.CompletedProcess[str] | None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in SESSION_VARS and k not in drop_env and k != "MEM_PROJECT"
        }
        if project is not None:
            env["MEM_PROJECT"] = str(project)
        try:
            done = subprocess.run(
                [str(MEM), *args],
                env=env,
                cwd=self.cwd,
                input=stdin,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=MEM_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.log(f"mem {args[0]}: could not run ({type(exc).__name__})")
            return None
        self.log(
            f"mem {args[0]}: exit {done.returncode} {done.stdout.strip()[:120]!r} {done.stderr.strip()[:200]!r}"
        )
        return done

    def handle(self, lesson_id: str) -> str:
        return f"m:{self.lessons[lesson_id].memory.handle}"

    def add_cases(self, target: str, entries: list[str], cases: list[str]) -> bool:
        """One `mem confirm` per case of the action, for the session's entry; exit 3 (the case is already there) is
        fine, exit 0 counts a case written. False when a call failed."""
        by_session = {records.session_key(e): e for e in reversed(entries)}
        for raw in cases:
            c = records.case(raw)
            entry = by_session.get(c.session) if c else None
            if c is None or entry is None:
                continue
            done = self.mem([
                "confirm",
                target,
                "--global",
                f"--source={entry}",
                f"--outcome={c.outcome}",
                f"--seen-on={c.on.isoformat()}",
            ])
            if done is None or done.returncode not in {0, ALREADY_THERE}:
                return False
            self.counts["cases"] += done.returncode == 0
        return True

    def sight(self, target: str, entry: str, cases: list[str]):
        """The sighting of `entry`: its first case rides on the first call, so no `seen` entry is logged for it. The
        result of that call, and whether the cases after it went well (None when the call itself did not work)."""
        parsed = [c for c in map(records.case, cases) if c]
        extra = (
            [f"--outcome={parsed[0].outcome}", f"--seen-on={parsed[0].on.isoformat()}"]
            if parsed
            else []
        )
        done = self.mem(["confirm", target, "--global", f"--source={entry}", *extra])
        if done is None or done.returncode not in {0, ALREADY_THERE}:
            return done, None
        if parsed and done.returncode == 0:
            self.counts["cases"] += 1
        return done, self.add_cases(target, [entry], cases[1:] if parsed else cases)

    def path(self, lesson_id: str) -> Path:
        return self.lessons[lesson_id].memory.path

    def apply(self, group, acts) -> bool:
        """Every action of one group, in order; False when one was refused or failed and the rest was left."""
        self.written = None
        steps = {
            "merge": self._merge,
            "merge_global": self._merge,
            "write_global": self._write_global,
            "sighting": self._sighting,
            "cases": self._cases,
            "link": self._link,
        }
        for a in acts:
            step = steps.get(a.kind)
            if step is not None and not step(a):
                return False
        return True

    def _merge(self, a) -> bool:
        args = [
            "merge",
            *(["--global"] if a.kind == "merge_global" else []),
            self.handle(a.keep),
            self.handle(a.drop),
        ]
        before = self.journal.watch([self.path(a.keep), self.path(a.drop)])
        done = self.mem(args, a.project)
        self.journal.commit(a.kind, before)
        if done is None:
            return self.fail()
        if done.returncode:
            return self.refuse()  # left for curation, never forced
        self.counts["merges"] += 1
        return True

    def _run_remember(self, a) -> tuple[subprocess.CompletedProcess[str] | None, list[str], bool]:
        """`mem remember` for a `write_global` action and the cases of its record: the result, its first row, whether
        the case calls went well; what changed in the global folder is journaled."""
        before = self.journal.watch_folder(self.gfolder) if self.gfolder else {}
        # no counts in the body: the record is not rewritten when a sighting arrives, so a figure would go stale
        done = self.mem(_remember_args(a), stdin=REMEMBER_BODY)
        first = _first_row(done) if done else []
        cases_ok = True
        if (
            done is not None
            and done.returncode in {0, ALREADY_THERE}
            and first
            and first[0].startswith("m:")
        ):
            cases_ok = self.add_cases(first[0], a.entries, a.cases)
        self.journal.commit("write_global", before, self.gfolder)
        return done, first, cases_ok

    def _write_global(self, a) -> bool:
        done, first, cases_ok = self._run_remember(a)
        named = bool(first) and first[0].startswith("m:")
        if done is not None and done.returncode == 0 and named:
            self.counts["written"] += 1  # the record exists, though a case call may have failed
            self.written = first[0]
        if done is None or not cases_ok:
            return self.fail()
        if done.returncode == ALREADY_THERE and len(first) == ROW_FIELDS and named:
            self.written = first[0]  # the claim exists: its sightings were added by `remember`
            self.counts["sightings"] += first[1] == "sighting"
            return True
        if done.returncode == 0 and named:
            return True
        if done.returncode in REFUSED_MEM_EXITS["remember"]:
            return self.refuse()
        return self.fail()

    def _sighting(self, a) -> bool:
        target = (a.target and f"m:{a.target}") or self.written
        if not target or not self.gfolder:
            return self.refuse()
        before = self.journal.watch([self.gfolder / f"{target[2:]}.md"])
        done, cases_ok = self.sight(target, a.entry, a.cases)
        self.journal.commit("sighting", before)
        if done is not None and done.returncode == 0:
            self.counts["sightings"] += 1
        if cases_ok is False or done is None or done.returncode not in {0, ALREADY_THERE}:
            return self.fail()
        return True

    def _cases(self, a) -> bool:
        if not a.target or not self.gfolder:
            return self.refuse()
        before = self.journal.watch([self.gfolder / f"{a.target}.md"])
        cases_ok = self.add_cases(f"m:{a.target}", [a.entry], a.cases)
        self.journal.commit("cases", before)
        return cases_ok or self.fail()

    def _link(self, a) -> bool:
        target = (a.target and f"m:{a.target}") or self.written
        if not target:
            return self.refuse()
        before = self.journal.watch([self.path(a.member)])
        done = self.mem(["promote", "--done", self.handle(a.member), "--to", target], a.project)
        self.journal.commit("link", before)
        if done is not None and done.returncode == 0:
            self.counts["links"] += 1
            return True
        return self.fail()

    def refuse(self) -> bool:
        self.counts["refused"] += 1
        if self.current is None:  # only `apply` reaches here, with the group set by `_apply_groups`
            raise AttributeError("refuse() needs the group being applied")
        self.refused_ids.update(self.current.ids)
        return False

    def fail(self) -> bool:
        self.counts["failed_actions"] += 1
        return False


def stable_key(lesson) -> str:
    """The name of a lesson that does not change between runs (the ids of a lessons file depend on the registry)."""
    return corroborate_decide.fill_key(lesson.project, lesson.memory.handle)


def planned(acts) -> list[dict]:
    out = []
    for a in acts:
        row = {k: v for k, v in vars(a).items() if v not in (None, [], "")}
        if "project" in row:
            row["project"] = records.project_key(a.project)
        out.append(row)
    return out


def refused_by_verdict(verdict_data: object, n: int) -> bool:
    """True when exactly one verdict names group `n` and its `same` or `general` is present and not `true` (so "yes"
    or `null` counts as a refusal): a verdict that is missing, repeated or lacks both is not. A group refused only
    because its rewording is not `faithful` is not a refusal to remember: the next run rewords it again."""
    items = verdict_data.get("verdicts") if isinstance(verdict_data, dict) else None
    if not isinstance(items, list):
        return False
    found = [
        v
        for v in items
        if isinstance(v, dict) and v.get("group") == n and not isinstance(v.get("group"), bool)
    ]
    return len(found) == 1 and any(
        k in found[0] and found[0][k] is not True for k in ("same", "general")
    )


def has_verdict(verdict_data: object, n: int) -> bool:
    items = verdict_data.get("verdicts") if isinstance(verdict_data, dict) else None
    return isinstance(items, list) and any(
        isinstance(v, dict) and v.get("group") == n and not isinstance(v.get("group"), bool)
        for v in items
    )


def _blank_line() -> dict:
    return {
        "t": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "lessons": 0,
        "groups": 0,
        "proposed": 0,
        "verified": 0,
        "dropped": 0,
        "written": 0,
        "sightings": 0,
        "links": 0,
        "merges": 0,
        "refused": 0,
        "failed_actions": 0,
        "cases": 0,
        "skipped": None,
        "cost": 0.0,
        "tokens": 0,
        "runner": "claude",
        "failed": None,
        "ms": 0,
    }


@dataclass
class _Run:
    """What the phases of one `execute` share: its inputs, the log line it builds and the run folder it logs to."""

    claude: str  # "" when there is none
    budget: float
    groups_file: str | None
    dry_run: bool
    out_file: str | None
    data: Path
    cdir: Path
    scratch: Path | None  # a dry run's folder, in place of a run folder
    line: dict = field(default_factory=_blank_line)
    spend: Spend = field(default_factory=Spend)
    start: float = field(default_factory=time.time)
    run: Path | None = None
    logged: bool = False

    def finish_log(self) -> None:
        if self.dry_run:
            return
        self.line["ms"] = int((time.time() - self.start) * 1000)
        corroborate_state.append_log(self.cdir, self.line)
        self.logged = True

    def log(self, text: str) -> None:
        if self.run is None:
            return
        fd = os.open(self.run / "log.txt", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")


@dataclass
class _World:
    """Where the lessons come from."""

    registry: dict
    gfolder: Path | None
    today: datetime.date

    def collect(self) -> list:
        return corroborate_decide.collect(
            corroborate_decide.counted_projects(self.registry), self.gfolder, self.today
        )


@dataclass
class _Judged:
    """What the sessions (or a reviewed groups file) decided about the lessons."""

    proposal: object
    proposed: list
    reasons: list[str]
    kept: list
    vreasons: list[str]
    verdict_data: object = None
    incomplete: bool = (
        False  # a session left no usable file: nothing is saved, so the next run asks again
    )
    refused: set[str] = field(
        default_factory=set
    )  # ids of the groups the verifying session refused


def _make_run_folder(cdir: Path) -> Path:
    run = cdir / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    jobs.private_dir(run)
    return run


def _read_world(data: Path) -> _World:
    try:
        registry = records.read_registry(data)
    except ValueError as exc:
        raise StopError("registry unreadable", f"registry: {exc}") from exc
    return _World(registry, records.global_memories_root(os.environ), datetime.date.today())


def _skip_reason(ctx: _Run, seen: dict, lessons: list, before: str) -> str | None:
    if not lessons:
        return "no lessons"
    if not (ctx.groups_file or ctx.dry_run) and seen.get("fingerprint") == before:
        return "nothing new"
    return None


def _start_run(ctx: _Run) -> Path:
    """The folder this run writes to: a dry run's scratch folder, else a new run folder (and a `running` status)."""
    if ctx.scratch is not None:
        return ctx.scratch
    ctx.run = _make_run_folder(ctx.cdir)
    corroborate_state.save_status(
        ctx.cdir, state="running", started=time.time(), finished=None, log=str(ctx.run)
    )
    return ctx.run


def _run_checked(ctx: _Run, work: Path, brief: str, model: str, stage: str) -> None:
    """One session of a stage ("propose" or "verify"): its cost goes to the line, a failed one stops the run."""
    doing = {"propose": "proposing", "verify": "verifying"}[stage]
    if ctx.spend.spent_up:
        raise StopError(
            "token cap",
            f"the {doing} session did not start: {ctx.spend.tokens} tokens reached the cap",
        )
    limits = SessionLimits(model, ctx.budget)
    done = run_on(
        ctx.spend,
        work,
        session_spec(ctx.claude, work, brief, work.parent / "settings.json", limits),
    )
    ctx.line["cost"] += done["cost"] if done["has_result"] else 0.0
    ctx.line["tokens"] = ctx.spend.tokens
    spent = (
        f"tokens={done['tokens']}" if ctx.spend.runner == "codex" else f"cost={done['cost']:.3f}"
    )
    ctx.log(f"{stage}: has_result={done['has_result']} error={done['error']} {spent}")
    if not done["has_result"] or done["error"]:
        no_result = (
            "ended without a result"
            if ctx.spend.runner == "codex"
            else "ended without a cost report"
        )
        raise StopError(
            "session error",
            (
                f"the {doing} session {no_result}"
                if not done["has_result"]
                else f"the {doing} session failed"
            )
            + codex_pass.reason(done),
        )


def _propose(ctx: _Run, root: Path) -> object:
    work = root / "propose"
    work.mkdir(mode=0o700)
    corroborate_state.write_private(
        work / "lessons.txt", (root / "lessons.txt").read_text(encoding="utf-8")
    )
    out = work / "groups.json"
    brief = PROPOSE_BRIEF.format(lessons=work / "lessons.txt", out=out)
    _run_checked(ctx, work, brief, PROPOSE_MODEL, "propose")
    return read_object(out)


def _verify(ctx: _Run, root: Path, judged: _Judged, by_id: dict) -> None:
    """The verifying session over the proposed groups: sets what was kept and why the rest was not."""
    work = root / "verify"
    work.mkdir(mode=0o700)
    lines = corroborate_decide.verification_lines(judged.proposed, by_id)
    corroborate_state.write_private(work / "groups.txt", "".join(f"{ln}\n" for ln in lines))
    out = work / "verdicts.json"
    brief = VERIFY_BRIEF.format(groups=work / "groups.txt", out=out)
    _run_checked(ctx, work, brief, VERIFY_MODEL, "verify")
    data = read_object(out)
    judged.verdict_data = data
    judged.incomplete = judged.incomplete or not (
        isinstance(data, dict) and isinstance(data.get("verdicts"), list)
    )
    judged.kept, judged.vreasons = corroborate_decide.validate_verdicts(data, judged.proposed)


def _judge_file(groups_file: str, lessons: list) -> _Judged:
    """A reviewed groups file: no sessions, every valid group is kept."""
    proposal = read_object(Path(groups_file).expanduser())
    proposed, reasons = corroborate_decide.validate_groups(proposal, lessons)
    return _Judged(proposal, proposed, reasons, list(proposed), [])


def _judge_sessions(
    ctx: _Run, root: Path, lessons: list, by_id: dict, refused_seen: dict
) -> _Judged:
    if ctx.spend.runner == "claude" and not ctx.claude:
        raise StopError("no claude", "no claude binary (--claude, CLAUDE_CODE_EXECPATH or PATH)")
    if missing := missing_codex(ctx.spend):
        raise StopError("no codex", missing)
    corroborate_state.write_private(root / "settings.json", json.dumps({"disableAllHooks": True}))
    proposal = _propose(ctx, root)
    incomplete = not (isinstance(proposal, dict) and isinstance(proposal.get("groups"), list))
    proposed, reasons = corroborate_decide.validate_groups(proposal, lessons)
    # a refused group waits until one of its lessons changes (a sighting, a new wording): all marks must still hold
    proposed = [
        g
        for g in proposed
        if not all(
            refused_seen.get(stable_key(by_id[i]))
            == corroborate_decide.lesson_fingerprint(by_id[i])
            for i in g.ids
        )
    ]
    judged = _Judged(proposal, proposed, reasons, [], [], None, incomplete)
    if proposed:
        _verify(ctx, root, judged, by_id)
    return judged


def _count_judgement(ctx: _Run, judged: _Judged) -> None:
    """Put the counts of the sessions on the line, log what was not applied and note what the verifier refused."""
    proposed, kept = judged.proposed, judged.kept
    raw_groups = judged.proposal.get("groups") if isinstance(judged.proposal, dict) else None
    ctx.line["groups"] = len(raw_groups) if isinstance(raw_groups, list) else 0
    ctx.line["proposed"], ctx.line["verified"], ctx.line["dropped"] = (
        len(proposed),
        len(kept),
        len(judged.reasons),
    )
    # a proposed group the verifying session did not answer is neither applied nor marked: ask again
    judged.incomplete = judged.incomplete or any(
        g not in kept and not has_verdict(judged.verdict_data, n)
        for n, g in enumerate(proposed, start=1)
        if not ctx.groups_file
    )
    if judged.incomplete:  # no usable answer from a session counts as dropped, even where the validator says it per group
        ctx.line["dropped"] += len(judged.vreasons)
    for why in [*judged.reasons, *judged.vreasons]:
        ctx.log(f"not applied: {why}")
    judged.refused = {
        i
        for n, g in enumerate(proposed, start=1)
        if g not in kept and refused_by_verdict(judged.verdict_data, n)
        for i in g.ids
    }


def _write_plan(ctx: _Run, judged: _Judged, by_id: dict) -> None:
    """A dry run's only output: the proposal, the verdicts and the planned actions."""
    if ctx.out_file is None:
        raise TypeError("a dry run needs an output file")
    plan = [
        {"ids": g.ids, "claim": g.claim, "actions": planned(corroborate_decide.actions(g, by_id))}
        for g in judged.kept
    ]
    report = {
        "proposal": judged.proposal,
        "dropped": judged.reasons,
        "verdicts": judged.verdict_data,
        "not_verified": judged.vreasons,
        "plan": plan,
    }
    corroborate_state.write_private(
        Path(ctx.out_file), json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    )


def _apply_groups(ctx: _Run, judged: _Judged, by_id: dict, root: Path, world: _World) -> set[str]:
    """Apply the kept groups, one at a time; a group that raises counts as a failed action. The counts go to the
    line. The ids to mark as refused: the verifier's and the applier's, less those of a group that failed."""
    applier = Applier(corroborate_state.Journal(root), by_id, world.gfolder, root, ctx.log)
    failed_ids: set[str] = set()
    for g in judged.kept:
        applier.current = g
        failed_before = applier.counts["failed_actions"]
        try:
            applier.apply(g, corroborate_decide.actions(g, by_id))
        except Exception as exc:  # one odd group never stops the others
            logger.debug("a group failed", exc_info=True)
            ctx.log(f"group failed: {type(exc).__name__}: {exc}")
            applier.fail()
        if applier.counts["failed_actions"] > failed_before:
            failed_ids.update(g.ids)
    for key in ("written", "sightings", "links", "merges", "refused", "failed_actions", "cases"):
        ctx.line[key] = applier.counts[key]
    return (judged.refused | applier.refused_ids) - failed_ids


def _refusal_marks(
    world: _World, by_id: dict, refused_seen: dict, ids: set[str]
) -> tuple[dict, set[str]]:
    """The marks the next run keeps: the fingerprints the lessons have now, after this run's own writes (a merge
    changes the kept record); the marks this run added."""
    after = {stable_key(x): corroborate_decide.lesson_fingerprint(x) for x in world.collect()}
    marked = {stable_key(by_id[i]) for i in ids}
    marks = {k: v for k, v in refused_seen.items() if isinstance(v, str) and k in after}
    marks.update({k: after[k] for k in marked if k in after})
    return marks, marked


def _retries_so_far(seen: dict, before: str) -> int:
    old = seen.get("retry")
    if (
        isinstance(old, dict)
        and old.get("fingerprint") == before
        and isinstance(old.get("count"), int)
    ):
        return old["count"]
    return 0


def _retry_entry(world: _World, seen: dict, before: str) -> tuple[dict, bool]:
    """A run with a failed action or an unusable answer saves no fingerprint, so the next run tries again, but only
    MAX_RETRIES times on the same lessons; then it gives up (the fingerprint is saved) and says so."""
    count = _retries_so_far(seen, before) + 1
    now = corroborate_decide.fingerprint(
        world.collect()
    )  # after this run's writes: what the next run starts from
    if count >= MAX_RETRIES:
        return {"fingerprint": now}, True
    return {"retry": {"fingerprint": now, "count": count}}, False


def _next_state(
    ctx: _Run, world: _World, seen: dict, before: str, incomplete: bool
) -> tuple[dict, bool]:
    """The fingerprint or retry entry for `seen.json`, and whether the run gives up on these lessons."""
    failing = ctx.line["failed_actions"] or incomplete
    if failing and not ctx.groups_file:
        return _retry_entry(world, seen, before)
    state: dict = {}
    if failing:
        if isinstance(
            seen.get("retry"), dict
        ):  # a reviewed file starts no session and leaves the bound alone
            state["retry"] = seen["retry"]
    elif (
        not ctx.groups_file
    ):  # a reviewed file never tells the model's pass that the lessons were seen
        state["fingerprint"] = corroborate_decide.fingerprint(world.collect())
    elif "fingerprint" in seen:
        state["fingerprint"] = seen["fingerprint"]
    return state, False


def _resolve_runner(ctx: _Run) -> None:
    """After the lock (the run folder of a failure needs it); a malformed setting fails the run naming its source."""
    try:
        ctx.spend.runner = ctx.line["runner"] = runners.resolve_runner(None)
    except ValueError as exc:
        raise StopError("runner setting", str(exc)) from exc


def _run_pass(ctx: _Run) -> dict:
    _resolve_runner(ctx)  # once per run, before any early stop
    seen = jobs.read_json(ctx.cdir / "seen.json")
    refused_seen = seen["refused"] if isinstance(seen.get("refused"), dict) else {}
    world = _read_world(ctx.data)
    lessons = world.collect()
    before = corroborate_decide.fingerprint(
        lessons
    )  # compared with the retry a failed run stored (its lessons after its writes)
    ctx.line["lessons"] = len(lessons)
    ctx.line["skipped"] = _skip_reason(ctx, seen, lessons, before)
    if ctx.line["skipped"]:
        ctx.finish_log()
        return ctx.line
    root = _start_run(ctx)  # only a run that works gets a folder and a status
    by_id = {x.id: x for x in lessons}
    corroborate_state.write_private(
        root / "lessons.txt", "".join(f"{ln}\n" for ln in corroborate_decide.lesson_lines(lessons))
    )
    judged = (
        _judge_file(ctx.groups_file, lessons)
        if ctx.groups_file
        else _judge_sessions(ctx, root, lessons, by_id, refused_seen)
    )
    _count_judgement(ctx, judged)
    if ctx.dry_run:
        _write_plan(ctx, judged, by_id)
        return ctx.line
    refused_ids = _apply_groups(ctx, judged, by_id, root, world)
    marks, marked = _refusal_marks(world, by_id, refused_seen, refused_ids)
    state, gave_up = _next_state(ctx, world, seen, before, judged.incomplete)
    corroborate_state.write_private(
        root / "seen-added.json", json.dumps({"marked": sorted(marked)})
    )
    jobs.write_json(ctx.cdir / "seen.json", {"refused": marks, **state})
    if gave_up:
        raise StopError(
            "gave up after repeated failures",
            f"gave up: {MAX_RETRIES} runs in a row on these lessons ended "
            "with a failed action or an unusable answer; the run folders hold the details",
        )
    save_done(ctx.cdir, ctx.line, None, ctx.dry_run)
    ctx.finish_log()
    return ctx.line


def _record_failure(ctx: _Run, reason: str, locked: bool) -> None:
    """The details of a failure go to the run folder (made now when the failure came first) and the status."""
    if ctx.run is None and locked:  # the details of a failure need a private place
        ctx.run = _make_run_folder(ctx.cdir)
    ctx.log(f"failed: {reason}")
    save_done(
        ctx.cdir, ctx.line, ctx.line["failed"], ctx.dry_run, log=str(ctx.run) if ctx.run else ""
    )
    if not ctx.logged:
        ctx.finish_log()


def _report_failure(ctx: _Run, exc: Exception, locked: bool) -> None:
    """A background process reports and ends: the reason goes to the line (a dry run) or to the run's files."""
    reason = str(exc) if isinstance(exc, StopError) else f"{type(exc).__name__}: {exc}"
    ctx.line["failed"] = exc.short if isinstance(exc, StopError) else type(exc).__name__
    if ctx.dry_run:
        ctx.line["failed_reason"] = reason
        return
    try:
        _record_failure(ctx, reason, locked)
    except Exception:  # the failure itself is already on the line
        logger.debug("could not record the failure", exc_info=True)


def _release(ctx: _Run, lock: int | None) -> None:
    """Prune the old run folders, release the run lock and drop a dry run's scratch folder."""
    if lock is not None and (
        ctx.run is not None or (ctx.cdir / "runs").is_dir()
    ):  # a skipped run prunes too
        try:
            cs.prune_runs(ctx.cdir / "runs", cs.KEEP_RUNS, cs.KEEP_RUN_DAYS, time.time())
        except Exception:  # pruning is housekeeping
            logger.debug("could not prune the run folders", exc_info=True)
    if lock is not None:
        os.close(lock)
    if ctx.scratch is not None:
        shutil.rmtree(ctx.scratch, ignore_errors=True)


def execute(
    claude: str | None,
    budget: float,
    groups_file: str | None = None,
    dry_run: bool = False,
    out_file: str | None = None,
) -> dict:
    """One run. The log line (counts only); a dry run writes nothing but `out_file`. The runner is the configured
    one (`runner.resolve_runner`)."""
    data = corroborate_state.data_dir()
    scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-")) if dry_run else None
    ctx = _Run(
        claude or "",
        budget,
        groups_file,
        dry_run,
        out_file,
        data,
        corroborate_state.corroborate_dir(data),
        scratch,
    )
    lock = None
    try:
        if not dry_run:
            lock = jobs.take_run_lock(ctx.cdir)
            if lock is None:
                ctx.line["skipped"] = "another run holds the lock"
                ctx.finish_log()
                return ctx.line
        return _run_pass(ctx)
    except Exception as exc:  # a background process reports and ends
        logger.debug("the run failed", exc_info=True)
        _report_failure(ctx, exc, lock is not None)
        return ctx.line
    finally:
        _release(ctx, lock)


def save_done(cdir: Path, line: dict, failure: str | None, dry_run: bool, log: str = "") -> None:
    """A failure line stays in the status until `ack`: a later successful run does not clear it."""
    if dry_run:
        return
    now = time.time()
    end: dict = {
        "state": "failed" if failure else "ok",
        "finished": now,
        "cost": line["cost"],
        "tokens": line["tokens"],
        "runner": line["runner"],
    }
    if log:
        end["log"] = log
    if failure:
        end["failure"] = {"at": now, "reason": failure[:300], "log": log}
    corroborate_state.save_status(cdir, **end)


def repo_above(folder: Path) -> Path | None:
    """The nearest folder, `folder` or an ancestor, that holds an entry named `.git` (as `mem-capture run --out`)."""
    for p in (folder, *folder.parents):
        if os.path.lexists(p / ".git"):
            return p
    return None


def _fill_world():
    """(data folder, registry, counted projects, global folder, project name of each path)."""
    data = corroborate_state.data_dir()
    registry = records.read_registry(data)
    projects = corroborate_decide.counted_projects(registry)
    names: dict[Path, str] = {}
    for name in sorted(registry):
        entry = registry[name]
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            names.setdefault(Path(entry["path"]), name)
    return data, projects, records.global_memories_root(os.environ), names


def _cell(text: object) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


def _ask(
    claude: str,
    scratch: Path,
    name: str,
    limits: SessionLimits,
    job: AskJob,
) -> tuple[object, float, bool]:
    """One session in its own folder: (the JSON it wrote or None, its cost, whether it ended with a result and no error).
    Callers pass `claude`, `scratch` and `name` positionally (`name` stays third: a test wraps the call). `job.spend`:
    the run's runner and Codex tokens (the configured runner when None); a session that would start past the token
    cap does not start and counts as failed."""
    template, text, text_key, out_name, spend = job
    spend = spend or Spend(runners.resolve_runner(None))
    if spend.spent_up:
        return None, 0.0, False
    work = scratch / name
    work.mkdir(mode=0o700)
    corroborate_state.write_private(work / "input.txt", text)
    out = work / out_name
    brief = template.format(**{text_key: work / "input.txt"}, out=out)
    try:
        done = run_on(
            spend, work, session_spec(claude, work, brief, scratch / "settings.json", limits)
        )
    except OSError:  # a binary that is missing or cannot run is a failed session
        return None, 0.0, False
    cost = done["cost"] if done["has_result"] else 0.0
    ok = done["has_result"] and not done["error"]
    return (read_object(out) if ok else None), cost, ok
