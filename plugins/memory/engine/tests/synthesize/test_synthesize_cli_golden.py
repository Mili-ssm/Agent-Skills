"""Golden behavior of the synthesis command lines (`mem-synthesize`, `mem-auto`, `mem-settle`), pinned at base of the
`engine/synthesize/` split: `--help` text, a bad argument, the two dry runs and the failure of a broken engine.
Literal expected values; they must pass unchanged after every step of the split."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[3]
BIN = PLUGIN / "bin"
MEM = PLUGIN / "engine" / "mem.py"
A = "../knowledge/computing/attention-replaces-recurrence.md"
B = "../literature/computing/2017-vaswani-attention.md"
ALPHA = (
    f"First plain sentence   here. Second one is backed.[a]({A}) Third has [an inline one]({B}) in it.\n\n"
    f"Sources: [attention]({A}), [vaswani]({B}), experience 2026-11-17\n"
)
USAGE_BAD_BUDGET = (
    "usage: mem-synthesize [-h] [--backfill [s:HANDLE ...]] [--topic TOPIC]\n"
    "                      [--budget BUDGET] [--no-references] [--dry-run]\n"
    "                      [--store STORE] [--claude CLAUDE]\n"
    "                      [--runner {claude,codex}] [--self-check]\n"
    "mem-synthesize: error: argument --budget: invalid float value: 'abc'\n"
)
HELP_SYNTHESIZE = """\
usage: mem-synthesize [-h] [--backfill [s:HANDLE ...]] [--topic TOPIC]
                      [--budget BUDGET] [--no-references] [--dry-run]
                      [--store STORE] [--claude CLAUDE]
                      [--runner {claude,codex}] [--self-check]

mem-synthesize: write syntheses for topics that have none, quietly, one
headless session per step.

options:
  -h, --help            show this help message and exit
  --backfill [s:HANDLE ...]
                        add inline references to existing syntheses (the named
                        ones, or all) with one read-only session each
  --topic TOPIC         topic id (repeatable; default: the topics `mem curate
                        --notes` lists without a synthesis)
  --budget BUDGET       USD; no new topic starts past it
  --no-references       skip the last step of a topic (adding inline
                        references with the --backfill session)
  --dry-run             list the topics and the estimated cost; run nothing
  --store STORE         default: the store `mem` resolves (MEM_STORE, else the
                        default)
  --claude CLAUDE
  --runner {claude,codex}
                        claude or codex; outranks MEM_RUNNER, the runner
                        config file and the plugin option (default claude)
  --self-check          no model: prove the parsers and a run with a fake
                        claude
"""
HELP_AUTO = """\
usage: mem-auto [-h] [--store STORE] [--claude CLAUDE]
                [--runner {claude,codex}] [--budget BUDGET]
                [--threshold THRESHOLD] [--self-check]
                [{run,status,ack,due}]

mem-auto: one bounded curation run in the background, started by the
SessionEnd hook when the plugin option

positional arguments:
  {run,status,ack,due}

options:
  -h, --help            show this help message and exit
  --store STORE         default: the store `mem` resolves (MEM_STORE, else the
                        default)
  --claude CLAUDE
  --runner {claude,codex}
                        claude or codex; outranks MEM_RUNNER, the runner
                        config file and the plugin option (default claude)
  --budget BUDGET       USD per run (default: the option auto_curation_budget,
                        else 2.0)
  --threshold THRESHOLD
                        new records that start a run (default: the option
                        auto_curation_threshold, else 10)
  --self-check          no model: prove the lock, the folder mode and the
                        gates
"""
HELP_SETTLE = """\
usage: mem-settle [-h] [--store STORE] [--claude CLAUDE] [--budget BUDGET]
                  [--runner {claude,codex}] [--minutes MINUTES] [--dry-run]
                  [--self-check]
                  [{run,status,ack}]

mem-settle: one bounded settling run in the background (plan
2026-11-17-memory-seamless, stage W).

positional arguments:
  {run,status,ack}

options:
  -h, --help            show this help message and exit
  --store STORE         default: the store `mem` resolves (MEM_STORE, else the
                        default)
  --claude CLAUDE
  --budget BUDGET       USD per run (default 0.25)
  --runner {claude,codex}
                        claude or codex; outranks MEM_RUNNER, the runner
                        config file and the plugin option (default claude)
  --minutes MINUTES     a run starts only when the last apply ended more than
                        this long ago (default 30; 0 at the end of a session)
  --dry-run             say whether `run` would start; change nothing
  --self-check          no model: prove the lock, the gates and the tool list
"""
DRY_TOPICS = (
    "mem-synthesize dry run: 2 topics: one, two; each ends with a reference step (--no-references skips it); "
    "estimated cost 1.10 USD (budget 3.00)\n"
)
DRY_BACKFILL = (
    "s:attention: alpha (1 of 3 units without reference)\n"
    "mem-synthesize --backfill dry run: 1 syntheses (0 skipped); estimated cost 0.05 USD (budget 3.00)\n"
)


def _env(**extra: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"FORCE_COLOR", "PYTHON_COLORS", "MEM_STORE"}
    }
    env.update(NO_COLOR="1", COLUMNS="80", **extra)
    return env


def _command(script: str) -> list[str]:
    """The uv launchers run through `engine/run.py` under the test Python instead."""
    if script in {"mem-synthesize", "mem-auto", "mem-settle"}:
        return [sys.executable, str(PLUGIN / "engine" / "run.py"), "--bin", script]
    return [sys.executable, str(BIN / script)]


def _run(script: str, *args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [*_command(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env or _env(),
    )


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("mem-synthesize", HELP_SYNTHESIZE),
        ("mem-auto", HELP_AUTO),
        ("mem-settle", HELP_SETTLE),
    ],
)
def test_help_text(script, expected):
    done = _run(script, "--help")
    assert (done.returncode, done.stdout, done.stderr) == (0, expected, "")


def test_a_bad_argument_prints_usage_and_exits_2():
    done = _run("mem-synthesize", "--budget", "abc")
    assert (done.returncode, done.stdout, done.stderr) == (2, "", USAGE_BAD_BUDGET)


def _mem(store: Path, *args: str, stdin: str = "") -> None:
    done = subprocess.run(
        [sys.executable, str(MEM), "--root", str(store), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr


@pytest.fixture
def synthesis_store(hub_root: Path) -> Path:
    summary = hub_root.parent / "summary.md"
    summary.write_text("How attention works here.\n", encoding="utf-8")
    _mem(
        hub_root,
        *("synthesis", "new", "--title", "Attention", "--topics", "ml", "--slug", "attention"),
        *("--summary-file", str(summary)),
    )
    _mem(
        hub_root,
        *("synthesis", "add", "s:attention", "--section", "Alpha", "--body-file", "-"),
        stdin=ALPHA,
    )
    return hub_root


def test_topic_dry_run_lists_the_topics_and_the_estimate(synthesis_store):
    done = _run(
        "mem-synthesize",
        "--store",
        str(synthesis_store),
        "--topic",
        "one",
        "--topic",
        "two",
        "--dry-run",
    )
    assert (done.returncode, done.stdout, done.stderr) == (0, DRY_TOPICS, "")


def test_backfill_dry_run_lists_the_parts_and_the_estimate(synthesis_store):
    done = _run("mem-synthesize", "--store", str(synthesis_store), "--backfill", "--dry-run")
    assert (done.returncode, done.stdout, done.stderr) == (0, DRY_BACKFILL, "")


@pytest.fixture
def stub_yaml(tmp_path: Path) -> Path:
    stub = tmp_path / "stub" / "yaml"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text("raise ImportError('stub: no yaml')\n", encoding="utf-8")
    return stub.parent


@pytest.mark.parametrize(
    ("script", "args"),
    [
        ("mem-synthesize", ["--help"]),
        ("mem-auto", ["status"]),
        ("mem-settle", ["--help"]),
    ],
)
def test_a_broken_engine_exits_1_before_argparse_and_writes_no_state(
    script, args, stub_yaml, tmp_path
):
    data = tmp_path / "state"
    data.mkdir()
    done = _run(script, *args, env=_env(PYTHONPATH=str(stub_yaml), MEM_DATA=str(data)))
    assert (done.returncode, done.stdout) == (1, "")
    assert "stub: no yaml" in done.stderr  # the engine load failed, not something else
    assert list(data.iterdir()) == []
