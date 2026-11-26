"""plugins/agent-skills/hooks/offload-policy.sh: prints the offload table at session start, or stays silent."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_DIR = ROOT / "plugins" / "agent-skills" / "hooks"
SCRIPT = HOOK_DIR / "offload-policy.sh"
COPY = HOOK_DIR / "offload-policy.md"
SOURCE = ROOT / "user-config" / "offload-policy.md"
HEADING = "## Offload policy (main conversation only)"


def run(
    tmp_path: Path,
    script: Path = SCRIPT,
    *,
    unset_home: bool = False,
    unset_config: bool = False,
    **env: str,
) -> str:
    """Run the script with a clean environment; assert it exits 0 and return its standard output."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if not unset_home:
        base |= {"HOME": str(home)}
        if not unset_config:
            base["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
    result = subprocess.run(
        [str(script)],
        env=base | env,
        capture_output=True,
        text=True,
        input="",
        check=False,
    )
    assert result.returncode == 0
    return result.stdout


def write_claude_md(tmp_path: Path, text: str, folder: str = ".claude") -> None:
    config = tmp_path / "home" / folder
    config.mkdir(parents=True, exist_ok=True)
    (config / "CLAUDE.md").write_text(text, encoding="utf-8")


def test_prints_the_policy_verbatim(tmp_path: Path) -> None:
    assert run(tmp_path) == COPY.read_text(encoding="utf-8")


def test_option_false_prints_nothing(tmp_path: Path) -> None:
    assert not run(tmp_path, CLAUDE_PLUGIN_OPTION_OFFLOAD_POLICY="false")


def test_eval_marker_prints_nothing(tmp_path: Path) -> None:
    assert not run(tmp_path, CLAUDE_CODE_EVAL_CONFINED="1")


def test_eval_marker_with_switch_on_prints(tmp_path: Path) -> None:
    out = run(tmp_path, CLAUDE_CODE_EVAL_CONFINED="1", EVAL_OFFLOAD_HOOK="on")
    assert out == COPY.read_text(encoding="utf-8")


def test_eval_marker_with_other_switch_value_prints_nothing(tmp_path: Path) -> None:
    for value in ("off", "true", "ON", ""):
        assert not run(tmp_path, CLAUDE_CODE_EVAL_CONFINED="1", EVAL_OFFLOAD_HOOK=value)


def test_skips_when_claude_md_holds_the_heading(tmp_path: Path) -> None:
    write_claude_md(tmp_path, f"# Mine\n\n{HEADING}\n\ntext\n")
    assert not run(tmp_path)


def test_prints_when_claude_md_lacks_the_heading(tmp_path: Path) -> None:
    write_claude_md(tmp_path, f"# Mine\n\nsee {HEADING} elsewhere\n")  # not an exact line
    assert run(tmp_path) == COPY.read_text(encoding="utf-8")


def test_skips_by_home_when_config_dir_is_unset(tmp_path: Path) -> None:
    write_claude_md(tmp_path, f"{HEADING}\n")
    assert not run(tmp_path, unset_config=True)


def test_config_dir_wins_over_home(tmp_path: Path) -> None:
    other = tmp_path / "home" / "other"
    # heading only under $HOME/.claude, CLAUDE_CONFIG_DIR points to a folder without it: prints
    write_claude_md(tmp_path, f"{HEADING}\n")
    write_claude_md(tmp_path, "# Mine\n", "other")
    assert run(tmp_path, CLAUDE_CONFIG_DIR=str(other)) == COPY.read_text(encoding="utf-8")
    # reverse placement: heading only in the configured folder: silent
    write_claude_md(tmp_path, "# Mine\n")
    write_claude_md(tmp_path, f"{HEADING}\n", "other")
    assert not run(tmp_path, CLAUDE_CONFIG_DIR=str(other))


def test_empty_eval_marker_counts_as_set(tmp_path: Path) -> None:
    assert not run(tmp_path, CLAUDE_CODE_EVAL_CONFINED="")


def test_prints_without_home(tmp_path: Path) -> None:
    assert run(tmp_path, unset_home=True) == COPY.read_text(encoding="utf-8")


def test_missing_policy_file_is_silent(tmp_path: Path) -> None:
    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copy(SCRIPT, lone / "offload-policy.sh")
    assert not run(tmp_path, lone / "offload-policy.sh")


def test_generated_copy_matches_source() -> None:
    assert COPY.read_bytes() == SOURCE.read_bytes()
