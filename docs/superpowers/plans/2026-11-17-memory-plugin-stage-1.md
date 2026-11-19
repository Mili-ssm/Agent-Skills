# Memory plugin, stage 1 (engine and reach) Implementation Plan

Status: done · merged in #117, 2026-11-17 · boxes left unticked during execution are not open work (checked 2026-11-19).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a `mem` command, available in every repository once the `memory` plugin is enabled, that searches and reads a configured store with the same results as the tool it was copied from.

**Architecture:** the engine is one Python file, `plugins/memory/engine/mem.py`, copied unchanged from the owner's search tool and then given a store path that comes from configuration instead of the file's own location. A shell launcher in `bin/` runs it with `uv`. A `SessionStart` hook passes the plugin's `store` option to later shell commands. Splitting the file into modules waits for stage 2, where the record model changes it: a verbatim copy keeps parity provable now.

**Tech Stack:** Python 3.12, `uv` (PEP 723 script header), `pyyaml`, `pytest`; Bash for the launcher and the hook.

**Spec:** [../specs/2026-11-17-memory-plugin-design.md](../specs/2026-11-17-memory-plugin-design.md); stage 1 of [2026-11-17-memory-plugin.md](2026-11-17-memory-plugin.md).

## Global Constraints

- `ORIGINAL` means the owner's private tool. Its path is given in each task's brief, never written in this repository. It is read, never changed.
- This repository is public: no file may hold a home-directory path, the private repository's name, or text of a private note. The original's test fixtures are synthetic and may be copied.
- Nothing outside `plugins/memory/`, `.claude-plugin/marketplace.json`, `README.md` and `docs/` changes. `plugins/agent-skills/`, the mods, `ports/` and `scripts/` do not change.
- No `version` in `plugin.json` or the marketplace entry (ADR 0006).
- Tests run with: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`. The original's suite passes 324 tests (measured 2026-11-17).
- Commit after each task on branch `feat/memory-plugin`; do not push.
- The command is `mem`; user-facing text says `mem`, never `hub.py`.
- **Stage 1 is read-only by default.** The configured store may be the owner's private repository, which must not change: the commands `new`, `rename`, `index` and `fetch-sources` refuse to run unless `MEM_ALLOW_WRITE=1`.
- Tests never touch the real home: an autouse fixture points `MEM_DATA` and `XDG_CONFIG_HOME` at temporary folders, unsets `MEM_STORE` and sets `MEM_ALLOW_WRITE=1`.
- One usage log location: `data_dir(env)/usage/log.jsonl`. The hook does not export `MEM_DATA`; that variable exists for tests.

## Review Focus

1. A store path that contains spaces: the launcher, the hook and the config file must keep it whole.
2. A store path that is set but does not exist: `mem` exits 2 with a message naming the path, not a traceback.
3. `uv` not installed: the launcher exits 127 with one line, not a shell error.
4. The hook run with no `store` option set: exits 0, prints nothing, writes nothing, and removes a config file left by an earlier option. With the option set and no `CLAUDE_ENV_FILE`: writes the config file only.
5. The current folder cannot be read when the usage log computes `outside`: the command still succeeds.

---

### Task 1: Copy the engine and its tests

**Files:**
- Create: `plugins/memory/engine/mem.py` (copy of `ORIGINAL`)
- Create: `plugins/memory/engine/tests/` (copy of the original's `tests/` folder, including `fixtures/`)
- Create: `plugins/memory/engine/tests/fixtures/templates/` (copy of the original repository's `templates/` folder)

**Interfaces:**
- Produces: module `mem` importable from `plugins/memory/engine/`, with every function of the original under the same name; the `hub_root` pytest fixture, unchanged in name and behavior.

- [x] **Step 1:** Copy the files. Do not copy `__pycache__`.
- [x] **Step 2:** In the tests, change the imported module name from `hub` to `mem` (imports and attribute references), make `conftest.py` put `plugins/memory/engine/` on `sys.path`, and make the `hub_root` fixture copy templates from `tests/fixtures/templates`. Change nothing else, in the tests or in `mem.py`.
- [x] **Step 3:** Run the tests. Expected: `324 passed`.
- [x] **Step 4:** Run `grep -rnE '/home/|Documentos|research-hub' plugins/memory/` . Expected: no output. If a hit is in copied code, stop and report it; do not rewrite it.
- [x] **Step 5:** Commit: `feat(memory): copy the search engine and its tests`.

### Task 2: Store path from configuration, usage log outside the store

**Files:**
- Modify: `plugins/memory/engine/mem.py`
- Create: `plugins/memory/engine/tests/test_store.py`

**Interfaces:**
- Produces:
  - `resolve_root(cli_root: str | None, env: Mapping[str, str]) -> Path | None`. Order: `cli_root`; `env["MEM_STORE"]`; the first line of the file `agent-memory/store` under `env["XDG_CONFIG_HOME"]` or, when that is unset, `env["HOME"]/.config`; otherwise `None`. Empty strings count as unset; the file's line is read with `strip()`; with neither `XDG_CONFIG_HOME` nor `HOME` in `env` the file step is skipped. A leading `~` is expanded with `Path.expanduser()`. The path is not checked for existence.
  - `store_source(cli_root: str | None, env: Mapping[str, str]) -> str | None`: `"--root"`, `"MEM_STORE"` or `"config file"`, by the same order; `mem stats` prints a first line `store: <path> (from <source>)`.
  - `data_dir(env: Mapping[str, str]) -> Path`. `env["MEM_DATA"]`; else `agent-memory` under `env["XDG_STATE_HOME"]` or `env["HOME"]/.local/state`.
  - `log_usage(root: Path, entry: dict[str, Any], *, env: Mapping[str, str] | None = None, cwd: Path | None = None) -> None`: writes to `data_dir(env)/usage/log.jsonl`; adds `"outside": bool`, true when `cwd` (default: the current folder) is neither `root` nor inside it, and true when the current folder cannot be read; does nothing when `env["MEM_USAGE_LOG"] == "0"`. It still never raises. `mem stats` counts this log, not a `.usage` folder in the store; the constant `USAGE_LOG` under the store is removed.
- `main()`: the `--root` option has no default; the root comes from `resolve_root(args.root, os.environ)`. `None` prints to stderr exactly `mem: no store is set. Enable the memory plugin and set its "store" option, or pass --root <folder>, or set MEM_STORE.` and returns 2. A root that is not an existing folder prints `mem: the store folder does not exist: <path>` and returns 2.
- Every user-facing `hub.py` in messages, help text and the parser's program name becomes `mem`; a message that says `uv run tools/hub.py <command>` says `mem <command>`. The module docstring becomes `Memory engine: parsing primitives and the mem commands.` `DEFAULT_ROOT` and the `HUB_USAGE_LOG` variable are removed. Markers inside notes (`TODO(hub):`, `hub:index:start`) do not change: they are the store's format.
- Write guard: in `main()`, when the command is one of `new`, `rename`, `index`, `fetch-sources` and `os.environ.get("MEM_ALLOW_WRITE") != "1"`, print to stderr exactly `mem: <command> writes to the store, which is read-only in stage 1; set MEM_ALLOW_WRITE=1 to allow it.` and return 2.
- `conftest.py` gains an autouse fixture `isolated_env(monkeypatch, tmp_path)` that sets `MEM_DATA` to `tmp_path / "mem-data"`, `XDG_CONFIG_HOME` to `tmp_path / "mem-config"`, `MEM_ALLOW_WRITE` to `1`, and deletes `MEM_STORE`.

- [ ] **Step 1: Write the failing tests** in `test_store.py`:

```python
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
```

- [ ] **Step 2:** Run `…pytest plugins/memory/engine/tests/test_store.py -q`. Expected: fails, `resolve_root` not defined.
- [ ] **Step 3:** Implement the interfaces above in `mem.py`. Existing tests that relied on `DEFAULT_ROOT`, on the log under the store, or on `hub.py` in a message are updated to the new behavior, and each such change is listed in the report.
- [ ] **Step 4:** Run the whole suite. Expected: all pass; the count is 324 plus the new tests, and any test removed or rewritten is listed in the report with its reason. Then confirm isolation: `ls ~/.local/state/agent-memory 2>/dev/null` shows no file newer than the run.
- [ ] **Step 5:** `grep -n 'hub\.py\|HUB_\|DEFAULT_ROOT' plugins/memory/engine/mem.py`. Expected: no output.
- [ ] **Step 6:** Commit: `feat(memory): take the store from configuration and log usage outside it`.

### Task 3: The plugin around the engine

**Files:**
- Create: `plugins/memory/.claude-plugin/plugin.json`, `plugins/memory/bin/mem`, `plugins/memory/hooks/hooks.json`, `plugins/memory/hooks/session-env.sh`, `plugins/memory/README.md`, `plugins/memory/engine/tests/test_plugin_shell.py`
- Modify: `.claude-plugin/marketplace.json` (one entry), `README.md` (one row in the first table, one install line beside the mods')

**Interfaces:**
- Consumes: `mem.py` reads `MEM_STORE`, `MEM_DATA` and the file `agent-memory/store` (Task 2).
- Produces: the `mem` executable; the environment a session's shell commands see.

`plugin.json`:

```json
{
  "name": "memory",
  "description": "Notes and memories reachable from every repository and subagent: a `mem` command that searches and reads a configured store.",
  "author": { "name": "mili-ssm" },
  "repository": "https://github.com/Mili-ssm/Agent-Skills",
  "userConfig": {
    "store": {
      "type": "directory",
      "title": "Store",
      "description": "Folder of notes and memories that the plugin reads and writes (the global scope)."
    }
  }
}
```

`hooks/hooks.json`:

```json
{
  "description": "Passes the store path to shell commands of the session",
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}\"/hooks/session-env.sh", "timeout": 5 } ] }
    ]
  }
}
```

`hooks/session-env.sh` (Bash, executable): reads `CLAUDE_PLUGIN_OPTION_STORE`. When it is empty: exit 0, nothing written, nothing printed. Otherwise: write the path as the only line of `${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory/store` (creating the folder); when `CLAUDE_ENV_FILE` is set, append `export MEM_STORE=<path>`, the value quoted with `printf %q`. With the option set and no `CLAUDE_ENV_FILE`, it still writes the config file. It prints nothing and always exits 0, also when a write fails.

`bin/mem` (Bash, executable): finds its own folder through symlinks; when `uv` is not on the path prints `mem: uv is not installed (https://docs.astral.sh/uv/)` to stderr and exits 127; otherwise `exec uv run --quiet --script "<its folder>/../engine/mem.py" "$@"`.

Marketplace entry: `{"name": "memory", "source": "./plugins/memory", "description": <the same text as plugin.json>}`. README row: `` | `memory` | Notes and memories reachable from every repository: the `mem` command (stage 1 of ADR 0023; proposed) | [README](plugins/memory/README.md) | ``.

`plugins/memory/README.md`: purpose in two lines; requirements (`uv`); how the store is set (the plugin option, `MEM_STORE`, `--root`), that the option takes effect in the next session, and that stage 1 is read-only unless `MEM_ALLOW_WRITE=1`; `mem --help` for commands; the test command; a line that this is stage 1 with a link to the plan. Under 40 lines.

- [ ] **Step 1: Write the failing tests** in `test_plugin_shell.py` (each skips when `uv` is not installed):

```python
MEM = Path(__file__).resolve().parents[2] / "bin" / "mem"
HOOK = Path(__file__).resolve().parents[2] / "hooks" / "session-env.sh"

def run(cmd, env):  # PATH and HOME are carried over so uv keeps its cache; config and data go to tmp
    return subprocess.run(cmd, env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **env}, capture_output=True, text=True)

def test_mem_searches_the_configured_store(hub_root, tmp_path):
    r = run([str(MEM), "search", "attention"], {"MEM_STORE": str(hub_root), "MEM_DATA": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c")})
    assert r.returncode == 0 and "attention" in r.stdout.lower()

def test_mem_store_path_with_spaces(hub_root, tmp_path):
    spaced = tmp_path / "my store"; shutil.copytree(hub_root, spaced)
    r = run([str(MEM), "search", "attention"], {"MEM_STORE": str(spaced), "MEM_DATA": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c")})
    assert r.returncode == 0

def test_mem_without_store(tmp_path):
    r = run([str(MEM), "search", "x"], {"XDG_CONFIG_HOME": str(tmp_path / "c"), "MEM_DATA": str(tmp_path / "d")})
    assert r.returncode == 2 and r.stderr.startswith("mem: no store is set.")

def test_mem_without_uv(tmp_path):
    r = subprocess.run([str(MEM), "search", "x"], env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode == 127 and r.stderr.strip() == "mem: uv is not installed (https://docs.astral.sh/uv/)"

def test_hook_writes_config_and_env(tmp_path):
    envfile = tmp_path / "env"; envfile.write_text("")
    r = run([str(HOOK)], {"XDG_CONFIG_HOME": str(tmp_path / "c"), "CLAUDE_PLUGIN_OPTION_STORE": "/a path/store", "CLAUDE_ENV_FILE": str(envfile)})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert (tmp_path / "c" / "agent-memory" / "store").read_text() == "/a path/store\n"
    out = subprocess.run(["bash", "-c", f"source {envfile}; printf '%s' \"$MEM_STORE\""], capture_output=True, text=True).stdout
    assert out == "/a path/store"

def test_hook_without_option_does_nothing(tmp_path):
    r = run([str(HOOK)], {"XDG_CONFIG_HOME": str(tmp_path / "c")})
    assert r.returncode == 0 and r.stdout == "" and not (tmp_path / "c").exists()
```

`test_mem_without_uv` skips when `uv` is found under `/usr/bin` or `/bin`.

- [ ] **Step 2:** Run them. Expected: fail, files missing.
- [ ] **Step 3:** Write the files above.
- [ ] **Step 4:** Run the whole suite. Expected: all pass.
- [ ] **Step 5:** Run `python3 scripts/validate.py` (expected `OK: 15 skills, 17 agents, 0 errors`) and `python3 scripts/port.py --check` (expected: passes; if it reports the new plugin in a generated catalog, stop and report, do not edit generated files).
- [ ] **Step 6:** `git add` the files, then `git ls-files -s plugins/memory/bin/mem plugins/memory/hooks/session-env.sh` must show mode `100755` for both. Commit: `feat(memory): add the plugin manifest, the mem launcher and the session hook`.

### Task 4: The `memory` skill and its trigger case

Written by the main conversation, not delegated: it is prompt text (N1, N2), and its wording follows the `prompt-engineering` skill.

**Files:**
- Create: `plugins/memory/skills/memory/SKILL.md`, `plugins/memory/evals/trigger/memory/` (same shape as `plugins/agent-skills/evals/trigger/api-design/`)

- [ ] **Step 1:** Write `SKILL.md`: description in the third person with "Use when…" and the owner's likely terms, at most 1,024 characters; body at most 150 lines: the three-step recall recipe (`mem search`, `mem show <handle>… --section conclusion`, read a whole note only if needed), `--links` for a question that needs several notes, what to do when nothing relevant comes back, and that writing waits for stage 2.
- [ ] **Step 2:** Write the trigger case: a prompt that asks a factual question the store could hold, and a grader that passes when the skill is loaded.
- [ ] **Step 3:** Run the case at 2 runs with Sonnet as the main model. Expected: 2 of 2; record the result in ADR 0023 when it is next amended.
- [ ] **Step 4:** Commit: `feat(memory): add the memory skill and its trigger case`.

### Task 5: Parity and reach, measured

Run by the main conversation; "Results" below records counts and pass or fail only, never a query, a path or a note title.

- [ ] **Step 0:** Before Task 3, a spike in a scratch repository: `claude plugin validate` on a manifest and `hooks.json` of the shapes in Task 3; a hook that dumps its environment shows whether the `store` option reaches it under `--plugin-dir`; a subagent runs `printenv MEM_STORE` to show whether the env-file export reaches its shell. Task 3's JSON is corrected to what validates.
- [ ] **Step 1:** Parity: on a disposable clone of the owner's store, run twenty fixed queries and `search-eval` through `ORIGINAL` and through `mem`, and compare outputs. Expected: identical ranked paths for each query; identical recall and MRR figures. The original runs at a pinned commit with `HUB_USAGE_LOG=0`; the queries stay in the scratchpad.
- [ ] **Step 2:** Reach: in a scratch repository, a headless session with the plugin loaded (`--plugin-dir`) and the store option set runs `mem search` in the main session and in a Haiku subagent. The session starts with `MEM_STORE` unset, a temporary `XDG_CONFIG_HOME` and `--allowedTools 'Bash(mem *)'`. Expected: both print results; `mem stats` shows whether each shell got the store from the environment or from the config file.
- [ ] **Step 3:** No store: the same session without the option. Expected: the message of Task 2.
- [ ] **Step 4:** Eval isolation: one `neg-*` case of `plugins/agent-skills` with the plugin enabled and disabled. Expected: the same result; if not, note that eval runs disable it.
- [ ] **Step 5:** Tick stage 1 in [the stage plan](2026-11-17-memory-plugin.md) and record the figures there.

## Results

Measured on 2026-11-17; counts and pass or fail only.

| Task | Result |
|---|---|
| 1 | Done. The copy was byte-identical to the original and passed its 324 tests |
| 2 | Done, one fix round. A review found that a read command could leave its usage log inside the store when no home folder was set; fixed and tested. Suite: 348 passed, 1 skipped (the no-`uv` test, skipped where `uv` is in a system folder) |
| 3 | Done. Validators pass; both scripts are executable |
| 4 | Done. Trigger case: 2 of 2 runs loaded the skill (Sonnet, 2026-11-17, with the owner's permission to trust the folder) |
| 5, step 0 | Pass. A trial plugin showed: the manifest and `hooks.json` validate; the `store` option reaches the hook; `bin/` is on the path of the main session's shell and of a subagent's; a variable exported through `CLAUDE_ENV_FILE` reaches both; the option itself does not reach the shell |
| 5, step 1 | Pass. 20 of 20 fixed queries gave identical output in the original and in `mem`; `search-eval` gave identical figures; the disposable clone was unchanged |
| 5, step 2 | Pass. With the plugin loaded in a headless session, `mem` ran in the main session and in a subagent; both took the store from the exported variable; the store was unchanged |
| 5, step 3 | Pass. With no store set: the Task 2 message and exit code 2 |
| 5, step 4 | Not applicable: `claude plugin eval` loads only the plugin it is given, so this plugin cannot enter an eval run of `agent-skills` |
| Write guard on a real store | Pass. `mem index` returned 2 and changed nothing |

