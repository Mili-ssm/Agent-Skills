"""The lean synthesis pipeline shared by `bin/mem-synthesize` and `evals/synthesis/run_trials.py`.

Lean loop (measured in docs/superpowers/plans/2026-11-17-memory-prompts-and-loop.md): check (one line per unsupported
claim) -> one fixer that changes only the listed sentences -> one check scoped to the parts and sentences the fixer
reports -> when it still lists claims, one delete-only step removes those sentences; no third pass. Every step is its
own `claude -p` session. Standard library only."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
MEM = PLUGIN / "bin" / "mem"
BRIEFS = Path(__file__).resolve().parent / "synth_briefs"
SKILL = PLUGIN / "skills" / "memory-synthesis" / "SKILL.md"
CHEAP = "high"   # effort of every Haiku checker and fixer (owner, 2026-11-17: raised from medium, unmeasured)
NOT_GIVEN = "(not given)"

COUNTS = re.compile(r"^COUNTS: checked=(\d+) unsupported=(\d+)(?: used=(\d+) unused=(\d+))?\s*$", re.M)
NOTE_LINE = re.compile(r"^NOTE: (\S+) (used|unused)\s*$", re.M)
CLAIM_LINE = re.compile(r"^(?P<part>[^|\n]+?) \| (?P<start>[^|\n]*) \| (?P<kind>[^|\n]+?) \| (?P<note>[^|\n]*) \| (?P<fix>.*)$")
PARTS_LINE = re.compile(r"^PARTS: ?(.*)$", re.M)
REF_LINE = re.compile(r"^REF: (?P<part>[^|\n]+?) \| (?P<number>\d+) \| (?:(?P<missing>missing)|wrong (?P<current>[^|\n]+?)) \| "
                      r"(?P<target>[^|\n]*?)\s*$")
REFS_TOTAL = re.compile(r"^s:\S+: added (\d+), removed (\d+), refused (\d+)\s*$", re.M)
DENIED = re.compile(r"requested permissions|haven't granted|permission.{0,40}denied|denied.{0,40}permission", re.I)


DELETE_ONLY = """
## Additional instruction for this step: delete only

This is the last pass. For every claim the report lists, delete that sentence from its part: ignore any replacement
sentence, write no new text, and leave every other character of the part as it is.
"""


def brief(name: str, briefs: Path = BRIEFS, **values: str) -> str:
    text = (briefs / f"{name}-brief.md").read_text()
    values.setdefault("SKILL_FILE", str(SKILL))
    values.setdefault("PARTS", NOT_GIVEN)
    values.setdefault("UNITS_FILE", NOT_GIVEN)
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    left = re.findall(r"\{[A-Z_]+\}", text)
    assert not left, f"{name}-brief.md has unfilled placeholders: {left}"
    return text


def mem(store: Path, env: dict, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(MEM), *args], env={**env, "MEM_STORE": str(store)}, input=stdin, capture_output=True,
                          text=True, cwd=store)


def model_family(model_id: str) -> str:
    return next((f for f in ("haiku", "sonnet", "opus") if f in model_id.lower()), model_id)


def cost_by_family(model_usage: dict) -> dict[str, float]:
    costs: dict[str, float] = {}
    for model, usage in model_usage.items():
        family = model_family(model)
        costs[family] = costs.get(family, 0.0) + float(usage.get("costUSD") or 0.0)
    return costs


def parse(stdout: str) -> dict:
    """Facts of one stream-json session: writes with their exit status, denials, cost per model, result."""
    out = dict(writes=0, write_errors=0, denied=0, tool_errors=0, model_usage={}, cost=0.0, error=True, answer="",
               has_result=False)
    uses: dict[str, tuple[str, str]] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        content = message.get("content")
        if kind == "assistant" and isinstance(content, list):
            for part in content:
                if part.get("type") == "tool_use":
                    uses[part["id"]] = (part["name"], (part.get("input") or {}).get("command", ""))
        elif kind == "user" and isinstance(content, list):
            for part in content:
                if part.get("type") != "tool_result":
                    continue
                name, command = uses.get(part.get("tool_use_id"), ("", ""))
                body = part.get("content")
                text = body if isinstance(body, str) else " ".join(b.get("text", "") for b in body or [])
                failed = bool(part.get("is_error"))
                if failed:
                    out["tool_errors"] += 1
                    if DENIED.search(text):
                        out["denied"] += 1
                if name == "Write" or (name == "Bash" and re.match(r"\s*mem synthesis (new|add|edit|append)\b", command)):
                    out["writes"] += 1
                    out["write_errors"] += failed
        elif kind == "result":
            out["has_result"] = True
            out["answer"] = event.get("result") or ""
            out["model_usage"] = event.get("modelUsage") or {}
            out["cost"] = float(event.get("total_cost_usd") or 0.0)
            out["error"] = bool(event.get("is_error"))
    return out


def run_session(claude: str, model: str, prompt: str, work: Path, settings: Path, env: dict, log: Path,
                timeout: int = 1500, effort: str | None = None, agent: str | None = None,
                max_budget: float | None = None) -> dict:
    cmd = [claude, "-p", prompt, "--model", model, "--plugin-dir", str(PLUGIN), "--settings", str(settings),
           "--setting-sources", "project",
           # Headless --allowedTools also limits what a session may run: exactly what a step needs. Body files go
           # in the work folder (`//` is an absolute path in a permission rule; a new file needs the Edit rule too); the
           # web stays out.
           "--allowedTools", "Bash(mem *)", "Read", "Grep", "Glob",
           f"Write(/{work}/**)", f"Edit(/{work}/**)",
           "--disallowedTools", "WebSearch", "WebFetch",
           "--output-format", "stream-json", "--verbose", "--no-session-persistence"]
    if effort:
        cmd += ["--effort", effort]
    if max_budget is not None:
        cmd += ["--max-budget-usd", f"{max_budget:.4f}"]   # the session stops itself past this spend (--print only)
    if agent:
        cmd += ["--agent", agent]   # the agent's body is the session's system prompt
    start = time.monotonic()
    try:
        done = subprocess.run(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=timeout)
        raw = done.stdout
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    log.write_text(raw)
    result = parse(raw)
    result["wall"] = time.monotonic() - start
    return result


def units_text(synthesis: Path) -> str:
    """What the checker's `{UNITS_FILE}` holds: per part (not the Summary) `## <handle>`, one line per unit
    `<number> | <text without references> | <targets, or ->`, then `Sources: <note targets>`."""
    import syntheses   # lazy: it needs PyYAML, which the rest of this module does not
    lines = []
    for section in syntheses.load_one(synthesis).parts:
        found, _ = syntheses.units(section.text)
        lines.append(f"## {section.handle}")
        lines += [f"{u.n} | {' '.join(u.plain.split())} | {', '.join(u.refs) or '-'}" for u in found]
        lines.append("Sources: " + ", ".join(t for t in section.sources if syntheses._is_ref(t)))
    return "\n".join(lines) + "\n"


def write_units(synthesis: Path, target: Path) -> None:
    target.write_text(units_text(synthesis))


def parse_report(path: Path) -> dict | None:
    """The checker's report: its last COUNTS line, the PARTS line, the claim lines, the `REF:` lines (reference
    problems, never claims; a malformed one is only counted in `ref_malformed`) and the judge's NOTE lines.

    None when the file or the COUNTS line is missing. A report with no unsupported claim holds only the COUNTS line."""
    if not path.is_file():
        return None
    text = path.read_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    found = COUNTS.fullmatch(lines[-1]) if lines else None
    if not found:
        return None
    notes = {}
    for rel, state in NOTE_LINE.findall(text):
        at = rel.find("knowledge/")
        notes[rel[at:] if at >= 0 else rel] = state
    claims = [m.groupdict() for ln in lines if not ln.startswith("REF:") and (m := CLAIM_LINE.match(ln))]
    refs, malformed = [], 0
    for ln in lines:
        if ln.startswith("REF:"):
            m = REF_LINE.match(ln)
            if not m:
                malformed += 1
                continue
            target = m["target"].strip()
            refs.append(dict(part=section_handle(m["part"].strip().removeprefix("s:").split("#")[-1]),
                             number=int(m["number"]), kind="missing" if m["missing"] else "wrong",
                             current=(m["current"] or "").strip() or None,
                             target=None if target in ("", "none") else target))
    listed = PARTS_LINE.search(text)
    # A model may write a heading where the brief asks for a handle: both become the handle `mem` gives the part.
    parts = [section_handle(h.strip().removeprefix("s:").split("#")[-1])
             for h in (listed.group(1) if listed else "").split(",") if h.strip()]
    for claim in claims:
        claim["part"] = section_handle(claim["part"].strip().removeprefix("s:").split("#")[-1])
    parts = list(dict.fromkeys(parts + [c["part"] for c in claims]))
    return dict(checked=int(found.group(1)), unsupported=int(found.group(2)), notes=notes, claims=claims, parts=parts,
                refs=refs, ref_malformed=malformed)


def scope_text(report: dict, fixer_answer: str) -> str:
    """What the scoped second check receives in `{PARTS}`: the fixer's own report of the parts and sentences it
    changed; when the fixer said nothing usable, the parts and sentence starts the first report listed."""
    answer = fixer_answer.strip()
    if answer:
        return answer[:2000]
    return "; ".join(f"{c['part'].strip()}: {c['start'].strip()}" for c in report["claims"]) or ", ".join(report["parts"])


def section_handle(heading: str) -> str:
    """As `syntheses.section_handle` of the engine: the handle `mem` gives a part."""
    import unicodedata
    ascii_text = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def resolve_parts(parts: list[str], text: str) -> list[str]:
    """Reported parts as handles: a checker may name a part by the line range `mem show s:<slug>` prints
    (`12-30`), which is the part whose heading sits on the range's first line."""
    by_line = {n: section_handle(line[3:]) for n, line in enumerate(text.splitlines(), 1) if line.startswith("## ")}
    out = []
    for part in parts:
        m = re.fullmatch(r"(\d+)-\d+", part)
        out.append(by_line.get(int(m.group(1)), part) if m else part)
    return list(dict.fromkeys(out))


def split_parts(text: str) -> dict[str, str]:
    """Part handle -> exact part text (heading line included); the front matter and anything before the first part
    are left out."""
    pieces = re.split(r"^(?=## )", text, flags=re.M)[1:]
    return {section_handle(piece.splitlines()[0][3:]): piece for piece in pieces}


def changed_outside(before: str, after: str, allowed: list[str]) -> list[str]:
    """Handles of the parts that differ between the two texts although they are not in `allowed`: a fixer may touch
    only the parts its report lists, and an untouched part must stay byte-equal."""
    old, new = split_parts(before), split_parts(after)
    return sorted(h for h in old.keys() | new.keys() if old.get(h) != new.get(h) and h not in allowed)


def guard_parts(store: Path, env: dict, topic: str, before: str, after: str, allowed: list[str]) -> tuple[list[str], list[str]]:
    """(violations, reverted): the parts changed outside `allowed` and those put back to their text in `before`
    through `mem synthesis edit --shrink`, so the undo log and `mem check` stay consistent. A part the fixer removed
    or added cannot be put back by `edit`: it stays in the violations only."""
    violations = changed_outside(before, after, allowed)
    old, new = split_parts(before), split_parts(after)
    reverted = []
    for handle in violations:
        if handle in old and handle in new:
            text = old[handle].split("\n", 1)[1].strip("\n") if "\n" in old[handle] else ""
            done = mem(store, env, "synthesis", "edit", f"s:{topic}#{handle}", "--body-file", "-", "--shrink",
                       "--drop-references", stdin=text + "\n")
            if done.returncode == 0:
                reverted.append(handle)
    return violations, reverted


def summary(s: dict) -> dict:
    return dict(role=s["role"], model=s["model"], costs=s["costs"], cost=s["cost"], wall=s["wall"], writes=s["writes"],
                write_errors=s["write_errors"], denied=s["denied"], tool_errors=s["tool_errors"],
                ok=s["has_result"] and not s["error"])


class Stop(Exception):
    """The loop ends: the budget is spent, or a session left no cost report."""


NO_COST = "a session ended without a cost report"


def lean_loop(claude: str, env: dict, base: Path, store: Path, work: Path, settings: Path, topic: str,
              sessions: list[dict], lean: bool = True, left=None, briefs: Path = BRIEFS) -> dict:
    """Check, fix, and (lean) scoped check and delete-only step for the synthesis `s:<topic>` already in `store`.

    Each session's summary is appended to `sessions`; session streams go to `base/NN-<role>.jsonl`. Returns
    `arm_count` (first check, None when its report is unreadable), `why` (empty when every step worked), `fixes`,
    `deleted`, `scope_violations`, `reverted` (the violations put back), `refs` (per check that reported `REF:` lines:
    `check`, `reported` lines, proposal `lines` sent, `applied` and `refused` as `mem synthesis refs` printed them,
    `error` when the command failed). `briefs` is the folder the brief files are read from. `lean=False` is the trial's arm S: one Sonnet fixer, no second check.
    `left` (a function: USD still allowed) caps every step: none starts when nothing is left, each session gets
    `--max-budget-usd` of what is left, and a session without a result event (killed at its timeout: its spend is
    unknown) ends the loop with `why` = NO_COST."""
    synthesis = store / "syntheses" / f"{topic}.md"
    fill = dict(TOPIC=topic, SLUG=topic, STORE=str(store), WORK_DIR=str(work))
    out = dict(arm_count=None, why="", fixes=0, deleted=0, scope_violations=[], reverted=[], refs=[])

    def step(role: str, model: str, text: str, level: str | None = None) -> dict:
        remaining = left() if left else None
        if remaining is not None and remaining <= 0:
            raise Stop("budget spent")
        s = run_session(claude, model, text, work, settings, env, base / f"{len(sessions) + 1:02d}-{role}.jsonl",
                        effort=level, max_budget=remaining)
        s.update(role=role, model=model, costs=cost_by_family(s["model_usage"]))
        sessions.append(summary(s))
        if left and not s["has_result"]:
            raise Stop(NO_COST)
        return s

    def check(n: int, scope: str = NOT_GIVEN) -> dict | None:
        report = work / f"report-{n}.md"
        report.unlink(missing_ok=True)
        units = work / f"units-{n}.md"
        write_units(synthesis, units)   # rewritten per check: the fixer changed the text
        step("checker", "haiku", brief("checker", briefs, **fill, REPORT_FILE=str(report), PARTS=scope,
                                       UNITS_FILE=str(units)), CHEAP)
        return parse_report(report)

    def apply_refs(n: int, report: dict | None) -> None:
        """The report's `REF:` lines through `mem synthesis refs`, before anything changes the text their numbers
        refer to. A failure is recorded, never raised."""
        if not report or not report["refs"]:
            return
        lines = []
        for r in report["refs"]:
            if r["kind"] == "wrong":
                lines.append(f"{r['part']} | {r['number']} | remove {r['current']}")
            if r["target"]:
                lines.append(f"{r['part']} | {r['number']} | add {r['target']}")
        row = dict(check=n, reported=len(report["refs"]), lines=len(lines), applied=0, refused=0, error="")
        out["refs"].append(row)
        if not lines:
            return
        proposals = work / f"refs-{n}.txt"
        proposals.write_text("".join(ln + "\n" for ln in lines))
        try:
            done = mem(store, env, "synthesis", "refs", f"s:{topic}", "--file", str(proposals))
        except OSError as exc:
            row["error"] = str(exc)
            return
        total = REFS_TOTAL.findall(done.stdout)
        if done.returncode or not total:
            row["error"] = (done.stderr.strip() or done.stdout.strip() or f"exit {done.returncode}")[:200]
        else:
            added, removed, refused = map(int, total[-1])
            row.update(applied=added + removed, refused=refused)

    def guarded_fix(model: str, level: str | None, text: str, report: dict, role: str = "fixer") -> dict:
        """One fixer step; the parts it changed outside the report's PARTS are recorded and put back."""
        before = synthesis.read_text()
        s = step(role, model, text, level)
        bad, back = guard_parts(store, env, topic, before, synthesis.read_text(), resolve_parts(report["parts"], before))
        out["scope_violations"].extend(bad)
        out["reverted"].extend(back)
        return s

    try:
        first = out["arm_count"] = check(1)
        apply_refs(1, first)
        if first is None:
            out["why"] = "arm checker report unreadable"
        elif first["unsupported"]:
            out["fixes"] = 1
            text = brief("fixer", briefs, **fill, REPORT_FILE=str(work / "report-1.md"))
            if not lean:
                guarded_fix("sonnet", None, text, first)
            else:
                fixed = guarded_fix("haiku", CHEAP, text, first)
                second = check(2, scope_text(first, fixed["answer"]))
                apply_refs(2, second)
                if second is None:
                    out["why"] = "scoped check report unreadable"
                elif second["unsupported"]:
                    guarded_fix("haiku", CHEAP, text.replace(str(work / "report-1.md"), str(work / "report-2.md"))
                                + DELETE_ONLY, second, "deleter")
                    out["deleted"] = len(second["claims"]) or second["unsupported"]
    except Stop as stop:
        out["why"] = str(stop)
    return out
