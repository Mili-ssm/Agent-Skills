"""mem-corroborate: the model sessions, the briefs, the applier and `execute` (one run); what the three jobs share."""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import auto_state as au
import capture_state as cs
import corroborate
import corroborate_state
import records
import research_pipeline as rp
import synth_pipeline as sp


PROPOSE_MODEL = VERIFY_MODEL = "haiku"


CHECK_MODEL = "haiku"   # the second session of the automatic fill; chosen by the gate of 2026-11-22 (the plan's Results)


SESSION_TIMEOUT = 600


MAX_FILE_BYTES = 1_000_000


# Not resolved: `fake_plugin` in the tests links `engine/`, and a resolved path would reach the real `bin/mem`.
MEM = Path(__file__).parent.parent / "bin" / "mem"


MEM_TIMEOUT = 60


SETTLE_STATE = ".settle-state.json"   # beside the global records; `settle.STATE_NAME`


SESSION_VARS = ("CLAUDE_ENV_FILE", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "CLAUDE_PROJECT_DIR", "CLAUDE_PID",
                "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN")


SETTLE_VARS = ("MEM_SETTLE_AUTO", "MEM_SETTLE_MINUTES", "MEM_SETTLE_CLAUDE")   # `settle_state.maybe_start` starts a run from these


ANSWERS = ("same", "faithful", "general")


MAX_RETRIES = 2   # runs that end with a failed action or an unusable answer on the same lessons before the run gives up


REFUSED_MEM_EXITS = {"remember": (4, 5)}   # a `mem merge` refuses with any non-zero exit; any other exit is a failure


class Stop(Exception):
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


def session_cmd(claude: str, work: Path, brief: str, settings: Path, model: str, max_budget: float) -> list[str]:
    """One session. Only Read and Write exist (`--tools`, no MCP server) and the rules allow them inside `work`
    only; no Bash, no web, hooks disabled by `settings`."""
    return [claude, "-p", brief, "--model", model, "--effort", "medium", "--settings", str(settings),
            "--setting-sources", "project", "--tools", "Read,Write", "--strict-mcp-config",
            "--allowedTools", f"Read(/{work}/**)", f"Write(/{work}/**)", f"Edit(/{work}/**)",
            "--disallowedTools", "Bash", "WebSearch", "WebFetch",
            "--output-format", "stream-json", "--verbose", "--no-session-persistence",
            "--max-budget-usd", f"{max_budget:.4f}"]


def run_session(cmd: list[str], work: Path) -> dict:
    try:
        done = subprocess.run(cmd, cwd=work, env=rp.session_env(), stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, errors="replace", timeout=SESSION_TIMEOUT)
        raw = done.stdout
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    return sp.parse(raw)


def read_object(path: Path) -> object:
    """The JSON of `path`, or None when it is missing, too large or not JSON (the validators then say why)."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Applier:
    """Applies the kept groups through `bin/mem`; the counts of what happened are in `counts`.

    A refusal (exit 4 or 5 of `remember`, a non-zero `merge`) is counted and marked so the group is not tried again.
    Any other result of a `mem` call (an undocumented exit code, a timeout, no process) is a failure: it stops the
    group, marks nothing and keeps the run from saving its fingerprint, so the next run tries again."""

    def __init__(self, journal: corroborate_state.Journal, lessons: dict, gfolder: Path | None, cwd: Path, log):
        self.journal, self.lessons, self.gfolder, self.cwd, self.log = journal, lessons, gfolder, cwd, log
        self.counts = {"written": 0, "sightings": 0, "links": 0, "merges": 0, "refused": 0, "failed_actions": 0,
                       "cases": 0}
        self.refused_ids: set[str] = set()
        self.current = None

    def mem(self, args: list[str], project: Path | None = None, stdin: str | None = None, drop_env: tuple = ()):
        env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS and k not in drop_env and k != "MEM_PROJECT"}
        if project is not None:
            env["MEM_PROJECT"] = str(project)
        try:
            done = subprocess.run([str(MEM), *args], env=env, cwd=self.cwd, input=stdin, capture_output=True,
                                  text=True, errors="replace", timeout=MEM_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.log(f"mem {args[0]}: could not run ({type(exc).__name__})")
            return None
        self.log(f"mem {args[0]}: exit {done.returncode} {done.stdout.strip()[:120]!r} {done.stderr.strip()[:200]!r}")
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
            done = self.mem(["confirm", target, "--global", f"--source={entry}", f"--outcome={c.outcome}",
                             f"--seen-on={c.on.isoformat()}"])
            if done is None or done.returncode not in (0, 3):
                return False
            self.counts["cases"] += done.returncode == 0
        return True

    def sight(self, target: str, entry: str, cases: list[str]):
        """The sighting of `entry`: its first case rides on the first call, so no `seen` entry is logged for it. The
        result of that call, and whether the cases after it went well (None when the call itself did not work)."""
        parsed = [c for c in map(records.case, cases) if c]
        extra = [f"--outcome={parsed[0].outcome}", f"--seen-on={parsed[0].on.isoformat()}"] if parsed else []
        done = self.mem(["confirm", target, "--global", f"--source={entry}", *extra])
        if done is None or done.returncode not in (0, 3):
            return done, None
        if parsed and done.returncode == 0:
            self.counts["cases"] += 1
        return done, self.add_cases(target, [entry], cases[1:] if parsed else cases)

    def path(self, lesson_id: str) -> Path:
        return self.lessons[lesson_id].memory.path

    def apply(self, group, acts) -> bool:
        """Every action of one group, in order; False when one was refused or failed and the rest was left."""
        written: str | None = None   # the global record that this group's write_global made or found
        for a in acts:
            if a.kind in ("merge", "merge_global"):
                args = ["merge"] + (["--global"] if a.kind == "merge_global" else []) + [self.handle(a.keep), self.handle(a.drop)]
                before = self.journal.watch([self.path(a.keep), self.path(a.drop)])
                done = self.mem(args, a.project)
                self.journal.commit(a.kind, before)
                if done is None:
                    return self.fail()
                if done.returncode:
                    return self.refuse()   # left for curation, never forced
                self.counts["merges"] += 1
            elif a.kind == "write_global":
                args = ["remember", "--global", f"--kind={a.record_kind}", f"--claim={a.claim}"]
                if a.context:
                    args.append(f"--context={a.context}")
                args += ["--origin", "transcript", "--reach", "general", "--weight", a.weight]
                args += [f"--source={e}" for e in a.entries] + ["--body-file", "-"]
                # no counts here: the record is not rewritten when a sighting arrives, so a figure would go stale
                body = "Written by the corroboration pass; its sightings are the sessions and projects in `sources`.\n"
                before = self.journal.watch_folder(self.gfolder) if self.gfolder else {}
                done = self.mem(args, stdin=body)
                first = done.stdout.strip().splitlines()[0].split("\t") if done and done.stdout.strip() else []
                cases_ok = True
                if done is not None and done.returncode in (0, 3) and first and first[0].startswith("m:"):
                    cases_ok = self.add_cases(first[0], a.entries, a.cases)
                self.journal.commit("write_global", before, self.gfolder)
                if not cases_ok and done is not None and done.returncode == 0 and first and first[0].startswith("m:"):
                    self.counts["written"] += 1   # the record exists, though a case call failed
                if done is None or not cases_ok:
                    return self.fail()
                if done.returncode == 0 and first and first[0].startswith("m:"):
                    written = first[0]
                    self.counts["written"] += 1
                elif done.returncode == 3 and len(first) == 2 and first[0].startswith("m:"):
                    written = first[0]   # the claim exists: its sightings were added by `remember`
                    self.counts["sightings"] += first[1] == "sighting"
                elif done.returncode in REFUSED_MEM_EXITS["remember"]:
                    return self.refuse()
                else:
                    return self.fail()
            elif a.kind == "sighting":
                target = a.target and f"m:{a.target}" or written
                if not target or not self.gfolder:
                    return self.refuse()
                path = self.gfolder / f"{target[2:]}.md"
                before = self.journal.watch([path])
                done, cases_ok = self.sight(target, a.entry, a.cases)
                self.journal.commit("sighting", before)
                if done is not None and done.returncode == 0:
                    self.counts["sightings"] += 1
                if cases_ok is False:
                    return self.fail()
                if done is None or done.returncode not in (0, 3):
                    return self.fail()
            elif a.kind == "cases":
                if not a.target or not self.gfolder:
                    return self.refuse()
                before = self.journal.watch([self.gfolder / f"{a.target}.md"])
                cases_ok = self.add_cases(f"m:{a.target}", [a.entry], a.cases)
                self.journal.commit("cases", before)
                if not cases_ok:
                    return self.fail()
            elif a.kind == "link":
                target = a.target and f"m:{a.target}" or written
                if not target:
                    return self.refuse()
                before = self.journal.watch([self.path(a.member)])
                done = self.mem(["promote", "--done", self.handle(a.member), "--to", target], a.project)
                self.journal.commit("link", before)
                if done is not None and done.returncode == 0:
                    self.counts["links"] += 1
                else:
                    return self.fail()
        return True

    def refuse(self) -> bool:
        self.counts["refused"] += 1
        self.refused_ids.update(self.current.ids)
        return False

    def fail(self) -> bool:
        self.counts["failed_actions"] += 1
        return False


def stable_key(lesson) -> str:
    """The name of a lesson that does not change between runs (the ids of a lessons file depend on the registry)."""
    return corroborate.fill_key(lesson.project, lesson.memory.handle)


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
    found = [v for v in items if isinstance(v, dict) and v.get("group") == n and not isinstance(v.get("group"), bool)]
    return len(found) == 1 and any(k in found[0] and found[0][k] is not True for k in ("same", "general"))


def has_verdict(verdict_data: object, n: int) -> bool:
    items = verdict_data.get("verdicts") if isinstance(verdict_data, dict) else None
    return isinstance(items, list) and any(isinstance(v, dict) and v.get("group") == n
                                           and not isinstance(v.get("group"), bool) for v in items)


def execute(claude: str | None, budget: float, groups_file: str | None = None, dry_run: bool = False,
            out_file: str | None = None) -> dict:
    """One run. The log line (counts only); a dry run writes nothing but `out_file`."""
    start = time.time()
    data = corroborate_state.data_dir()
    cdir = corroborate_state.corroborate_dir(data)
    line: dict = {"t": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "lessons": 0,
                  "groups": 0, "proposed": 0, "verified": 0, "dropped": 0, "written": 0, "sightings": 0, "links": 0,
                  "merges": 0, "refused": 0, "failed_actions": 0, "cases": 0, "skipped": None, "cost": 0.0, "failed": None, "ms": 0}
    lock = None
    logged: list[bool] = []
    run: Path | None = None

    def finish_log() -> None:
        if dry_run:
            return
        line["ms"] = int((time.time() - start) * 1000)
        corroborate_state.append_log(cdir, line)
        logged.append(True)

    def log(text: str) -> None:
        if run is None:
            return
        fd = os.open(run / "log.txt", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    scratch = Path(tempfile.mkdtemp(prefix="mem-corroborate-")) if dry_run else None
    try:
        if not dry_run:
            lock = au.take_run_lock(cdir)
            if lock is None:
                line["skipped"] = "another run holds the lock"
                finish_log()
                return line
        seen = au.read_json(cdir / "seen.json")
        refused_seen = seen.get("refused") if isinstance(seen.get("refused"), dict) else {}
        try:
            registry = records.read_registry(data)
        except ValueError as exc:
            raise Stop("registry unreadable", f"registry: {exc}") from exc
        gfolder = records.global_memories_root(os.environ)
        today = datetime.date.today()

        def collect() -> list:
            return corroborate.collect(corroborate.counted_projects(registry), gfolder, today)

        lessons = collect()
        before = corroborate.fingerprint(lessons)   # compared with the retry a failed run stored (its lessons after its writes)
        line["lessons"] = len(lessons)
        if not lessons:
            line["skipped"] = "no lessons"
        elif not (groups_file or dry_run) and seen.get("fingerprint") == corroborate.fingerprint(lessons):
            line["skipped"] = "nothing new"
        if line["skipped"]:
            finish_log()
            return line
        if not dry_run:   # only a run that works gets a folder and a status
            run = cdir / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
            au.private_dir(run)
            corroborate_state.save_status(cdir, state="running", started=time.time(), finished=None, log=str(run))
        root = run if run is not None else scratch
        by_id = {x.id: x for x in lessons}
        corroborate_state.write_private(root / "lessons.txt", "".join(f"{ln}\n" for ln in corroborate.lesson_lines(lessons)))
        verdict_data: object = None
        proposal: object = None
        incomplete = False   # a session left no usable file: nothing is saved, so the next run asks again
        if groups_file:
            proposal = read_object(Path(groups_file).expanduser())
            proposed, reasons = corroborate.validate_groups(proposal, lessons)
            kept, vreasons = list(proposed), []   # a reviewed file: no verifying session
        else:
            if not claude:
                raise Stop("no claude", "no claude binary (--claude, CLAUDE_CODE_EXECPATH or PATH)")
            settings = root / "settings.json"
            corroborate_state.write_private(settings, json.dumps({"disableAllHooks": True}))
            work1 = root / "propose"
            work1.mkdir(mode=0o700)
            corroborate_state.write_private(work1 / "lessons.txt", (root / "lessons.txt").read_text(encoding="utf-8"))
            out1 = work1 / "groups.json"
            brief = PROPOSE_BRIEF.format(lessons=work1 / "lessons.txt", out=out1)
            done = run_session(session_cmd(claude, work1, brief, settings, PROPOSE_MODEL, budget), work1)
            line["cost"] += done["cost"] if done["has_result"] else 0.0
            log(f"propose: has_result={done['has_result']} error={done['error']} cost={done['cost']:.3f}")
            if not done["has_result"] or done["error"]:
                raise Stop("session error", "the proposing session ended without a cost report" if not done["has_result"]
                           else "the proposing session failed")
            proposal = read_object(out1)
            incomplete = not (isinstance(proposal, dict) and isinstance(proposal.get("groups"), list))
            proposed, reasons = corroborate.validate_groups(proposal, lessons)
            # a refused group waits until one of its lessons changes (a sighting, a new wording): all marks must still hold
            proposed = [g for g in proposed if not all(refused_seen.get(stable_key(by_id[i])) == corroborate.lesson_fingerprint(by_id[i])
                                                       for i in g.ids)]
            kept, vreasons = [], []
            if proposed:
                work2 = root / "verify"
                work2.mkdir(mode=0o700)
                corroborate_state.write_private(work2 / "groups.txt", "".join(f"{ln}\n" for ln in corroborate.verification_lines(proposed, by_id)))
                out2 = work2 / "verdicts.json"
                brief = VERIFY_BRIEF.format(groups=work2 / "groups.txt", out=out2)
                done = run_session(session_cmd(claude, work2, brief, settings, VERIFY_MODEL, budget), work2)
                line["cost"] += done["cost"] if done["has_result"] else 0.0
                log(f"verify: has_result={done['has_result']} error={done['error']} cost={done['cost']:.3f}")
                if not done["has_result"] or done["error"]:
                    raise Stop("session error", "the verifying session ended without a cost report" if not done["has_result"]
                               else "the verifying session failed")
                verdict_data = read_object(out2)
                incomplete = incomplete or not (isinstance(verdict_data, dict) and isinstance(verdict_data.get("verdicts"), list))
                kept, vreasons = corroborate.validate_verdicts(verdict_data, proposed)
        raw_groups = proposal.get("groups") if isinstance(proposal, dict) else None
        line["groups"] = len(raw_groups) if isinstance(raw_groups, list) else 0
        line["proposed"], line["verified"], line["dropped"] = len(proposed), len(kept), len(reasons)
        # a proposed group the verifying session did not answer is neither applied nor marked: ask again
        incomplete = incomplete or any(g not in kept and not has_verdict(verdict_data, n)
                                       for n, g in enumerate(proposed, start=1) if not groups_file)
        if incomplete:   # no usable answer from a session counts as dropped, even where the validator says it per group
            line["dropped"] += len(vreasons)
        for why in [*reasons, *vreasons]:
            log(f"not applied: {why}")
        refused_now = {i for n, g in enumerate(proposed, start=1) if g not in kept and refused_by_verdict(verdict_data, n)
                       for i in g.ids}
        if dry_run:
            plan = [{"ids": g.ids, "claim": g.claim, "actions": planned(corroborate.actions(g, by_id))} for g in kept]
            corroborate_state.write_private(Path(out_file), json.dumps({"proposal": proposal, "dropped": reasons, "verdicts": verdict_data,
                                                      "not_verified": vreasons, "plan": plan}, ensure_ascii=False, indent=1) + "\n")
            return line
        applier = Applier(corroborate_state.Journal(run), by_id, gfolder, run, log)
        failed_ids: set[str] = set()
        for g in kept:
            applier.current = g
            failed_before = applier.counts["failed_actions"]
            try:
                applier.apply(g, corroborate.actions(g, by_id))
            except Exception as exc:   # noqa: BLE001 - one odd group never stops the others
                log(f"group failed: {type(exc).__name__}: {exc}")
                applier.fail()
            if applier.counts["failed_actions"] > failed_before:
                failed_ids.update(g.ids)
        for key in ("written", "sightings", "links", "merges", "refused", "failed_actions", "cases"):
            line[key] = applier.counts[key]
        # marks are the fingerprints the lessons have now, after this run's own writes (a merge changes the kept record)
        after = {stable_key(x): corroborate.lesson_fingerprint(x) for x in collect()}
        marked = {stable_key(by_id[i]) for i in (refused_now | applier.refused_ids) - failed_ids}
        marks = {k: v for k, v in refused_seen.items() if isinstance(v, str) and k in after}
        marks.update({k: after[k] for k in marked if k in after})
        seen_out: dict = {"refused": marks}
        gave_up = False
        if (line["failed_actions"] or incomplete) and not groups_file:
            # no fingerprint, so the next run tries again, but only MAX_RETRIES times on the same lessons
            old = seen.get("retry") if isinstance(seen.get("retry"), dict) else {}
            count = (old.get("count") if old.get("fingerprint") == before and isinstance(old.get("count"), int) else 0) + 1
            now = corroborate.fingerprint(collect())   # after this run's writes: what the next run starts from
            if count >= MAX_RETRIES:
                gave_up = True
                seen_out["fingerprint"] = now
            else:
                seen_out["retry"] = {"fingerprint": now, "count": count}
        elif line["failed_actions"] or incomplete:
            if isinstance(seen.get("retry"), dict):   # a reviewed file starts no session and leaves the bound alone
                seen_out["retry"] = seen["retry"]
        elif not groups_file:   # a reviewed file never tells the model's pass that the lessons were seen
            seen_out["fingerprint"] = corroborate.fingerprint(collect())
        elif "fingerprint" in seen:
            seen_out["fingerprint"] = seen["fingerprint"]
        corroborate_state.write_private(run / "seen-added.json", json.dumps({"marked": sorted(marked)}))
        au.write_json(cdir / "seen.json", seen_out)
        if gave_up:
            raise Stop("gave up after repeated failures", f"gave up: {MAX_RETRIES} runs in a row on these lessons ended "
                       "with a failed action or an unusable answer; the run folders hold the details")
        save_done(cdir, line, None, dry_run)
        finish_log()
        return line
    except Exception as exc:   # noqa: BLE001 - a background process reports and ends
        reason = str(exc) if isinstance(exc, Stop) else f"{type(exc).__name__}: {exc}"
        line["failed"] = exc.short if isinstance(exc, Stop) else type(exc).__name__
        if not dry_run:
            try:
                if run is None and lock is not None:   # the details of a failure need a private place
                    run = cdir / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
                    au.private_dir(run)
                log(f"failed: {reason}")
                save_done(cdir, line, line["failed"], dry_run, log=str(run) if run else "")
                if not logged:
                    finish_log()
            except Exception:   # noqa: BLE001
                pass
        else:
            line["failed_reason"] = reason
        return line
    finally:
        if lock is not None and (run is not None or (cdir / "runs").is_dir()):   # a skipped run prunes too
            try:
                cs.prune_runs(cdir / "runs", cs.KEEP_RUNS, cs.KEEP_RUN_DAYS, time.time())
            except Exception:   # noqa: BLE001
                pass
        if lock is not None:
            os.close(lock)
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


def save_done(cdir: Path, line: dict, failure: str | None, dry_run: bool, log: str = "") -> None:
    """A failure line stays in the status until `ack`: a later successful run does not clear it."""
    if dry_run:
        return
    now = time.time()
    end: dict = {"state": "failed" if failure else "ok", "finished": now, "cost": line["cost"]}
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
    projects = corroborate.counted_projects(registry)
    names: dict[Path, str] = {}
    for name in sorted(registry):
        entry = registry[name]
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            names.setdefault(Path(entry["path"]), name)
    return data, projects, records.global_memories_root(os.environ), names


def _cell(text: object) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


def _ask(claude: str, scratch: Path, name: str, model: str, budget: float, template: str, text: str,
         text_key: str, out_name: str) -> tuple[object, float, bool]:
    """One session in its own folder: (the JSON it wrote or None, its cost, whether it ended with a result and no error)."""
    work = scratch / name
    work.mkdir(mode=0o700)
    corroborate_state.write_private(work / "input.txt", text)
    out = work / out_name
    brief = template.format(**{text_key: work / "input.txt"}, out=out)
    try:
        done = run_session(session_cmd(claude, work, brief, scratch / "settings.json", model, budget), work)
    except OSError:   # a binary that is missing or cannot run is a failed session
        return None, 0.0, False
    cost = done["cost"] if done["has_result"] else 0.0
    ok = done["has_result"] and not done["error"]
    return (read_object(out) if ok else None), cost, ok
