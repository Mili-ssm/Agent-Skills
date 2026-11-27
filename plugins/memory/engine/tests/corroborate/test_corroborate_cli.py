"""`bin/mem-corroborate`: the commands, the automatic run's options and an engine that cannot load."""

import argparse
import json
import shutil
import sys

import pytest
from core import jobs
from corroborate import cli as corroborate_cli
from corroborate import digest as corroborate_digest
from corroborate import reword as corroborate_reword
from corroborate import run as corroborate_run
from corroborate_world import (
    CORR,
    NARROW,
    NEW_WORDING,
    OLD_WORDING,
    OPTION,
    PLUGIN,
    by_claim,
    calls,
    log_lines,
    model,
    reword,
    reword_answers,
    reword_state,
    run,
    w,
    worse_one,
)

__all__ = ["w"]  # re-exported: pytest finds the fixture in this module by its name

USAGE_EXIT = 2  # exit code for a refused command line

# ---- the option auto_reword: the step in the automatic run ---------------------------------------------------------

REWORD_OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_REWORD"


def test_auto_runs_reword_only_with_the_option(w, monkeypatch):
    worse_one(w)
    model(w, [])
    reword_answers(w, monkeypatch)
    for env in ({}, {REWORD_OPTION: "false"}, {REWORD_OPTION: "1"}, {REWORD_OPTION: "TRUE"}):
        done = run(w, cmd="auto", env={OPTION: "true", **env})
        assert done.returncode == 0 and not done.stdout and not done.stderr
        assert (
            not any("reword" in x for x in log_lines(w))
            and by_claim(w, NARROW).short == OLD_WORDING
        )
        assert not (w.cdir / "reword-attempts.json").exists()
    off = [{k: v for k, v in x.items() if k not in {"t", "ms"}} for x in log_lines(w)]
    done = run(w, cmd="auto", env={OPTION: "true", REWORD_OPTION: "true"})
    assert done.returncode == 0 and not done.stdout and not done.stderr
    lines = log_lines(w)
    (reworded,) = [x for x in lines if "reword" in x]
    assert lines[-1] is reworded and "fill" in lines[-2] and reworded["reword"]["written"] == 1
    assert isinstance(reworded["ms"], int) and reworded["t"]
    assert by_claim(w, NARROW).short == NEW_WORDING
    assert [{k: v for k, v in x.items() if k not in {"t", "ms"}} for x in lines[: len(off)]] == off


def test_auto_skips_reword_when_loaded_rules_are_off(w, monkeypatch):
    worse_one(w)
    model(w, [])
    reword_answers(w, monkeypatch)
    for env in ({"MEM_LOADED_RULES": "off"}, {"CLAUDE_PLUGIN_OPTION_LOADED_RULES": "false"}):
        done = run(w, cmd="auto", env={OPTION: "true", REWORD_OPTION: "true", **env})
        assert done.returncode == 0 and not done.stdout and not done.stderr
        assert (
            not any("reword" in x for x in log_lines(w))
            and by_claim(w, NARROW).short == OLD_WORDING
        )


def test_auto_does_not_reword_without_auto_capture(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    done = run(w, cmd="auto", env={REWORD_OPTION: "true"})
    assert done.returncode == 0 and log_lines(w) == [] and by_claim(w, NARROW).short == OLD_WORDING


def test_a_failure_in_reword_does_not_fail_auto(w, monkeypatch):
    worse_one(w)
    model(w, [])

    def boom(*_args, **_kw):
        raise RuntimeError("the step broke")

    monkeypatch.setattr(corroborate_reword, "reword_auto", boom)
    monkeypatch.setenv(OPTION, "true")
    monkeypatch.setenv(REWORD_OPTION, "true")
    monkeypatch.setattr(sys, "argv", ["mem-corroborate", "auto", "--claude", str(w.fake)])
    assert corroborate_cli.cmd_auto(argparse.Namespace(claude=str(w.fake))) == 0
    lines = log_lines(w)
    assert any("fill" in x for x in lines) and not any("reword" in x for x in lines)


# ---- the option rules_layout: the digest step in the automatic run -------------------------------------------------

LAYOUT_OPTION = "CLAUDE_PLUGIN_OPTION_RULES_LAYOUT"


def test_auto_runs_digest_only_with_the_layout(w, monkeypatch):
    worse_one(w)
    model(w, [])
    for env in ({}, {LAYOUT_OPTION: "flat"}, {LAYOUT_OPTION: "grouped"}, {LAYOUT_OPTION: "DIGEST"}):
        done = run(w, cmd="auto", env={OPTION: "true", **env})
        assert done.returncode == 0 and not done.stdout and not done.stderr
        assert (
            not any("digest" in x for x in log_lines(w))
            and not (w.data / "rules-digest.json").exists()
        )
    for off in ({"MEM_LOADED_RULES": "off"}, {"CLAUDE_PLUGIN_OPTION_LOADED_RULES": "false"}):
        done = run(w, cmd="auto", env={OPTION: "true", LAYOUT_OPTION: "digest", **off})
        assert done.returncode == 0 and not any("digest" in x for x in log_lines(w))
    done = run(w, cmd="auto", env={OPTION: "true", LAYOUT_OPTION: "digest"})
    assert done.returncode == 0 and not done.stdout and not done.stderr
    lines = log_lines(w)
    (digested,) = [x for x in lines if "digest" in x]
    assert lines[-1] is digested and "fill" in lines[-2] and isinstance(digested["digest"], dict)
    assert isinstance(digested["ms"], int) and digested["t"]


def test_a_failure_in_digest_does_not_fail_auto(w, monkeypatch):
    worse_one(w)
    model(w, [])

    def boom(*_args, **_kw):
        raise RuntimeError("the step broke")

    monkeypatch.setattr(corroborate_digest, "digest_auto", boom)
    monkeypatch.setenv(OPTION, "true")
    monkeypatch.setenv(LAYOUT_OPTION, "digest")
    monkeypatch.setattr(sys, "argv", ["mem-corroborate", "auto", "--claude", str(w.fake)])
    assert corroborate_cli.cmd_auto(argparse.Namespace(claude=str(w.fake))) == 0
    lines = log_lines(w)
    assert any("fill" in x for x in lines) and not any("digest" in x for x in lines)


def test_auto_without_the_layout_is_as_before(w, monkeypatch):
    worse_one(w)
    model(w, [])
    reword_answers(w, monkeypatch)
    env = {OPTION: "true", REWORD_OPTION: "true"}
    run(w, cmd="auto", env=env)
    before = [{k: v for k, v in x.items() if k not in {"t", "ms"}} for x in log_lines(w)]
    store = by_claim(w, NARROW).short
    assert [list(x) for x in before][-1] == ["reword"] and store == NEW_WORDING
    run(w, cmd="auto", env=env)
    after = [{k: v for k, v in x.items() if k not in {"t", "ms"}} for x in log_lines(w)]
    assert after[: len(before)] == before and not any("digest" in x for x in after)
    assert by_claim(w, NARROW).short == store and not (w.data / "rules-digest.json").exists()


def test_plugin_json_has_the_option_off():
    config = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["userConfig"]
    assert (
        config["auto_reword"]["type"] == "boolean" and config["auto_reword"].get("default") is False
    )


def test_reword_sheet_is_refused_inside_a_repository(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    repo = w.tmp / "repo"
    (repo / ".git").mkdir(parents=True)
    done = run(
        w, "--every", "--dry-run", "--sheet", str(repo / "sheet.md"), cmd="reword", mode="never"
    )
    assert (
        done.returncode == USAGE_EXIT and "repository" in done.stderr and "--sheet" in done.stderr
    )
    assert calls(w) == 0 and not (repo / "sheet.md").exists()


class _Run:
    def __init__(self, code):
        self.returncode, self.stdout, self.stderr = code, "", "fake"


def _edit_exits(monkeypatch, code):
    """Every `mem memory edit --reworded` call ends with `code` (None: could not run) and writes nothing."""
    real = corroborate_run.Applier.mem

    def mem(self, args, *a, **kw):
        if "--reworded" in args:
            return None if code is None else _Run(code)
        return real(self, args, *a, **kw)

    monkeypatch.setattr(corroborate_run.Applier, "mem", mem)


@pytest.mark.parametrize("code", [None, 1, 2, 3])
def test_a_failed_edit_spends_no_attempt(w, monkeypatch, code):
    worse_one(w)
    reword_answers(w, monkeypatch)
    _edit_exits(monkeypatch, code)
    before = by_claim(w, NARROW)
    for _ in range(2):
        result = reword(w)
        assert (
            result["failed_edits"],
            result["written"],
            result["refused_code"],
            result["no_proposal"],
        ) == (1, 0, 0, 0)
    assert by_claim(w, NARROW) == before and by_claim(w, NARROW).reword_failed is None
    assert reword_state(w)["lessons"] == {}


@pytest.mark.parametrize("code", [4])
def test_a_refused_edit_still_spends_an_attempt(w, monkeypatch, code):
    worse_one(w)
    reword_answers(w, monkeypatch)
    _edit_exits(monkeypatch, code)
    result = reword(w)
    assert (result["refused_code"], result["failed_edits"], result["written"]) == (1, 0, 0)
    (entry,) = reword_state(w)["lessons"].values()
    assert entry["count"] == 1 and not entry["spent"]


def test_an_unwritable_sheet_does_not_fail_an_applied_run(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    result = reword(w, sheet=w.tmp / "no-such-folder" / "sheet.md")
    assert result["written"] == 1 and by_claim(w, NARROW).short == NEW_WORDING
    assert "sheet" in result["stopped"] and result["stopped"] != "the step failed"
    assert reword_state(w)["lessons"]


# ---- an engine that cannot load: `auto` still reports, `status` and `ack` still work ---------------------------------

ENGINE_LOG_KEYS = [
    "t",
    "lessons",
    "groups",
    "proposed",
    "verified",
    "dropped",
    "written",
    "sightings",
    "links",
    "merges",
    "refused",
    "failed_actions",
    "cases",
    "skipped",
    "cost",
    "failed",
    "ms",
]


def test_auto_with_an_engine_that_cannot_load_writes_its_failed_status(w):
    plug = w.tmp / "plug-no-yaml"
    (plug / "bin").mkdir(parents=True)
    launcher = plug / "bin" / "mem-corroborate"
    shutil.copy(CORR, launcher)
    (plug / "engine").symlink_to(PLUGIN / "engine")
    stub = w.tmp / "stub"
    stub.mkdir()
    (stub / "yaml.py").write_text('raise ImportError("no yaml in this test")\n')
    env = {"PYTHONPATH": str(stub), OPTION: "true"}
    done = run(w, cmd="auto", env=env, corr=launcher)
    assert done.returncode == 0 and not done.stdout and not done.stderr
    status = jobs.read_json(w.cdir / "status.json")
    assert status["state"] == "failed" and status["failure"]["reason"] == "engine import error"
    log = [json.loads(x) for x in (w.cdir / "log.jsonl").read_text().splitlines()]
    assert (
        len(log) == 1
        and list(log[0]) == ENGINE_LOG_KEYS
        and log[0]["failed"] == "engine import error"
    )
    shown = run(w, cmd="status", claude=False, env=env, corr=launcher)
    assert shown.returncode == 0 and "unacknowledged failure: engine import error" in shown.stdout
    assert run(w, cmd="ack", claude=False, env=env, corr=launcher).returncode == 0
    shown = run(w, cmd="status", claude=False, env=env, corr=launcher)
    assert shown.returncode == 0 and "unacknowledged" not in shown.stdout
    refused = run(w, "--dry-run", "--out", str(w.tmp / "o.json"), env=env, corr=launcher)
    assert refused.returncode == 1 and "cannot load the engine" in refused.stderr
