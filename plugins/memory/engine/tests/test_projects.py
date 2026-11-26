import datetime
import json
import os
import shutil
from pathlib import Path

import mem
import pytest
from conftest import usage_log_path
from store import records

USAGE_EXIT = 2
PATH_LINES = 2


def registry():
    return json.loads((Path(os.environ["MEM_DATA"]) / "projects.json").read_text())


def run(capsys, *argv):
    code = mem.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def remember_in(monkeypatch, root, claim, capsys=None):
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    code = mem.main(["remember", "--kind", "lesson", "--claim", claim])
    if capsys:
        capsys.readouterr()
    return code


@pytest.fixture
def two(tmp_path, monkeypatch, capsys):
    """Two registered projects: the current one (alpha) and beta, both holding a memory about pottery glaze."""
    alpha, beta = tmp_path / "alpha", tmp_path / "beta"
    assert remember_in(monkeypatch, beta, "Pottery glaze needs a slow cooling ramp", capsys) == 0
    assert remember_in(monkeypatch, alpha, "Pottery glaze cracks in alpha kilns", capsys) == 0
    return alpha, beta


def test_remember_registers_the_project_with_name_path_and_date(tmp_path, monkeypatch, capsys):
    root = tmp_path / "alpha"
    assert remember_in(monkeypatch, root, "A lesson about kilns", capsys) == 0
    assert registry() == {
        "alpha": {"path": str(root.resolve()), "seen": datetime.date.today().isoformat()}
    }


def test_a_taken_name_gets_a_numeric_suffix_and_the_same_path_keeps_its_name(
    tmp_path, monkeypatch, capsys
):
    one, two_ = tmp_path / "x" / "app", tmp_path / "y" / "app"
    assert remember_in(monkeypatch, one, "First lesson here", capsys) == 0
    assert remember_in(monkeypatch, two_, "Second lesson here", capsys) == 0
    assert remember_in(monkeypatch, one, "Third lesson there", capsys) == 0
    reg = registry()
    assert sorted(reg) == ["app", "app-2"]
    assert reg["app"]["path"] == str(one.resolve()) and reg["app-2"]["path"] == str(two_.resolve())


def test_curation_actions_refresh_the_seen_date(tmp_path, monkeypatch, capsys):
    root = tmp_path / "alpha"
    remember_in(monkeypatch, root, "A lesson about kilns", capsys)
    path = Path(os.environ["MEM_DATA"]) / "projects.json"
    reg = registry()
    reg["alpha"]["seen"] = "2020-01-01"
    path.write_text(json.dumps(reg))
    handle = records.load_memories(root / ".memory", "project")[0].handle
    assert mem.main(["confirm", f"m:{handle}"]) == 0
    assert registry()["alpha"]["seen"] == datetime.date.today().isoformat()


def test_registration_never_fails_a_command(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setenv("MEM_DATA", str(blocker))
    assert remember_in(monkeypatch, tmp_path / "alpha", "A lesson about kilns", capsys) == 0
    data = tmp_path / "data2"
    data.mkdir()
    (data / "projects.json").write_text("not json")
    monkeypatch.setenv("MEM_DATA", str(data))
    assert remember_in(monkeypatch, tmp_path / "beta", "Another lesson about kilns", capsys) == 0
    assert (data / "projects.json").read_text() == "not json"


def test_no_data_folder_registers_nothing(tmp_path, monkeypatch, capsys):
    for var in ("MEM_DATA", "XDG_STATE_HOME", "HOME"):
        monkeypatch.delenv(var, raising=False)
    assert mem.data_dir(os.environ) is None
    assert remember_in(monkeypatch, tmp_path / "alpha", "A lesson about kilns", capsys) == 0


def test_a_failed_remember_registers_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEM_PROJECT", str(tmp_path / "alpha"))
    assert mem.main(["remember", "--kind", "finding", "--claim", "No source given"]) == USAGE_EXIT
    assert not (Path(os.environ["MEM_DATA"]) / "projects.json").exists()


def test_projects_list_add_remove(tmp_path, monkeypatch, two, capsys):
    alpha, beta = two
    code, out, _ = run(capsys, "projects", "list")
    assert code == 0
    assert out.splitlines() == [
        f"alpha\t1 memories\t{alpha.resolve()}",
        f"beta\t1 memories\t{beta.resolve()}",
    ]
    gamma = tmp_path / "gamma"
    gamma.mkdir()
    code, out, _ = run(capsys, "projects", "add", str(gamma), "--name", "g")
    assert code == 0 and registry()["g"]["path"] == str(gamma.resolve())
    assert (
        run(capsys, "projects", "add", str(tmp_path / "beta"), "--name", "g")[0] == USAGE_EXIT
    )  # name taken by another path
    code, out, _ = run(capsys, "projects", "add", str(gamma))  # same path: refreshed
    assert code == 0 and sorted(registry()) == ["alpha", "beta", "g"]
    gamma.rmdir()
    assert f"g\tmissing\t{gamma.resolve()}" in run(capsys, "projects", "list")[1].splitlines()
    assert run(capsys, "projects", "remove", "g")[0] == 0 and "g" not in registry()
    code, _, err = run(capsys, "projects", "remove", "nope")
    assert code == USAGE_EXIT and "nope" in err
    assert (beta / ".memory").is_dir()  # the project's files are never touched


def test_projects_need_no_store(capsys):
    assert run(capsys, "projects", "list")[0] == 0


def test_search_project_adds_a_section_after_the_current_ones(two, hub_root, capsys):
    code, out, err = run(
        capsys, "--root", str(hub_root), "search", "pottery glaze", "--project", "beta"
    )
    assert code == 0, err
    lines = out.splitlines()
    assert lines.index("-- memories (project) --") < lines.index("-- memories (project: beta) --")
    tail = lines[lines.index("-- memories (project: beta) --") + 1 :]
    assert len(tail) == 1 and tail[0].startswith("m:") and "slow cooling ramp" in tail[0]


def test_search_does_not_repeat_the_current_project_under_its_name(two, capsys):
    code, out, _ = run(
        capsys, "search", "--scope", "memories", "pottery glaze", "--project", "alpha"
    )
    assert code == 0 and "(project: alpha)" not in out and "cracks in alpha" in out


def test_search_all_projects_names_every_other_one(tmp_path, monkeypatch, two, capsys):
    remember_in(
        monkeypatch, tmp_path / "gamma", "Pottery glaze is food safe only when fired", capsys
    )
    monkeypatch.setenv("MEM_PROJECT", str(two[0]))
    code, out, _ = run(capsys, "search", "--scope", "memories", "pottery glaze", "--all-projects")
    assert code == 0
    assert "-- memories (project: beta) --" in out and "-- memories (project: gamma) --" in out
    assert "(project: alpha)" not in out


def test_search_unknown_project_exits_2_and_prints_nothing(two, hub_root, capsys):
    code, out, err = run(
        capsys,
        "--root",
        str(hub_root),
        "search",
        "pottery glaze",
        "--project",
        "beta",
        "--project",
        "nope",
    )
    assert code == USAGE_EXIT and not out
    assert err.strip() == "mem: no project named nope (see mem projects list)"


def test_search_without_options_is_byte_identical_with_another_project_present(
    tmp_path, monkeypatch, hub_root, capsys
):
    alpha = tmp_path / "alpha"
    remember_in(monkeypatch, alpha, "Pottery glaze cracks in alpha kilns", capsys)
    before = run(capsys, "--root", str(hub_root), "search", "pottery glaze")
    remember_in(monkeypatch, tmp_path / "beta", "Pottery glaze needs a slow cooling ramp", capsys)
    monkeypatch.setenv("MEM_PROJECT", str(alpha))
    after = run(capsys, "--root", str(hub_root), "search", "pottery glaze")
    assert after == before and "beta" not in after[1] and "slow cooling" not in after[1]
    assert "slow cooling" not in run(capsys, "search", "--scope", "memories", "pottery glaze")[1]


def test_other_projects_follow_the_rules_of_the_memory_sections(two, hub_root, capsys):
    root = ["--root", str(hub_root)]
    for extra in (["--offset", "1"], ["--kind", "paper"], ["--detail", "paths"]):
        out = run(capsys, *root, "search", "pottery glaze", "--project", "beta", *extra)[1]
        assert "slow cooling" not in out and "(project: beta)" not in out, extra
    out = run(
        capsys,
        "search",
        "--scope",
        "memories",
        "pottery glaze",
        "--project",
        "beta",
        "--detail",
        "paths",
    )[1]
    assert len(out.splitlines()) == PATH_LINES


def test_the_usage_log_counts_projects_and_never_names_them(two, hub_root, capsys):
    run(capsys, "--root", str(hub_root), "search", "pottery glaze", "--project", "beta")
    text = usage_log_path().read_text()
    entry = json.loads(text.splitlines()[-1])
    assert entry["projects"] == 1 and "beta" not in text
    run(capsys, "--root", str(hub_root), "search", "pottery glaze")
    assert "projects" not in json.loads(usage_log_path().read_text().splitlines()[-1])


def test_show_and_memories_read_a_named_project_only_on_request(two, capsys):
    _, beta = two
    handle = records.load_memories(beta / ".memory", "project")[0].handle
    code, out, _ = run(capsys, "show", f"m:{handle}", "--project", "beta")
    assert code == 0 and "slow cooling ramp" in out
    assert run(capsys, "show", f"m:{handle}")[0] == 1
    code, out, _ = run(capsys, "memories", "--project", "beta")
    assert code == 0 and "slow cooling ramp" in out and "cracks in alpha" not in out
    assert "slow cooling" not in run(capsys, "memories")[1]
    assert run(capsys, "memories", "--project", "nope")[0] == USAGE_EXIT
    assert run(capsys, "show", f"m:{handle}", "--project", "nope")[0] == USAGE_EXIT


def test_memories_of_a_project_whose_folder_moved_say_so(two, tmp_path, capsys):
    _, beta = two
    beta.rename(tmp_path / "beta-moved")
    code, out, err = run(capsys, "memories", "--project", "beta")
    assert code == USAGE_EXIT and not out
    assert "beta" in err and str(beta.resolve()) in err and "not found" in err


def test_writing_commands_take_no_project_option(two):
    for argv in (
        ["remember", "--kind", "lesson", "--claim", "x y", "--project", "beta"],
        ["confirm", "m:x", "--project", "beta"],
    ):
        with pytest.raises(SystemExit):
            mem.main(argv)


def test_memories_of_a_project_without_its_memory_folder_is_an_error(two, capsys):
    _, beta = two
    shutil.rmtree(beta / ".memory")  # the root stays, its memory folder is gone
    code, out, err = run(capsys, "memories", "--project", "beta")
    assert code == USAGE_EXIT and not out and ".memory" in err and "beta" in err
