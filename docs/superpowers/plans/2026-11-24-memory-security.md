# Memory plugin security fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: in progress (pre-mortem amendments applied 2026-11-24) · Date: 2026-11-24 · Branch `fix/memory-security` from `dev`

**Goal:** A cloned repository's `.memory/` folder can no longer overwrite user files, inject owner-vouched rules into any session, launder its memories into global ones, make the engine fetch private addresses, or let a background session send local files out.

**Architecture:** `engine/safe_io.py` owns every write into a store or memory folder (unpredictable temp file, no symlink followed anywhere in the path below the folder). Project memories tracked by git (submodules included) are hidden from every automatic consumer until the owner approves the project once in a terminal (`mem trust`), recorded in the registry in the data folder, outside the repository. `mem fetch-sources` reuses the address-checked transport of `research_checks`. Background synthesis and curation sessions run in a sandbox: scoped reads, an allow-list of `mem` subcommands, and `MEM_SANDBOX=1`, which turns off network, import, URL notes and body files outside allowed roots.

**Tech Stack:** Python 3.12+, pytest, PyYAML; `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (full suite about 5 min).

**Spec:** [project review](../../studies/2026-11-24-project-review.md) § Recommended sequence step 1; findings S1–S4 and S6 (details in `.local/studies/2026-11-24-security-review.md` until this plan merges). Owner rulings 2026-11-24: fix now, before other work; S2 design = per-project approval, accepting that a later `git pull` into an approved project can bring new memories that load.

## Global Constraints

- Python `>=3.12,<3.15` (`engine/run.py`); no new dependency.
- New logic goes into focused modules (`safe_io.py`, `records.py` helpers, `corroborate.py`), not into `mem.py` beyond thin `cmd_*` wiring and parser lines (owner rule: every edit leaves the touched code compliant or better; `mem.py` is 5,924 lines).
- Every behavior change adds a user-facing line under `## [Unreleased]` in `plugins/memory/CHANGELOG.md`; no version bump.
- No line numbers in docs (ADR 0014). English in code, docs and commits.
- Tests rely on the autouse `isolated_env` fixture in `tests/conftest.py`. A test outside a task's Step 4 list that fails in Task 6 means a missed caller: stop and look before patching.

## Verified facts the tasks rely on (2026-11-24)

- `claude -p` passes its environment to Bash children (`MEM_SANDBOX=1` reached `env`).
- `--allowedTools "Read(//abs/**)" "Grep(//abs/**)" "Glob(//abs/**)"` without a bare `Read` denies reads outside those roots; the session's working directory stays readable.
- Session start never registers a project; `cmd_remember`, `_act`, `cmd_memory` and `projects add` do, through `_register_project`.
- `git ls-files -- .memory/` lists only the gitlink when `.memory` is a submodule.

## Review Focus

1. The main agent approving the project itself because a forged memory or the head line says so: `mem trust` must refuse without a TTY — test in Task 3d.
2. A `.memory` submodule: its files count as tracked — test in Task 3b.
3. An untrusted tracked lesson grouped with an owner lesson by corroboration: it must not reach `write_global` or a sighting — test in Task 3c.
4. A redirect from a public URL to `127.0.0.1` during `mem fetch-sources` — test in Task 4.
5. A memory file that is 0644, or a state file that is 0600, keeps its mode after a rewrite; a symlink at the target never yields a 0777 file — tests in Tasks 1 and 2.

---

### Task 1: Symlink-safe writes for memory and synthesis files

**Files:**
- Create: `plugins/memory/engine/safe_io.py`
- Modify: `plugins/memory/engine/records.py` (`update`, `restore`, `log_before`, `load_memories`, `write_memory`), `plugins/memory/engine/syntheses.py` (`_write`, its curation-log append), `plugins/memory/engine/project_syntheses.py` (`load_each`, `write_part` path check)
- Test: `plugins/memory/engine/tests/test_safe_io.py`

**Interfaces:**
- Produces:
  - `safe_io.replace_file(path: Path, data: bytes, mode: int | None = None) -> None`: temp file from `tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")`; mode = `mode` if given, else the mode of `path` when `os.lstat` says it is a regular file, else `0o666 & ~umask`; write, close, `os.replace(tmp, path)`; remove the temp file on any error. `os.replace` replaces a symlink at `path` itself, never its target.
  - `safe_io.append_text(path: Path, text: str) -> None`: `os.open(path, O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW, 0o644)`; a symlink raises `OSError`.
  - `safe_io.UnsafePath(OSError)`; `safe_io.refuse_symlink_chain(root: Path, path: Path) -> None` raises it when `root` or any component of `path` below `root` is a symlink.

- [ ] **Step 1: Write the failing tests** in `test_safe_io.py`:
  - `test_update_does_not_follow_a_planted_temp_symlink`: plant `.{name}.tmp` → victim file; `records.update` on that memory; victim unchanged, memory updated.
  - `test_replace_file_replaces_a_symlinked_target_not_its_target`: `<h>.md` → victim; `replace_file`; victim unchanged, `<h>.md` a regular file whose mode is not 0o777.
  - `test_replace_file_keeps_the_mode`: 0o644 file stays 0o644; `mode=0o600` gives 0o600.
  - `test_append_text_refuses_a_symlinked_log`: `.curation-log` → victim; `records.log_before` raises `OSError`; victim unchanged.
  - `test_project_memories_skip_symlinked_files`: `load_memories(folder, "project")` returns the regular memory only.
  - `test_a_symlinked_project_folder_loads_nothing_and_refuses_writes`: `.memory` → another folder with a valid memory; `load_memories(..., "project")` is `[]`; `write_memory(..., scope="project")` raises `safe_io.UnsafePath`.
  - `test_synthesis_write_refuses_a_symlinked_syntheses_folder`: `.memory/syntheses` → another folder; `project_syntheses.write_part` raises `UnsafePath`, nothing written in the target; `load_each` skips symlinked files.
- [ ] **Step 2: Run** `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_safe_io.py -q` — expected: failures (module missing).
- [ ] **Step 3: Implement** `safe_io.py`; route `records.update`, `records.restore`, `syntheses._write` through `replace_file`; every `.curation-log` append in `records.py` and `syntheses.py` through `append_text`; project-scope `load_memories` returns `[]` for a symlinked folder and skips symlinked entries (global scope unchanged: a user may link a synced folder); `write_memory` and `project_syntheses.write_part` call `refuse_symlink_chain` from the project folder.
- [ ] **Step 4: Run** the new file, then `test_records.py test_syntheses.py test_settle.py test_curation.py test_project_syntheses.py test_project_synthesis_commands.py` — expected: PASS.
- [ ] **Step 5: CHANGELOG line** (Security: writes into memory folders no longer follow symlinks; a symlinked project `.memory` is ignored) and **commit** `fix(memory): never follow symlinks when writing memory files`.

### Task 2: Same guarantee for the other store writes and imports

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`_swap_file`, the note-restore writes, the two JSON state writers that use `path.name + ".tmp"`, every `records.CURATION_LOG` append, `cmd_import`'s walk and its `topics.yaml` read), `plugins/memory/engine/store_git.py` (curation-log trim), `plugins/memory/engine/auto_state.py` (`write_json`, passing `mode=0o600`)
- Test: `plugins/memory/engine/tests/test_safe_io.py` (extend), `plugins/memory/engine/tests/test_import.py` (extend)

**Interfaces:**
- Consumes: `safe_io.replace_file`, `safe_io.append_text`, `safe_io.refuse_symlink_chain` (Task 1).

- [ ] **Step 1: Failing tests:**
  - `test_note_restore_does_not_follow_a_planted_temp_symlink` (through `mem restore` on a note).
  - `test_import_skips_symlinks_at_any_depth`: a source with `literature/x/a.md` → a secret file and `literature/y` → a folder outside; after `mem import`, the secret text is in no store file and the output names each skipped path.
  - `test_state_files_stay_private`: `auto_state.write_json` gives 0o600.
  - `test_no_predictable_temp_names_remain`: scans only `engine/*.py` and `bin/*` (never `tests/`) for `with_name(f".{` and `+ ".tmp"`; no match.
- [ ] **Step 2: Run** them — expected: FAIL.
- [ ] **Step 3: Implement**: route the listed writes through `safe_io`; `cmd_import` checks each path with `refuse_symlink_chain(source_root, path)`, skips and reports it.
- [ ] **Step 4: Run** the new tests, then `test_import.py test_store_git.py test_auto_curation.py test_note_edit.py test_curate_apply.py test_capture_state.py test_capture_auto.py test_memory_edit.py` — expected: PASS.
- [ ] **Step 5: CHANGELOG line** (`mem import` skips symlinks) and **commit** `fix(memory): route every store write through safe_io; import skips symlinks`.

### Task 3a: Trust in the project registry

**Files:**
- Modify: `plugins/memory/engine/records.py` (`register_project`, `forget_project`, new helpers)
- Test: `plugins/memory/engine/tests/test_trust.py`

**Interfaces:**
- Produces:
  - `records.is_trusted(data: Path | None, project: Path) -> bool`: the entry whose `path` equals `str(project.resolve())` has a `trusted` date; a registry `ValueError` counts as not trusted.
  - `records.set_trusted(data: Path | None, project: Path, today: datetime.date, trusted: bool) -> str | None`: registers the project if needed, sets or removes `"trusted": "YYYY-MM-DD"`, returns its name.
  - Every registry read-modify-write (`register_project`, `forget_project`, `set_trusted`) holds an exclusive `fcntl` lock on a lock file in the data folder (pattern: `settle.locked`); `register_project` carries every extra field over, including on its rename branch.

- [ ] **Step 1: Failing tests:** `test_registering_again_keeps_the_approval`, `test_renaming_keeps_the_approval` (`register_project(..., name="other")`), `test_revoke_removes_the_approval`, `test_unreadable_registry_is_not_trusted`.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_trust.py test_projects.py` — expected: PASS.
- [ ] **Step 5: Commit** `fix(memory): keep a per-project trust flag in the registry`.

### Task 3b: Hide untrusted tracked memories from session text

**Files:**
- Modify: `plugins/memory/engine/records.py` (new helpers), `plugins/memory/engine/mem.py` (`cmd_session_index` and `session_index`, `cmd_rules`, `cmd_signal`)
- Test: `plugins/memory/engine/tests/test_trust.py` (extend)

**Interfaces:**
- Consumes: `records.is_trusted` (3a).
- Produces:
  - `records.tracked_memories(project: Path) -> frozenset[str] | None`: handles of `.memory/*.md` tracked by git, from `git -C <project> ls-files -z --recurse-submodules -- .memory/` with a 2 s timeout; `None` ("all tracked") when `.memory` is itself a gitlink or holds a `.git`; empty set when git is missing, fails or times out.
  - `records.hidden_memories(project: Path | None, data: Path | None) -> frozenset[str] | None`: empty when no project or trusted, else `tracked_memories(project)`; `None` means hide every project memory.
  - `session_index(..., hidden: frozenset[str] | None = frozenset())`: drops hidden memories right after `load_memories(project)`, before curation-due counts, the "This project" count, `_got_worse`, `rules.choose` and the listed rows. When any were dropped, the head gains: `Repository memories: <n> tracked in git not loaded; only the owner can approve them, in a terminal (mem trust). Do not run it yourself.` `cmd_session_index` computes `hidden` and passes it, so `session_index` itself still runs no git.
  - `cmd_rules` and `cmd_signal` apply the same filter.

- [ ] **Step 1: Failing tests** (a temporary git repository as `MEM_PROJECT`, memories committed with `git add -f`):
  - `test_tracked_memory_with_forged_owner_confirmation_does_not_load`: tracked lesson with `origin: transcript`, `owner_confirmed`, a valid `short` → `mem session-index` contains neither its short nor its handle, and contains `Repository memories: 1`.
  - `test_untracked_memory_still_loads`.
  - `test_trusted_project_loads_tracked_memories` (via `records.set_trusted`).
  - `test_submodule_memory_folder_counts_as_tracked`.
  - `test_mem_rules_hides_untrusted_tracked_memories`.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_trust.py test_session_index.py test_session_index_due.py test_rules_session.py test_rules.py test_signal.py test_project_synthesis_curation.py` — expected: PASS (`test_session_index_runs_no_git` unchanged).
- [ ] **Step 5: Commit** `fix(memory): hide untrusted repository memories from session text`.

### Task 3c: Keep untrusted memories out of corroboration and capture

**Files:**
- Modify: `plugins/memory/engine/corroborate.py` (`collect`, `fill_records`, `reword_candidates`), `plugins/memory/bin/mem-capture` (the existing-memory list given to the model)
- Test: `plugins/memory/engine/tests/test_trust.py` (extend)

**Interfaces:**
- Consumes: `records.hidden_memories` (3b).
- Behavior: each registered project's hidden memories are dropped where its memories are loaded; a project whose `hidden` is `None` contributes none.

- [ ] **Step 1: Failing tests:** `test_corroboration_ignores_untrusted_tracked_lessons` (a dry run lists no `p<n>:` id of a hidden memory, and an untrusted lesson grouped with a global one yields no `write_global` or sighting); `test_capture_does_not_show_untrusted_memories_to_the_model`.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_trust.py test_corroborate.py test_mem_corroborate.py test_mem_capture.py test_capture.py` — expected: PASS.
- [ ] **Step 5: Commit** `fix(memory): corroboration and capture skip untrusted repository memories`.

### Task 3d: `mem trust` command and docs

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`cmd_trust` beside `cmd_projects`, its parser beside the `projects` parser, `"trust"` in the command list near the top that holds `"projects"`), `plugins/memory/README.md` (Project memories row; a short "Repository memories" paragraph), `plugins/memory/skills/memory/SKILL.md` only if it lists commands
- Test: `plugins/memory/engine/tests/test_trust.py` (extend)

**Interfaces:**
- Consumes: `records.set_trusted`, `records.is_trusted`, `records.hidden_memories`.
- CLI: `mem trust` requires stdin to be a TTY and the owner to type the project's registry name at a prompt; otherwise it exits 2 with `mem trust must be run by the owner in a terminal`. It prints `trusted <name> (<n> tracked memories now load)`. `mem trust --revoke` and `mem trust --status` (`trusted since <date>` or `not trusted (<n> tracked memories not loaded)`) need no TTY.

- [ ] **Step 1: Failing tests:** `test_trust_without_a_tty_exits_2`; `test_trust_with_the_typed_name_approves` (pseudo-TTY via `pty` or by patching the TTY check and stdin); `test_trust_with_a_wrong_name_changes_nothing`; `test_revoke_and_status_need_no_tty`.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_trust.py test_projects.py` — expected: PASS.
- [ ] **Step 5: README + CHANGELOG** (Security: memories committed to a repository load only after the owner runs `mem trust` in a terminal; migration: run it once in each project whose `.memory/` you commit on purpose; a fresh clone, as in a cloud session, needs it again) and **commit** `feat(memory): mem trust approves a project's repository memories`.

### Task 4: Address-checked downloads in `mem fetch-sources`

**Files:**
- Modify: `plugins/memory/engine/research_checks.py` (extract the hop loop), `plugins/memory/engine/mem.py` (`_download`; delete `_HttpOnlyRedirects`)
- Test: `plugins/memory/engine/tests/test_fetch_sources.py` (extend; delete `test_redirect_handler_refuses_non_http_targets` with the class; rewrite `test_download_refuses_oversized_and_non_http_redirects` for the new transport), `plugins/memory/engine/tests/test_research_checks.py` (stays green unchanged, including the `/big` truncation test)

**Interfaces:**
- Produces: `research_checks.fetch_raw(url: str, limit_for: Callable[[str], int], *, over: Literal["truncate", "fail"] = "truncate", headers: Mapping[str, str] | None = None, deadline: float | None = None, max_redirects: int = MAX_REDIRECTS, allow_hosts: Iterable[str] = ()) -> tuple[bytes, str]` — body and lowercased content type; scheme, credential, public-address, pinned-connection, redirect and deadline rules as today; `limit_for(content_type)` gives the byte limit; past it, `"truncate"` cuts and `"fail"` raises `FetchFailed`. `fetch_text` keeps its signature and behavior and calls it (its content-type refusal and decoding stay in `fetch_text`).
- `mem._download(url) -> tuple[bytes, str]` keeps its signature: `fetch_raw(url, lambda _: FETCH_MAX_BYTES, over="fail", headers={"User-Agent": _USER_AGENT}, deadline=120, max_redirects=10)`; `FetchError` becomes `ValueError` with the messages its callers print today.
- Known limit: the pinned connection ignores `HTTPS_PROXY` (as `research_checks` already does); note it in the CHANGELOG line.

- [ ] **Step 1: Failing tests:** `test_download_refuses_a_private_address` (patch `research_checks.socket.getaddrinfo` → `169.254.169.254`; `ValueError` mentioning "non-public"); `test_download_refuses_a_redirect_to_localhost` (first host public, patched `_connection` answers `302` to `http://127.0.0.1/`); `test_download_keeps_its_user_agent_and_ten_redirects`.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement**; fix `_download`'s docstring (it is no longer "the only network access").
- [ ] **Step 4: Run** `test_fetch_sources.py test_research_checks.py test_research_run.py` — expected: PASS.
- [ ] **Step 5: CHANGELOG line** and **commit** `fix(memory): fetch-sources refuses non-public addresses`.

### Task 5: Sandbox for background synthesis and curation sessions

**Files:**
- Modify: `plugins/memory/engine/synth_pipeline.py` (`run_session`), `plugins/memory/engine/research_checks.py` and `plugins/memory/engine/mem.py` (honor the sandbox in `fetch_raw`, `cmd_import`, `cmd_new`, and every `--body-file` reader), `plugins/memory/bin/mem-auto`, `plugins/memory/bin/mem-synthesize` (pass roots)
- Test: `plugins/memory/engine/tests/test_synth_session.py`

**Interfaces:**
- Produces:
  - `SANDBOX = "MEM_SANDBOX"` in `research_checks`. With `MEM_SANDBOX=1`: `fetch_raw` raises `FetchRefused("network access is off in this session")` before resolving; `mem import` and `mem fetch-sources` exit 2; `mem new` refuses `--url`; a `--body-file` outside `MEM_SANDBOX_ROOTS` (`os.pathsep`-separated) and the working directory exits 2.
  - `run_session(..., read_roots: Sequence[Path] = ())`: `Read(/{root}/**)`, `Grep(/{root}/**)`, `Glob(/{root}/**)` for each root (no bare `Read`, `Grep`, `Glob`); `Bash(mem *)` replaced by an allow-list of `Bash(mem <sub>*)` entries, one per subcommand the curator and synthesizer briefs use (derive the list from `plugins/memory/agents/memory-curator.md`, `plugins/memory/agents/memory-synthesizer.md` and the prompts `synth_pipeline` builds; record it as a module constant with a comment naming those sources); env gains `MEM_SANDBOX=1` and `MEM_SANDBOX_ROOTS`.
  - `mem-auto` and `mem-synthesize` pass the store, the global memories root (when outside the store) and the work folder.

- [ ] **Step 1: Failing tests:** `test_run_session_scopes_reads_and_sets_the_sandbox` (capture command and env: no bare `"Read"`, `f"Read(/{store}/**)"` present, no `Bash(mem *)`, `env["MEM_SANDBOX"] == "1"`); `test_sandbox_refuses_network_import_urls_and_outside_body_files`.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_synth_session.py test_auto_curation.py test_synth_pipeline_refs.py test_fetch_sources.py test_import.py test_new_body.py` — expected: PASS.
- [ ] **Step 5: CHANGELOG line** and **commit** `fix(memory): background curation and synthesis sessions run in a sandbox`.

### Task 6: Close

- [ ] Full suite `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` passes; `python3 scripts/validate.py`; `claude plugin validate .`
- [ ] One real `mem-auto` dry run or curator session after Task 5: the log shows `denied 0` and the expected writes (kill criterion: denials or no writes → revert the scoping and re-plan).
- [ ] Set this plan's Status to done; in the project review mark S1–S4 and S6 fixed and add S5 and S7 to its public table (open, low).
- [ ] Ask the owner before pushing the branch and opening the pull request to `dev`.

## Kill criteria (after merge)

- `mem fetch-sources --force` on 10 existing literature notes succeeds less often than on `dev` → fix user agent, redirects or deadline before release.
- Median `session-index` time in the hook log rises by more than 300 ms → cache the git call.
- `mem-auto` logs show denials or no writes → revert Task 5's scoping.
