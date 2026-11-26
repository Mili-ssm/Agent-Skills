"""config.py: the store precedence and the config folder, on explicit environments."""

from pathlib import Path

import config


def _marked(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / config.STORE_MARKER).write_text("format: 1\n", encoding="utf-8")
    return folder


def test_config_dir():
    assert config.config_dir({"XDG_CONFIG_HOME": "/c", "HOME": "/h"}) == Path("/c/agent-memory")
    assert config.config_dir({"HOME": "/h"}) == Path("/h/.config/agent-memory")
    assert config.config_dir({"XDG_CONFIG_HOME": "", "HOME": ""}) is None
    assert config.config_dir({}) is None


def test_config_lines(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert config.config_lines(env, "store") == []
    (tmp_path / "agent-memory").mkdir()
    (tmp_path / "agent-memory" / "store").write_text("a\n\nb\n", encoding="utf-8")
    assert config.config_lines(env, "store") == ["a", "", "b"]
    (tmp_path / "agent-memory" / "bad").write_bytes(b"\xff\xfe")
    assert config.config_lines(env, "bad") == []
    assert config.config_lines({}, "store") == []


def test_default_store_path_does_not_check_existence():
    assert config.default_store_path({"XDG_DATA_HOME": "/d", "HOME": "/h"}) == Path(
        "/d/agent-memory/store"
    )
    assert config.default_store_path({"HOME": "/h"}) == Path("/h/.local/share/agent-memory/store")
    assert config.default_store_path({}) is None


def test_default_store_needs_the_marker(tmp_path):
    env = {"XDG_DATA_HOME": str(tmp_path)}
    folder = tmp_path / "agent-memory" / "store"
    assert config.default_store(env) is None
    folder.mkdir(parents=True)
    assert config.default_store(env) is None
    _marked(tmp_path / "other")
    (folder / config.STORE_MARKER).write_text("format: 1\n", encoding="utf-8")
    assert config.default_store(env) == folder
    assert config.default_store({}) is None


def test_precedence(tmp_path):
    cfg = tmp_path / "cfg" / "agent-memory"
    cfg.mkdir(parents=True)
    (cfg / "store").write_text("/from/file\n", encoding="utf-8")
    default = _marked(tmp_path / "share" / "agent-memory" / "store")
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_DATA_HOME": str(tmp_path / "share")}
    assert config.store_source("/r", {**env, "MEM_STORE": "/m"}) == "--root"
    assert config.resolve_store("/r", {**env, "MEM_STORE": "/m"}) == Path("/r")
    assert config.store_source(None, {**env, "MEM_STORE": "/m"}) == "MEM_STORE"
    assert config.resolve_store(None, {**env, "MEM_STORE": "/m"}) == Path("/m")
    assert config.store_source(None, {**env, "MEM_STORE": ""}) == "config file"
    assert config.resolve_store(None, env) == Path("/from/file")
    (cfg / "store").write_text("\n/ignored\n", encoding="utf-8")  # only the first line counts
    assert config.store_source(None, env) == "default"
    assert config.resolve_store(None, env) == default


def test_unmarked_default_and_homeless_environments_have_no_store(tmp_path):
    (tmp_path / "agent-memory" / "store").mkdir(parents=True)
    assert config.resolve_store(None, {"XDG_DATA_HOME": str(tmp_path)}) is None
    assert config.store_source(None, {}) is None
    assert config.resolve_store(None, {"HOME": ""}) is None


def test_config_path_is_stripped_and_tilde_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    cfg = tmp_path / "agent-memory"
    cfg.mkdir()
    (cfg / "store").write_text("  ~/x  \n", encoding="utf-8")
    assert config.resolve_store(None, {"XDG_CONFIG_HOME": str(tmp_path)}) == Path("/h/x")
