"""On Codex the hooks read plugin options from one file per option (ADR 0038)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[3]
HELPER = PLUGIN / "hooks" / "codex-options.sh"


def _run(tmp_path, var, files=None, env=None, xdg=True):
    """Source the helper, call codex_options and print `var` (or `unset`)."""
    home = tmp_path / "home"
    cfg = (tmp_path / "xdg" if xdg else home / ".config") / "agent-memory"
    cfg.mkdir(parents=True, exist_ok=True)
    for name, text in (files or {}).items():
        (cfg / name).write_text(text)
    e = {"PATH": os.environ["PATH"], "HOME": str(home), **(env or {})}
    if xdg:
        e["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    script = f'. "{HELPER}"; codex_options; echo "${{{var}-unset}}"'
    out = subprocess.run(["bash", "-c", script], env=e, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_file_sets_unset_option(tmp_path):
    assert _run(tmp_path, "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE", {"auto_capture": "true\n"}) == "true"


def test_set_variable_wins(tmp_path):
    got = _run(
        tmp_path,
        "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE",
        {"auto_capture": "true\n"},
        {"CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE": "false"},
    )
    assert got == "false"


def test_missing_file_leaves_unset(tmp_path):
    assert _run(tmp_path, "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE") == "unset"


def test_whitespace_stripped(tmp_path):
    assert (
        _run(
            tmp_path, "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE", {"auto_capture": "  true \t\nignored\n"}
        )
        == "true"
    )


def test_xdg_config_home_honoured(tmp_path):
    (tmp_path / "home" / ".config" / "agent-memory").mkdir(parents=True)
    (tmp_path / "home" / ".config" / "agent-memory" / "auto_capture").write_text("from-home\n")
    assert (
        _run(tmp_path, "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE", {"auto_capture": "from-xdg\n"})
        == "from-xdg"
    )
    assert _run(tmp_path / "b", "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE", xdg=False) == "unset"


def test_option_list_matches_plugin_json():
    declared = set(
        json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["userConfig"]
    ) - {"store", "runner"}
    out = subprocess.run(
        ["bash", "-c", f'. "{HELPER}"; echo $CODEX_OPTION_NAMES'],
        capture_output=True,
        text=True,
        check=True,
    )
    assert set(out.stdout.split()) == declared


def _session_index(tmp_path, host):
    """session-index.sh with a stub `mem` that prints MEM_LOADED_RULES; the option file says `false`."""
    root = tmp_path / "plug"
    shutil.copytree(PLUGIN / "hooks", root / "hooks")
    (root / "bin").mkdir()
    mem = root / "bin" / "mem"
    mem.write_text('#!/bin/sh\necho "RULES=${MEM_LOADED_RULES-unset}"\n')
    mem.chmod(0o755)
    cfg = tmp_path / "xdg" / "agent-memory"
    cfg.mkdir(parents=True)
    (cfg / "loaded_rules").write_text("false\n")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
    }
    if host:
        env["MEM_HOST"] = host
    out = subprocess.run(
        ["bash", str(root / "hooks" / "session-index.sh")],
        env=env,
        input="{}",
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout


def test_hook_reads_files_only_on_codex(tmp_path):
    assert "RULES=off" in _session_index(tmp_path / "c", "codex")
    assert "RULES=unset" in _session_index(tmp_path / "n", None)


def test_missing_helper_never_fails_hook(tmp_path):
    root = tmp_path / "plug"
    shutil.copytree(PLUGIN / "hooks", root / "hooks")
    (root / "hooks" / "codex-options.sh").unlink()
    r = subprocess.run(
        ["bash", str(root / "hooks" / "subagent-start.sh")],
        env={"PATH": os.environ["PATH"], "MEM_HOST": "codex"},
        input="{}",
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and "memory:" in r.stdout
