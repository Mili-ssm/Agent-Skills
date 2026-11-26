"""`bin/mem-corroborate`: the pass that matches lessons by meaning, with a fake `claude` and invented lessons."""

import datetime
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TypedDict, Unpack

import corroborate
import corroborate_reword
import jobs
import pytest
import records

PLUGIN = Path(__file__).resolve().parents[2]
CORR = PLUGIN / "bin" / "mem-corroborate"
MEM = PLUGIN / "bin" / "mem"
TODAY = datetime.date.today()
OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE"

FAKE = """#!/usr/bin/env python3
import json, os, re, shutil, sys
mode = os.environ.get("FAKE_MODE", "good")
if mode == "never":
    sys.exit("the fake must not be called")
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "files": sorted(os.listdir(".")),
                        "mem_vars": sorted(k for k in os.environ if k.startswith(("MEM_", "CLAUDE_PLUGIN"))),
                        "path": os.environ.get("PATH", "")}) + "\\n")
brief = sys.argv[sys.argv.index("-p") + 1]
out = re.search(r"Write (\\S+) as JSON", brief).group(1)
src = os.environ.get("FAKE_DIGEST_CHECK" if out.endswith("digest-check.json") else "FAKE_DIGEST" if out.endswith("digest-write.json")
                     else "FAKE_REWORD_CHECK" if out.endswith("reword-check.json") else "FAKE_REWORD" if out.endswith("reword.json")
                     else "FAKE_VERDICTS" if out.endswith("verdicts.json") else "FAKE_FILL" if out.endswith("fill.json") else "FAKE_GROUPS")
if os.path.basename(out).startswith("digest-") and os.environ.get("FAKE_INPUTS"):   # what the session was asked, kept for the test
    shutil.copy("input.txt", os.environ["FAKE_INPUTS"] + "-" + os.path.basename(out)[:-5])
if mode == "exit1":
    sys.exit(1)
if src and os.path.exists(src):
    shutil.copy(src, out)
print(json.dumps({"type": "result", "is_error": False, "result": "done", "total_cost_usd": 0.03}))
"""

BRIEF = (
    "Brief the subagent with the acceptance check before it starts, so it can tell when it is done."
)
BRIEF2 = "Give a subagent the acceptance check first: with it the subagent can tell by itself when it is done."


class World:
    """What a test needs: the temp dir, the fake `claude`, the data and memory folders, two projects."""

    tmp: Path
    fake: Path
    calls_file: Path
    gmem: Path
    data: Path
    cdir: Path
    pa: Path
    pb: Path


@pytest.fixture
def w(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()
    w.tmp = tmp_path
    w.fake = tmp_path / "fake-claude"
    w.fake.write_text(FAKE)
    w.fake.chmod(0o755)
    w.calls_file = tmp_path / "calls"
    w.gmem = tmp_path / "gmem"
    w.gmem.mkdir()
    w.data = Path(os.environ["MEM_DATA"])
    w.cdir = w.data / "corroborate"
    w.pa, w.pb = tmp_path / "alpha-p-a", tmp_path / "beta-p-b"
    for p in (w.pa, w.pb):
        records.project_dir(p).mkdir(parents=True)
    w.data.mkdir(parents=True)
    (w.data / "projects.json").write_text(
        json.dumps({p.name: {"path": str(p), "seen": TODAY.isoformat()} for p in (w.pa, w.pb)})
    )
    monkeypatch.setenv("MEM_COUNT_TEMP_PROJECTS", "1")
    monkeypatch.setenv("MEM_MEMORIES", str(w.gmem))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FAKE_CALLS", str(w.calls_file))
    monkeypatch.setenv("FAKE_INPUTS", str(tmp_path / "asked"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.delenv(OPTION, raising=False)
    (tmp_path / "tmp").mkdir()
    return w


class LessonOptions(TypedDict, total=False):
    created: datetime.date
    weight: str
    scope: str


def lesson(w, project, claim, sessions=("s1",), **options: Unpack[LessonOptions]):
    created = options.get("created", TODAY)
    weight = options.get("weight", "light")
    scope = options.get("scope", "project")
    folder = records.project_dir(project) if scope == "project" else w.gmem
    sources = [
        f"session {s}"
        if scope == "project"
        else f"session {s} project {records.project_key(project)}"
        for s in sessions
    ]
    return records.write_memory(
        folder,
        scope,
        kind="lesson",
        claim=claim,
        body="b\n",
        today=created,
        sources=sources,
        origin="transcript",
        reach="general",
        weight=weight,
    )


def glob(w, claim, sessions, project=None, created=TODAY):
    return lesson(w, project or w.pa, claim, sessions, created=created, scope="global")


def lessons(w):
    registry = records.read_registry(w.data)
    return corroborate.collect(corroborate.counted_projects(registry), w.gmem, TODAY)


def ident(w, snippet):
    found = [x.id for x in lessons(w) if snippet in x.memory.claim]
    assert len(found) == 1, (snippet, found)
    return found[0]


def group(
    *ids,
    claim="Hand a subagent the check that tells it the task is done before it starts, and see whether it helps.",
    context="when briefing a subagent",
):
    return {"ids": list(ids), "claim": claim, "context": context}


def verdict(n, **override):
    return {
        "group": n,
        "reason": "both ask for the same",
        "same": True,
        "faithful": True,
        "general": True,
        **override,
    }


def model(w, groups, verdicts: str | list | None = "all"):
    """The fake writes these files as the model's answers; `verdicts` "all" approves every group, None writes none."""
    (w.tmp / "groups.json").write_text(
        groups if isinstance(groups, str) else json.dumps({"groups": groups})
    )
    os.environ["FAKE_GROUPS"] = str(w.tmp / "groups.json")
    if verdicts is None:
        os.environ.pop("FAKE_VERDICTS", None)
        return
    if verdicts == "all":
        verdicts = [verdict(n) for n in range(1, len(groups) + 1)]
    (w.tmp / "verdicts.json").write_text(
        verdicts if isinstance(verdicts, str) else json.dumps({"verdicts": verdicts})
    )
    os.environ["FAKE_VERDICTS"] = str(w.tmp / "verdicts.json")


class RunOptions(TypedDict, total=False):
    mode: str
    cmd: str
    env: dict[str, str] | None
    claude: bool
    corr: Path | None


def run(w, *args, **options: Unpack[RunOptions]):
    mode = options.get("mode", "good")
    cmd = options.get("cmd", "run")
    env = options.get("env")
    claude = options.get("claude", True)
    corr = options.get("corr")
    full = {k: v for k, v in os.environ.items() if k != "MEM_PROJECT"}
    full["FAKE_MODE"] = mode
    full.update(env or {})
    argv = [str(corr or CORR), cmd, *(["--claude", str(w.fake)] if claude else []), *args]
    return subprocess.run(argv, env=full, capture_output=True, text=True, timeout=300, check=False)


def status(w):
    return jobs.read_json(w.cdir / "status.json")


def log_lines(w):
    path = w.cdir / "log.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def calls(w):
    return len(w.calls_file.read_text().splitlines()) if w.calls_file.exists() else 0


def globals_(w):
    return [m for m in records.load_memories(w.gmem, "global") if m.status == "active"]


def project_records(project):
    return {m.handle: m for m in records.load_memories(records.project_dir(project), "project")}


def snapshot(w):
    out = {}
    for folder in (w.gmem, records.project_dir(w.pa), records.project_dir(w.pb)):
        for p in folder.iterdir():
            if p.is_file():
                out[str(p)] = p.read_bytes()
    return out


def two_projects(w):
    lesson(w, w.pa, BRIEF, ("s1",))
    lesson(w, w.pb, BRIEF2, ("s2",))
    return ident(w, "Brief the subagent"), ident(w, "Give a subagent")


# ---- fix round: failures against refusals, silent non-work, repeatable undo, process ----------------------------


def fake_plugin(w, shell):
    """A copy of the command beside a `mem` wrapper: `shell` runs first, then the real `mem` (REAL is its path)."""
    plug = w.tmp / "plug"
    (plug / "bin").mkdir(parents=True)
    shutil.copy(CORR, plug / "bin" / "mem-corroborate")
    (plug / "engine").symlink_to(PLUGIN / "engine")
    mem = plug / "bin" / "mem"
    mem.write_text("#!/bin/sh\n" + shell.replace("REAL", str(MEM)) + f'\nexec {MEM} "$@"\n')
    for f in (mem, plug / "bin" / "mem-corroborate"):
        f.chmod(0o755)
    return plug / "bin" / "mem-corroborate"


# ---- fill_auto: the pass writes and checks short forms by itself ---------------------------------------------------

NARROW = "Run the narrowest test that covers a change before the whole suite, as it may save time."
GCLAIM = "Read the whole failing test output before you change any code."


def candidate_ids(w):
    """claim -> ids of the lessons that lack a short form, as the fill sees them."""
    registry = records.read_registry(w.data)
    found = {}
    for i, _p, m in corroborate.fill_records(corroborate.counted_projects(registry), w.gmem):
        found.setdefault(m.claim, []).append(i)
    return found


def by_claim(w, claim):
    return next(m for m in project_records(w.pa).values() if m.claim == claim)


# ---- reword_auto: the pass rewords a loaded lesson whose present wording got worse ----------------------------------

OLD_WORDING = "Running the narrowest covering test before the whole suite may save time."
NEW_WORDING = (
    "Before the whole suite, running the narrowest test that covers a change may save time."
)


def ago(n):
    return TODAY - datetime.timedelta(days=n)


def worse_one(w, claim=NARROW, scope="project", failed=(5, 4), worked=()):
    """A loaded lesson whose only wording (10 days old) failed twice since: the step's candidate."""
    if scope == "global":  # as `fill_world` makes it: seen in two projects, released from triage
        m = records.write_memory(
            w.gmem,
            "global",
            kind="lesson",
            claim=claim,
            body="b\n",
            today=TODAY,
            origin="transcript",
            reach="general",
            weight="light",
            sources=[
                f"session s5 project {records.project_key(w.pa)}",
                f"session s6 project {records.project_key(w.pb)}",
            ],
        )
        m = records.update(m, TODAY, triage=None)
    else:
        m = lesson(w, w.pa, claim, ("s7", "s8"))
    log = [records.case_entry(ago(n), f"session z{n}", "failed") for n in failed]
    log += [records.case_entry(ago(n), f"session y{n}", "worked") for n in worked]
    return records.update(
        m,
        TODAY,
        short=OLD_WORDING,
        short_by="model",
        versions=[records.version_entry(ago(10), OLD_WORDING)],
        log=log,
    )


def reword_answers(w, mp, shorts=None, writer="ok", checker: bool | str = True):
    """The fake's two answers of the step. shorts: claim -> proposed short (default NEW_WORDING for every candidate);
    writer/checker as in `answers`, with no `topic` anywhere."""
    mp.delenv("FAKE_REWORD", raising=False)
    mp.delenv("FAKE_REWORD_CHECK", raising=False)
    found = candidate_ids(w)
    if writer == "ok":
        items = [
            {"id": i, "short": (shorts or {}).get(c, NEW_WORDING)}
            for c, ids in found.items()
            for i in ids
        ]
        writer = json.dumps({"items": items})
    if writer != "none":
        (w.tmp / "reword-answer.json").write_text(writer)
        mp.setenv("FAKE_REWORD", str(w.tmp / "reword-answer.json"))
    if checker is True or checker is False:
        every = [i for ids in found.values() for i in ids]
        checker = json.dumps({
            "verdicts": [
                {"id": i, "reason": "the checker's reason", "faithful": checker} for i in every
            ]
        })
    if checker != "none":
        (w.tmp / "reword-check-answer.json").write_text(checker)
        mp.setenv("FAKE_REWORD_CHECK", str(w.tmp / "reword-check-answer.json"))


def reword(w, **kw):
    return corroborate_reword.reword_auto(str(w.fake), 0.25, **kw)


def reword_state(w):
    return json.loads((w.cdir / "reword-attempts.json").read_text())
