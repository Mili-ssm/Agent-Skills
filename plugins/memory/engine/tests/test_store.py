import json
from pathlib import Path

import pytest
from conftest import usage_log_path

import mem


def test_resolve_root_order(tmp_path):
    cfg = tmp_path / "cfg" / "agent-memory"; cfg.mkdir(parents=True)
    (cfg / "store").write_text("/from/file\n")
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "MEM_STORE": "/from/env"}
    assert mem.resolve_root("/from/cli", env) == Path("/from/cli")
    assert mem.resolve_root(None, env) == Path("/from/env")
    assert mem.resolve_root(None, {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "MEM_STORE": ""}) == Path("/from/file")
    assert mem.resolve_root(None, {"HOME": str(tmp_path / "nohome")}) is None


def test_resolve_root_keeps_spaces(tmp_path):
    cfg = tmp_path / ".config" / "agent-memory"; cfg.mkdir(parents=True)
    (cfg / "store").write_text("/a path/with spaces\n")
    assert mem.resolve_root(None, {"HOME": str(tmp_path)}) == Path("/a path/with spaces")


def test_data_dir(tmp_path):
    assert mem.data_dir({"MEM_DATA": "/d"}) == Path("/d")
    assert mem.data_dir({"XDG_STATE_HOME": "/s"}) == Path("/s/agent-memory")
    assert mem.data_dir({"HOME": "/h"}) == Path("/h/.local/state/agent-memory")
    assert mem.data_dir({}) is None
    assert mem.data_dir({"MEM_DATA": "", "XDG_STATE_HOME": "", "HOME": ""}) is None


def _files(folder):
    return sorted(p.relative_to(folder) for p in folder.rglob("*"))


def test_log_usage_without_data_dir_writes_nothing(hub_root, monkeypatch):
    monkeypatch.chdir(hub_root)
    before = _files(hub_root)
    mem.log_usage(hub_root, {"cmd": "search"}, env={}, cwd=hub_root)
    assert _files(hub_root) == before


def test_log_usage_never_writes_inside_the_store(hub_root, tmp_path):
    before = _files(hub_root)
    mem.log_usage(hub_root, {"cmd": "search"}, env={"MEM_DATA": str(hub_root / "data")}, cwd=tmp_path)
    assert _files(hub_root) == before


def test_stats_counts_zero_entries_without_data_dir(hub_root, monkeypatch, capsys):
    for var in ("MEM_DATA", "XDG_STATE_HOME", "HOME"):
        monkeypatch.delenv(var, raising=False)
    assert mem.main(["--root", str(hub_root), "stats"]) == 0
    assert "usage log entries: 0" in capsys.readouterr().out


def test_log_usage_goes_to_data_dir_and_marks_outside(hub_root, tmp_path):
    env = {"MEM_DATA": str(tmp_path / "data")}
    mem.log_usage(hub_root, {"cmd": "search"}, env=env, cwd=tmp_path)
    mem.log_usage(hub_root, {"cmd": "search"}, env=env, cwd=hub_root / "knowledge")
    lines = (tmp_path / "data" / "usage" / "log.jsonl").read_text().splitlines()
    assert [json.loads(l)["outside"] for l in lines] == [True, False]
    assert not (hub_root / ".usage").exists()


def test_log_usage_can_be_disabled(hub_root, tmp_path):
    mem.log_usage(hub_root, {"cmd": "x"}, env={"MEM_DATA": str(tmp_path), "MEM_USAGE_LOG": "0"}, cwd=tmp_path)
    assert not (tmp_path / "usage").exists()


def test_main_without_store(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("MEM_STORE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert mem.main(["search", "x"]) == 2
    assert capsys.readouterr().err.strip() == 'mem: no store is set. Enable the memory plugin and set its "store" option, or pass --root <folder>, or set MEM_STORE.'


@pytest.mark.parametrize("argv", [
    ["new", "research", "--slug", "s", "--title", "t", "--question", "q", "--topics", "x"],
    ["rename", "a", "b"],
    ["index"],
    ["fetch-sources"],
])
def test_write_commands_need_permission(hub_root, monkeypatch, capsys, argv):
    (hub_root / "mem-store.yaml").unlink()
    before = _files(hub_root)
    assert mem.main(["--root", str(hub_root), *argv]) == 2
    assert capsys.readouterr().err.strip() == f"mem: {argv[0]} writes to the store, which is read-only: it has no mem-store.yaml (create a store with \"mem init\")."
    assert _files(hub_root) == before


def test_read_commands_need_no_permission(hub_root, monkeypatch):
    (hub_root / "mem-store.yaml").unlink()
    assert mem.main(["--root", str(hub_root), "search", "attention"]) == 0


def test_tilde_is_expanded(monkeypatch):
    monkeypatch.setenv("HOME", "/h")
    assert mem.resolve_root("~/x", {}) == Path("/h/x")


def test_unreadable_current_folder_counts_as_outside(hub_root, monkeypatch):
    def gone():
        raise FileNotFoundError
    monkeypatch.setattr(Path, "cwd", gone)
    assert mem.main(["--root", str(hub_root), "search", "attention"]) == 0
    entry = json.loads(usage_log_path().read_text().splitlines()[-1])
    assert entry["outside"] is True


def test_main_with_a_file_as_store(tmp_path, capsys):
    f = tmp_path / "file"; f.write_text("x")
    assert mem.main(["--root", str(f), "search", "x"]) == 2
    assert capsys.readouterr().err.strip() == f"mem: the store is not a folder: {f}"


def test_stats_names_the_store_source(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "stats"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"store: {hub_root} (from --root)"


def test_main_with_missing_folder(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MEM_STORE", str(tmp_path / "gone"))
    assert mem.main(["search", "x"]) == 2
    assert capsys.readouterr().err.strip() == f"mem: the store folder does not exist: {tmp_path / 'gone'}"
