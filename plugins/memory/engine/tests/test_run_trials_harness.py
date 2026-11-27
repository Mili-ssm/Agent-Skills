"""The synthesis trial harness (`evals/synthesis/run_trials.py`) calls `synthesize.topics.add_references` with the
keyword options that function declares; a stub records them, so no model session runs."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

HARNESS = Path(__file__).resolve().parents[2] / "evals" / "synthesis" / "run_trials.py"


def _load_harness() -> Any:
    spec = importlib.util.spec_from_file_location("run_trials_under_test", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reference_backfill_passes_the_options_by_keyword(tmp_path):
    harness = _load_harness()
    seen = {}

    def add_references(*args, **options):
        seen["args"] = args
        seen["options"] = options
        return {"status": "ok", "proposed": 3, "applied": 2, "refused": 1, "none": 0, "cost": 0.25}

    # The real declaration, read before the stub replaces the loader.
    options_type = harness.load_synthesize().ReferenceOptions
    harness.load_synthesize = lambda: SimpleNamespace(add_references=add_references)
    row = harness.reference_backfill("claude", tmp_path, {"A": "b"}, "demo")

    # The names sent are the ones add_references declares, and every required one is sent.
    assert set(seen["options"]) <= set(options_type.__annotations__)
    assert options_type.__required_keys__ <= set(seen["options"])

    assert seen["args"] == (
        "claude",
        {"A": "b"},
        tmp_path / "references",
        tmp_path / "store",
        "demo",
    )
    settings = tmp_path / "settings-references.json"
    assert seen["options"]["settings"] == settings
    assert json.loads(settings.read_text(encoding="utf-8")) == {"disableAllHooks": True}
    assert seen["options"]["budget_left"] == harness.SESSION_CAP_USD
    seen["options"]["log"]("a line")
    assert (tmp_path / "references-log.txt").read_text(encoding="utf-8") == "a line\n"
    assert (row["status"], row["proposed"], row["applied"], row["ran"]) == ("ok", 3, 2, True)


def test_clean_keeps_the_work_folder_when_diag_dir_is_set(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "trial_env_under_test", Path(__file__).resolve().parents[2] / "evals" / "trial_env.py"
    )
    assert spec is not None and spec.loader is not None
    trial_env = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trial_env)

    work = tmp_path / "w"
    (work / "job").mkdir(parents=True)
    (work / "job" / "place.jsonl").write_text("raw")
    (work / "home").mkdir()
    (work / "home" / "auth.json").write_text("secret")
    monkeypatch.setenv("MEM_DIAG_DIR", str(tmp_path / "diag"))
    trial_env.clean(work)
    assert not work.exists()
    assert (tmp_path / "diag" / "w" / "job" / "place.jsonl").read_text() == "raw"
    assert not (tmp_path / "diag" / "w" / "home").exists()
