import json
from pathlib import Path

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


def test_write_commands_need_permission(hub_root, monkeypatch, capsys):
    monkeypatch.delenv("MEM_ALLOW_WRITE")
    assert mem.main(["--root", str(hub_root), "index"]) == 2
    assert capsys.readouterr().err.strip() == "mem: index writes to the store, which is read-only in stage 1; set MEM_ALLOW_WRITE=1 to allow it."
    assert mem.main(["--root", str(hub_root), "search", "attention"]) == 0


def test_tilde_is_expanded(monkeypatch, tmp_path):
    assert mem.resolve_root("~/x", {"HOME": "/h"}) == Path("~/x").expanduser()


def test_stats_names_the_store_source(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "stats"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"store: {hub_root} (from --root)"


def test_main_with_missing_folder(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MEM_STORE", str(tmp_path / "gone"))
    assert mem.main(["search", "x"]) == 2
    assert capsys.readouterr().err.strip() == f"mem: the store folder does not exist: {tmp_path / 'gone'}"
