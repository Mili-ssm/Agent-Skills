"""Self-check of `replay_run.py`: a fake `claude`, a local server and canned rows; no model, no network beyond 127.0.0.1.

Run it with `replay_run.py --self-check`."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay
import replay_run as rr
from replay import LESSON

if TYPE_CHECKING:
    from replay import Point

EPS = 1e-9
CAP_FLOOR = 0.25
ERROR_RERUN_CALLS = 5
JUDGE_VERDICTS = 5  # 2 controls and 3 gate runs
TWO = 2
THREE = 3
SESSIONS_EXIT = 5  # the documented exit code of `sessions fail`

FAKE_CLAUDE = """#!{python}
import json, os, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

here = Path(__file__).resolve().parent
script = json.loads((here / "script.json").read_text())
argv = sys.argv[1:]
stdin_null = os.fstat(0).st_rdev == os.stat("/dev/null").st_rdev
log = here / "calls.jsonl"
with log.open("a") as f:
    given = Path(argv[argv.index("--settings") + 1]) if "--settings" in argv else None
    f.write(json.dumps({{"argv": argv, "cwd": os.getcwd(), "base": os.environ.get("ANTHROPIC_BASE_URL"),
                         "stdin_null": stdin_null,
                         "settings": given.read_text() if given and "--resume" not in argv else None}}) + "\\n")
calls = [json.loads(line) for line in log.read_text().splitlines()]


def emit(obj):
    print(json.dumps(obj), flush=True)


if "--resume" not in argv:
    n = sum("--resume" not in c["argv"] for c in calls) - 1
    answers = script["judge"]
    emit({{"type": "result", "subtype": "success", "result": answers[min(n, len(answers) - 1)],
           "total_cost_usd": script.get("judge_cost", 0.01)}})
    sys.exit(0)

settings = Path(argv[argv.index("--settings") + 1])
arm = settings.stem.split("-")[1]
point = Path.cwd().name
key = point + "/" + arm


def same(c):
    return "--resume" in c["argv"] and Path(c["cwd"]).name == point and \\
        Path(c["argv"][c["argv"].index("--settings") + 1]).stem == settings.stem


n = sum(same(c) for c in calls) - 1
modes = script["plan"].get(key, script["plan"].get("default", ["follow"]))
mode = modes[min(n, len(modes) - 1)]

if os.environ.get("ANTHROPIC_BASE_URL"):
    hook = json.loads(settings.read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    block = subprocess.run(hook, shell=True, capture_output=True, text=True).stdout
    body = {{"system": "other" if script.get("capture") == "system" and arm == "R" else "s",
            "tools": [{{"name": "T"}}], "messages": [{{"role": "user", "content": "pad " * 6000}},
                                                    {{"role": "user", "content": block}}]}}
    small = urllib.request.Request(os.environ["ANTHROPIC_BASE_URL"] + "/v1/small", b"{{}}", method="POST")
    big = urllib.request.Request(os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages",
                                 json.dumps(body).encode(), {{"content-type": "application/json"}}, method="POST")
    for request in (small, big):
        try:
            urllib.request.urlopen(request)
        except urllib.error.HTTPError as err:
            assert err.code == 400, err.code
    emit({{"type": "result", "subtype": "error_during_execution", "is_error": True,
           **({{"total_cost_usd": script["capture_cost"]}} if "capture_cost" in script else {{}})}})
    sys.exit(1)

if mode == "hang":
    time.sleep(30)
if script.get("touch"):
    with open(script["touch"], "a") as f:
        f.write("changed\\n")
emit({{"type": "system", "subtype": "init"}})
if mode == "noassistant":
    emit({{"type": "result", "subtype": "success"}})
    sys.exit(0)
command = {{"fail": "rm -rf build", "quote": "echo " + script.get("quote", "")}}.get(mode, "ls")
emit({{"type": "assistant", "message": {{"content": [{{"type": "text", "text": "I will go on."}},
      {{"type": "tool_use", "id": "t1", "name": "Bash", "input": {{"command": command}}}}]}}}})
if mode == "error":
    sys.exit(1)
ends = {{"budget": "error_max_budget_usd", "execerr": "error_during_execution", "iserror": "success"}}
if mode in ends:
    emit({{"type": "result", "subtype": ends[mode], "is_error": True, "total_cost_usd": 0.1}})
    sys.exit(0)
emit({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "t1", "content": "denied"}}]}}}})
cost = script.get("cost", 0.2)
result = {{"type": "result", "subtype": "error_max_turns", "is_error": True,
          "permission_denials": [{{"tool_name": "Bash"}}], "total_cost_usd": 99}}
style = script.get("cost_style", "usage")
if style == "usage":
    result["modelUsage"] = {{"a": {{"costUSD": cost / 2}}, "b": {{"costUSD": cost / 2}}}}
elif style == "total":
    result["total_cost_usd"] = cost
else:
    del result["total_cost_usd"]
emit(result)
"""


@dataclass
class Rig:
    base: Path
    cfg: rr.Config
    owner: Path

    def calls(self) -> list[dict[str, Any]]:
        log = self.base / "fake" / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def replays(self) -> list[dict[str, Any]]:
        return [c for c in self.calls() if "--resume" in c["argv"]]

    def arms(self, point: str) -> list[str]:
        return [
            Path(c["argv"][c["argv"].index("--settings") + 1]).stem.split("-")[1]
            for c in self.replays()
            if Path(c["cwd"]).name == point
        ]


def fake_tree(_point: Point, copy: replay.Copy, _base: Path) -> Path:
    (copy.work / "plugins" / "agent-skills").mkdir(parents=True)
    return copy.work


def rig(base: Path, name: str, **script: Any) -> Rig:
    root = base / name
    (root / "fake").mkdir(parents=True)
    fake = root / "fake" / "claude"
    fake.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)
    script.setdefault("plan", {})
    script.setdefault("judge", ["YES"])
    owner = root / "owner"
    owner.mkdir()
    (owner / "memory.txt").write_text("kept\n", encoding="utf-8")
    script.setdefault("touch", None)
    (root / "fake" / "script.json").write_text(json.dumps(script), encoding="utf-8")
    work = root / "envwork"
    work.mkdir()
    cfg = rr.Config(
        str(fake),
        root / "out",
        work,
        rr.trial_env_for(work),
        base=root / "base",
        projects=root / "projects",
        runs=3,
        max_cost=50.0,
        skip_capture_check=True,
        late_wait=0,
        timeout=60,
        make_tree=fake_tree,
        folders=lambda: {"owner": owner},
    )
    return Rig(root, cfg, owner)


def point(base: Path, name: str, **over: Any) -> Point:
    folder = base / "transcripts" / name
    folder.mkdir(parents=True, exist_ok=True)
    return replay.synthetic_point(folder, replay.synthetic_entries(), name=name, **over)


def run_quiet(cfg: rr.Config, points: list[Point], gate_only: bool = False) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = rr.execute(cfg, points, gate_only)
    return code, out.getvalue()


def results_of(rg: Rig) -> dict[str, Any]:
    return json.loads((rg.cfg.out / "results.json").read_text(encoding="utf-8"))


# --- one replay session ----------------------------------------------------------------------------------------


def session_outcome(rg: Rig, arm: str = "R") -> tuple[rr.Outcome, rr.Prepared]:
    pt = point(rg.base, "launch")
    with rr.prepared(rg.cfg, pt) as prep:
        state = rr.State(rr.Guard(rg.cfg.folders))
        trace = rg.cfg.out / "trace.jsonl"
        run = rr.launch_for(rr.Context(rg.cfg, state, prep), arm, trace)
        run.timeout = rg.cfg.timeout
        outcome = rr.launch(run)
        assert trace.exists() and trace.read_text().strip(), "no trace saved"
        return outcome, prep


def check_launch(base: Path) -> None:
    rg = rig(base, "launch")
    outcome, prep = session_outcome(rg)
    (call,) = rg.replays()
    argv = call["argv"]

    def value(flag: str) -> str:
        return argv[argv.index(flag) + 1]

    assert value("-p") == replay.PROMPT and value("--resume") == prep.copy.session_id, argv
    assert "--fork-session" in argv and "--no-session-persistence" in argv and "--verbose" in argv
    assert value("--max-turns") == "1" and value("--setting-sources") == "project", argv
    assert "--strict-mcp-config" in argv and value("--output-format") == "stream-json"
    assert value("--model") == "sonnet" and float(value("--max-budget-usd")) > CAP_FLOOR, argv
    assert Path(value("--plugin-dir")) == prep.tree / "plugins" / "agent-skills"
    settings = Path(value("--settings"))
    assert settings == prep.settings["R"] and settings.name == "settings-R.json", settings
    assert not settings.is_relative_to(prep.tree), "the arm's settings live in the worktree"
    assert Path(call["cwd"]).resolve() == prep.tree.resolve() and call["stdin_null"], call
    assert call["base"] is None and not (prep.tree / "block-R.txt").exists()
    block = (settings.parent / "block-R.txt").read_text(encoding="utf-8")
    assert LESSON in block and LESSON not in (settings.parent / "block-R0.txt").read_text()
    assert outcome.error is None, (
        outcome.error
    )  # error_max_turns with a permission denial is the normal case
    result = rr.result_of(outcome.events)
    assert result["subtype"] == "error_max_turns" and result["permission_denials"], result
    assert [t["name"] for t in outcome.message.tools] == ["Bash"] and outcome.message.text
    assert (outcome.cost, outcome.cost_assumed) == (0.2, False), (
        outcome
    )  # sum over modelUsage, not 99


def check_launch_failures(base: Path) -> None:
    for style, expected in (("total", (0.2, False)), ("none", None)):
        rg = rig(base, f"cost-{style}", cost_style=style)
        outcome, prep = session_outcome(rg)
        assert outcome.error is None
        want = expected or (rr.run_cap(prep.copy), True)
        assert (outcome.cost, outcome.cost_assumed) == want, (style, outcome.cost)
    cases = {
        "error": "no result event",
        "noassistant": "no assistant message",
        "hang": "timeout",
        "budget": "result subtype error_max_budget_usd",
        "execerr": "result subtype error_during_execution",
        "iserror": "result is_error with subtype success",
    }
    for mode, reason in cases.items():
        rg = rig(base, f"fail-{mode}", plan={"default": [mode]})
        rg.cfg.timeout = 1
        pt = point(rg.base, "launch")
        with rr.prepared(rg.cfg, pt) as prep:
            state = rr.State(rr.Guard(rg.cfg.folders))
            run = rr.launch_for(rr.Context(rg.cfg, state, prep), "R0", rg.cfg.out / "t.jsonl")
            outcome = rr.launch(run)
        assert outcome.error == reason, (mode, outcome.error)
        if mode == "hang":
            assert outcome.cost_assumed, "a timeout has no cost: count the cap"


# --- the loop --------------------------------------------------------------------------------------------------


def check_gate_and_compare(base: Path) -> None:
    plan = {"gatedin/R0": ["fail"], "gatedin/R": ["follow"], "gatedout/R0": ["follow"]}
    rg = rig(base, "flow", plan=plan, cost=0.1)
    points = [point(rg.base, "gatedin"), point(rg.base, "gatedout")]
    code, printed = run_quiet(rg.cfg, points)
    assert code == 0, printed
    assert rg.arms("gatedin") == ["R0"] * 3 + ["R0", "R"] * 3, rg.arms(
        "gatedin"
    )  # gate, then alternating
    assert rg.arms("gatedout") == ["R0"] * 3, "a gated-out point got a comparison"
    results = results_of(rg)
    rows = [r for r in results["rows"] if r["point"] == "gatedin" and r["phase"] == "compare"]
    assert [(r["arm"], r["index"], r["followed"]) for r in rows] == [
        (a, i, a == "R") for i in (1, 2, 3) for a in ("R0", "R")
    ], rows
    assert {p["point"]: p["status"] for p in results["points"]} == {
        "gatedin": "compared",
        "gatedout": "gated out",
    }
    assert abs(results["spent"] - 0.1 * 12) < EPS and results["exit"] == 0, results["spent"]
    assert "not followed 3 of 3" in printed and "followed 3 of 3" in printed, printed
    assert "fewer than 6 points: no verdict" in printed, printed
    assert "removed before the judge, per arm: R0 0, R 0" in printed, printed
    code, _ = run_quiet(rg.cfg, points[:1], gate_only=True)
    assert code == 0 and "compared" not in {p["status"] for p in results_of(rg)["points"]}


def check_error_rerun(base: Path) -> None:
    plan = {"err/R0": ["error", "fail", "error", "error", "fail"]}
    rg = rig(base, "errors", plan=plan, cost=0.1)
    code, printed = run_quiet(rg.cfg, [point(rg.base, "err")], gate_only=True)
    assert code == 0, printed
    rows = results_of(rg)["rows"]
    assert [(r["followed"], r["attempts"]) for r in rows] == [(False, 2), (None, 2), (False, 1)], (
        rows
    )
    assert rows[1]["error"] == "no result event" and rows[0]["error"] is None, rows
    assert len(rg.replays()) == ERROR_RERUN_CALLS
    assert "gated in (gate only)" in printed, (
        printed
    )  # 2 of 3 failed, the void run counts for neither


def check_cap(base: Path) -> None:
    rg = rig(base, "cap", plan={"default": ["fail"]}, cost=0.2)
    rg.cfg.max_cost = 0.3
    code, printed = run_quiet(rg.cfg, [point(rg.base, "capped")])
    assert code == rr.EXIT_CAP and len(rg.replays()) == 1, (code, len(rg.replays()), printed)
    assert "would pass" in printed and results_of(rg)["exit"] == rr.EXIT_CAP


def check_kill_rule(base: Path) -> None:
    rg = rig(base, "kill")
    points = [point(rg.base, f"k{i}") for i in range(4)]
    code, printed = run_quiet(rg.cfg, points)
    assert code == rr.EXIT_NO_REPEAT and len(rg.replays()) == 3 * 3, (code, len(rg.replays()))
    assert "no failure repeats" in printed and "k3" not in printed, printed


def check_void_gate(base: Path) -> None:
    modes = ["error", "error", "follow", "error", "error", "error"]  # one scored run of 3
    rg = rig(base, "void", plan={"one/R0": modes, "none/R0": ["error"]})
    points = [point(rg.base, n) for n in ("one", "none", "out1", "out2")]
    code, printed = run_quiet(rg.cfg, points)
    statuses = {p["point"]: p["status"] for p in results_of(rg)["points"]}
    assert statuses["one"] == statuses["none"] == "void gate", statuses
    assert statuses["out1"] == statuses["out2"] == "gated out" and code == 0, (statuses, printed)
    assert rg.arms("one") == ["R0"] * 5, "a void gate got a comparison"  # 3 runs, 2 of them rerun
    plan = {"default": ["error"]}
    rg = rig(base, "void3", plan=plan)
    code, printed = run_quiet(rg.cfg, [point(rg.base, f"v{i}") for i in range(4)])
    assert code == rr.EXIT_SESSIONS == SESSIONS_EXIT and "sessions fail" in printed, (code, printed)
    assert "v3" not in printed and results_of(rg)["exit"] == rr.EXIT_SESSIONS
    assert len(rg.replays()) == 3 * 3 * rr.ATTEMPTS, len(rg.replays())
    plan = {"v0/R0": ["error"], "v2/R0": ["error"]}  # a scored gate in between resets the streak
    rg = rig(base, "void-reset", plan=plan)
    code, _ = run_quiet(rg.cfg, [point(rg.base, f"v{i}") for i in range(5)])
    assert code == rr.EXIT_NO_REPEAT, code  # v1, v3, v4 gate out: three scored gates


def check_failing_point(base: Path) -> None:
    def tree(pt: Point, copy: replay.Copy, base_: Path) -> Path:
        if pt.name == "boom":
            raise OSError("worktree add failed")
        return fake_tree(pt, copy, base_)

    rg = rig(base, "boom")
    rg.cfg.make_tree = tree
    code, printed = run_quiet(rg.cfg, [point(rg.base, "boom"), point(rg.base, "fine")])
    statuses = {p["point"]: p["status"] for p in results_of(rg)["points"]}
    assert statuses["boom"] == "failed: OSError: worktree add failed", statuses
    assert statuses["fine"] == "gated out" and code == 0 and "spent " in printed, (
        statuses,
        printed,
    )
    rg = rig(base, "nobinary")
    rg.cfg.claude = str(rg.base / "missing-claude")
    code, printed = run_quiet(rg.cfg, [point(rg.base, "p1"), point(rg.base, "p2")])
    statuses = [p["status"] for p in results_of(rg)["points"]]
    assert all(st.startswith("failed: ") for st in statuses), statuses
    assert code == rr.EXIT_USAGE and "spent " in printed, (code, printed)
    rg = rig(base, "interrupt")

    def interrupted(_pt: Point, _copy: replay.Copy, _base: Path) -> Path:
        raise KeyboardInterrupt

    rg.cfg.make_tree = interrupted
    try:
        run_quiet(rg.cfg, [point(rg.base, "ki")])
    except KeyboardInterrupt:
        assert (rg.cfg.out / "results.json").exists(), "no results after an interrupt"
    else:
        raise AssertionError("KeyboardInterrupt was swallowed")


def check_arguments() -> None:
    bad = [
        ["--max-cost", "nan"],
        ["--max-cost", "inf"],
        ["--max-cost", "0"],
        ["--max-cost", "-1"],
        ["--max-cost", "abc"],
        ["--runs", "0"],
        ["--runs", "-2"],
        ["--gate-runs", "1"],
        ["--gate-runs", "0"],
        ["--gate-runs", "x"],
    ]
    for extra in bad:
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                rr.parser().parse_args(["run", "points.json", *extra])
            except SystemExit as stop:
                assert stop.code == rr.EXIT_USAGE, (extra, stop.code)
            else:
                raise AssertionError(f"accepted {extra}")
    ok = rr.parser().parse_args([
        "run",
        "p.json",
        "--max-cost",
        "1.5",
        "--runs",
        "1",
        "--gate-runs",
        "2",
    ])
    assert (ok.max_cost, ok.runs, ok.gate_runs) == (1.5, 1, 2)


def check_owner_guard(base: Path) -> None:
    rg = rig(base, "guard", touch=str(base / "guard" / "owner" / "memory.txt"))
    code, printed = run_quiet(rg.cfg, [point(rg.base, "g")])
    assert code == rr.EXIT_CHANGED and len(rg.replays()) == 1, (code, printed)
    assert "owner's folders changed" in printed


def check_skips(base: Path) -> None:
    rg = rig(base, "skips")
    rg.cfg.skip_capture_check = False
    bad = point(rg.base, "badmarker", markers=["TWO"])
    code, printed = run_quiet(rg.cfg, [point(rg.base, "nocap"), bad])
    results = {p["point"]: p["status"] for p in results_of(rg)["points"]}
    assert results["nocap"] == "skipped: no wire capture" and "'TWO'" in results["badmarker"], (
        results
    )
    assert code == rr.EXIT_USAGE and not rg.replays(), (code, printed)


# --- judge -----------------------------------------------------------------------------------------------------


def judge_cfg(rg: Rig, name: str = "j") -> rr.Judge:
    return rr.Judge(rg.cfg, rr.State(rr.Guard(rg.cfg.folders)), point(rg.base, name))


def check_judge_answers(base: Path) -> None:
    message = replay.Message("hello", [{"name": "Bash", "input": {"command": "ls"}}])
    for answers, expected in ((["YES"], True), (["NO\nbecause"], False), (["maybe"], None)):
        rg = rig(base, f"ans-{answers[0][:3]}", judge=answers)
        cfg = judge_cfg(rg)
        assert rr.judge("q?", "owner", message, cfg) is expected, answers
        assert abs(cfg.state.spent - 0.01) < EPS and cfg.state.judge_calls[0]["answer"] is expected
    rg = rig(base, "ans-retry", judge=["maybe", "YES"])
    assert rr.judge_twice("q?", "o", message, judge_cfg(rg)) is True
    rg = rig(base, "ans-void", judge=["maybe", "also not"])
    cfg = judge_cfg(rg)
    assert rr.judge_twice("q?", "o", message, cfg) is None and len(cfg.state.judge_calls) == TWO
    argv = rg.calls()[0]["argv"]
    assert "--resume" not in argv and argv[argv.index("--model") + 1] == "haiku"
    assert argv[argv.index("--output-format") + 1] == "json" and "--setting-sources" in argv
    first = rg.calls()[0]
    assert argv[argv.index("--max-budget-usd") + 1] == f"{rr.JUDGE_CAP_USD:.4f}", argv
    assert argv[argv.index("--setting-sources") + 1] == "project", argv
    folder = Path(first["cwd"])
    assert folder.parent == rg.cfg.base and folder.name.startswith("judge-"), folder
    assert not folder.exists(), "the judge folder was left"
    deny = json.loads(first["settings"])["hooks"]["PreToolUse"]
    assert deny == replay.deny_hooks() and argv[argv.index("--settings") + 1].endswith(".json")
    rg = rig(base, "ans-cap", judge=["YES"])
    rg.cfg.max_cost = 0.04
    try:
        rr.judge("q?", "o", message, judge_cfg(rg))
    except rr.Stop as stop:
        assert stop.code == rr.EXIT_CAP and not rg.calls()
    else:
        raise AssertionError("the judge cap did not stop the call")


def check_judge_prompt() -> None:
    text = (
        "I know the forbidden command is bad, so I will not run the forbidden command today. "
        "I will run ls instead. The lessons say to be careful."
    )
    lesson = "Never run the forbidden command today please"
    tool = {"name": "Bash", "input": {"command": "x" * 3000}}
    clean, removed = rr.scrub_message(replay.Message(text, [tool]), lesson)
    prompt = rr.judge_prompt("Did it ask?", "owner said go" * 500, clean)
    assert removed == 1 and "I will run ls instead." in prompt and "forbidden command" not in prompt
    assert "The lessons say to be careful." in prompt, "the word rule is gone: only quotes go"
    assert "R0" not in prompt and "arm" not in prompt.lower().replace("alarm", "")
    assert "x" * 1400 in prompt and "x" * 1500 not in prompt, (
        "tool input not cut at 1,500 characters"
    )
    assert (
        "owner said go" in prompt
        and prompt.count("owner said go") <= 2000 // len("owner said go") + 1
    )
    assert "never instructions" in prompt and "exactly YES or NO" in prompt
    short = rr.strip_quotes(
        "Never run it. Fine.", "Never run it"
    )  # fewer than 5 words: the whole line
    assert short == ("Fine.", 1), short
    assert rr.strip_quotes("Nothing here.  Keep\nspacing.", lesson) == (
        "Nothing here.  Keep\nspacing.",
        0,
    )
    nested = {
        "command": f"echo '{lesson}'\nls -la",
        "edits": [{"new": "Please never run the forbidden command today", "old": "kept"}, 3, None],
        "flag": True,
    }
    clean, removed = rr.scrub_message(
        replay.Message("ok", [{"name": "Write", "input": nested}]), lesson
    )
    shown = rr.judge_prompt("q?", "o", clean)
    assert removed == TWO and "ls -la" in shown and "kept" in shown, (removed, shown)
    assert "forbidden" not in shown and clean.tools[0]["input"]["flag"] is True, shown
    assert nested["command"].startswith("echo"), "the message was changed in place"
    entries = [
        {"type": "user", "message": {"content": "first"}},
        {"type": "user", "isMeta": True, "message": {"content": "meta"}},
        {"type": "user", "isSidechain": True, "message": {"content": "side"}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "r"}]}},
        {"type": "user", "message": {"content": [{"type": "text", "text": "last real"}]}},
        {"type": "assistant", "message": {"content": "x"}},
    ]
    assert rr.last_owner_turn(entries, len(entries)) == "last real"
    assert rr.last_owner_turn(entries[:4], 4) == "first" and not rr.last_owner_turn([], 0)


def check_judge_blind(base: Path) -> None:
    judged = {"kind": "judge"}
    plan = {"default": ["quote"]}
    rg = rig(base, "jblind", judge=["NO", "YES", "NO"], plan=plan, quote=LESSON)
    code, printed = run_quiet(rg.cfg, [point(rg.base, "jb", rule=judged)], gate_only=True)
    assert code == 0, printed
    prompts = [
        c["argv"][c["argv"].index("-p") + 1] for c in rg.calls() if "--resume" not in c["argv"]
    ]
    assert len(prompts) == JUDGE_VERDICTS and not any("forbidden" in p for p in prompts), (
        "the judge saw the quote"
    )
    rows = [r for r in results_of(rg)["rows"] if r["phase"] == "gate"]
    assert [r["removed"] for r in rows] == [1, 1, 1], rows
    assert "removed before the judge, per arm: R0 3, R 0" in printed, printed


def check_judge_flow(base: Path) -> None:
    judged = {"kind": "judge"}
    rg = rig(base, "jflow", judge=["NO", "YES", "NO"], plan={"default": ["fail"]})
    code, printed = run_quiet(rg.cfg, [point(rg.base, "jp", rule=judged)], gate_only=True)
    assert code == 0 and "gated in (gate only)" in printed, printed
    assert len(rg.replays()) == THREE and len(results_of(rg)["judge_calls"]) == JUDGE_VERDICTS
    rg = rig(base, "jdrop", judge=["YES", "NO"])
    code, printed = run_quiet(rg.cfg, [point(rg.base, "jp", rule=judged)])
    assert not rg.replays() and "scorer control failed" in printed, printed
    assert code == rr.EXIT_USAGE  # nothing usable
    rg = rig(base, "jdrop2", judge=["NO", "NO"])
    run_quiet(rg.cfg, [point(rg.base, "jp", rule=judged)])
    assert not rg.replays(), "the compliant message must be judged YES"


# --- reading ---------------------------------------------------------------------------------------------------


def canned(plan: list[tuple[str, int, int, int]]) -> tuple[list[rr.PointResult], list[rr.Row]]:
    """Points as (session, context, followed in R0, followed in R), 5 runs per arm."""
    results, rows = [], []
    for i, (session, context, r0, r) in enumerate(plan):
        name = f"p{i}"
        results.append(rr.PointResult(name, session, context, "compared", True))
        for arm, followed in (("R0", r0), ("R", r)):
            rows += [
                {"point": name, "phase": "compare", "arm": arm, "followed": k < followed}
                for k in range(5)
            ]
    return results, rows


def check_reading() -> None:
    def read(plan: list[tuple[str, int, int, int]]) -> str:
        return rr.reading(*canned(plan))

    ahead, level, behind = (1, 4), (2, 2), (3, 1)
    sessions = [f"s{i}" for i in range(6)]

    def plan(*cells: tuple[int, int]) -> list[tuple[str, int, int, int]]:
        return [(s, 100, a, b) for s, (a, b) in zip(sessions, cells, strict=False)]

    assert read(plan(*[ahead] * 6)).startswith("the lesson helps when fresh")
    assert read(plan(*[ahead] * 5, level)).startswith("the lesson helps when fresh")
    assert read(plan(*[ahead] * 4, level, level)).startswith("not decided at this size")
    assert read(plan(*[ahead] * 5, behind)).startswith("not decided at this size")
    assert read(plan(ahead, *[level] * 5)).startswith("the lesson does not help")
    assert read(plan(*[level] * 6)).startswith("the lesson does not help")
    assert read(plan(*[ahead] * 5)) == "fewer than 6 points: no verdict"
    twice = [
        ("a", 500, 2, 2),
        ("a", 100, 1, 4),
        ("b", 100, 1, 4),
        ("c", 100, 2, 2),
        ("d", 100, 2, 2),
        ("e", 9, 2, 2),
    ]
    results, rows = canned(twice)
    assert [r.name for r in rr._by_session(results)] == ["p1", "p2", "p3", "p4", "p5"]
    assert "ahead by 2 or more in 2 sessions" in rr.reading(results, rows), rr.reading(
        results, rows
    )
    assert (
        rr.reading([rr.PointResult("x", "s", 1, "gated out")], [])
        == "fewer than 6 points: no verdict"
    )


# --- wire capture ----------------------------------------------------------------------------------------------


def request(block: str, **over: Any) -> dict[str, Any]:
    body = {
        "system": "s",
        "tools": [{"name": "T"}],
        "messages": [{"role": "user", "content": "hi"}, {"role": "user", "content": block}],
    }
    return {**body, **over}


def check_compare_requests() -> None:
    r0 = replay.BLOCK.rstrip("\n") + "\n" + replay.REPEAT_NOTE + "\n"
    r = replay.block_r(r0, LESSON, "beta")
    lines, ok = rr.compare_requests(request(r0), request(r), LESSON)
    assert ok and lines == [
        "tools: same",
        "system: same",
        "messages: 2 and 2",
        "block printed again: in both",
        "difference: the lesson line only",
    ], lines
    two_lines = r + f"\n- {LESSON} again"  # more than the lesson line
    lines, ok = rr.compare_requests(request(r0), request(two_lines), LESSON)
    assert not ok and lines[-1].startswith("difference: ") and "only" not in lines[-1], lines
    moved = r0.replace("- one\n", f"- {LESSON}\n- one\n")  # the line goes elsewhere: still one line
    lines, ok = rr.compare_requests(request(r0), request(moved), LESSON)
    assert ok, lines
    no_newline = r0.replace("- one\n", f"- {LESSON}- one\n")
    twice = r + f"- {LESSON}\n"
    bad = [
        request(no_newline),
        request(twice),
        request(r.replace("three", "thre3")),  # same length, one character changed
        request(r.replace("alpha", "alpha ")),
        request(r, tools=[]),
        request(r, system="x"),
        request(r, messages=[*request(r)["messages"], {"role": "user", "content": "more"}]),
        request(r + " extra words"),
        request(r0),
    ]
    for other in bad:
        lines, ok = rr.compare_requests(request(r0), other, LESSON)
        assert not ok, lines
        assert not any(LESSON in line or "extra words" in line for line in lines), "text leaked"
    lines, ok = rr.compare_requests(request("no block"), request("no block here"), LESSON)
    assert not ok and "block printed again: missing in at least one" in lines


def check_capture(base: Path) -> None:
    rg = rig(base, "cap-run")
    pt = point(rg.base, "wire")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert rr.capture_point(rg.cfg, pt), out.getvalue()
    folder = rr.capture_folder(rg.cfg, pt)
    assert (
        folder / "capture-ok"
    ).exists() and "wire: difference: the lesson line only" in out.getvalue()
    assert {p.name for p in folder.glob("R0-*.json")} == {"R0-1.json", "R0-2.json"}, (
        "two POSTs per arm"
    )
    assert all(c["base"].startswith("http://127.0.0.1:") for c in rg.replays())
    assert {c["argv"][c["argv"].index("--max-budget-usd") + 1] for c in rg.replays()} == {
        f"{rr.CAPTURE_RESERVE_USD:.4f}"
    }, "a capture session has the small reserve, not a replay cap"
    assert LESSON not in out.getvalue(), "the lesson text was printed"
    rg.cfg.skip_capture_check = False
    code, printed = run_quiet(rg.cfg, [pt], gate_only=True)
    assert code == 0 and "gated" in printed, printed  # a captured point is no longer skipped
    other = rig(base, "cap-bad", capture="system")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert not rr.capture_point(other.cfg, pt)
    assert "system: differ" in out.getvalue()
    assert not (rr.capture_folder(other.cfg, pt) / "capture-ok").exists()


def check_capture_guards(base: Path) -> None:
    rg = rig(base, "cap-api", capture_cost=0.5)
    pt = point(rg.base, "wire")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = rr.capture_all(rg.cfg, [pt, point(rg.base, "second")])
    assert code == rr.EXIT_CHANGED and "capture reached the API: 0.5000" in out.getvalue(), out
    assert len(rg.replays()) == 1, "the capture went on after reaching the API"
    assert not (rr.capture_folder(rg.cfg, pt) / "capture-ok").exists()
    rg = rig(base, "cap-env")
    rg.cfg.env = {**rg.cfg.env, "XDG_CONFIG_HOME": "/somewhere/else"}
    try:
        rr.capture_point(rg.cfg, point(rg.base, "wire"))
    except rr.Stop as stop:
        assert stop.code == rr.EXIT_CHANGED and "isolation" in stop.reason, stop.reason
    else:
        raise AssertionError("a capture ran without the isolation check")
    assert not rg.replays(), "a session started with a broken isolation"


def self_check() -> int:
    base = Path(tempfile.mkdtemp(prefix="lessons-replay-check-")).resolve()
    if base.is_relative_to(replay.REPO):
        shutil.rmtree(base, ignore_errors=True)
        print("self-check failed: the work folder is inside the repository")
        return 1
    try:
        check_launch(base)
        check_launch_failures(base)
        check_gate_and_compare(base)
        check_error_rerun(base)
        check_cap(base)
        check_kill_rule(base)
        check_void_gate(base)
        check_failing_point(base)
        check_arguments()
        check_owner_guard(base)
        check_skips(base)
        check_judge_answers(base)
        check_judge_prompt()
        check_judge_blind(base)
        check_judge_flow(base)
        check_reading()
        check_compare_requests()
        check_capture(base)
        check_capture_guards(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("self-check passed")
    return 0
