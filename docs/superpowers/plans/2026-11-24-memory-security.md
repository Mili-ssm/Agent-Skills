# Memory plugin security fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: in progress (pre-mortem amendments applied; S2 reduced to the light design, owner 2026-11-24) · Date: 2026-11-24 · Branch `fix/memory-security` from `dev`

**Goal:** A cloned repository's `.memory/` folder can no longer overwrite user files, pass its memories off as owner-vouched, lift them into global ones through corroboration, make the engine fetch private addresses, or let a background session send local files out.

**Architecture:** `engine/safe_io.py` owns every write into a store or memory folder (unpredictable temp file, no symlink followed anywhere in the path below the folder). Project memories tracked by git (submodules included) still load, but the owner confirmation written in the file (`owner_confirmed`) no longer counts, they are marked "from repository", and corroboration never lifts them into global memories. `mem fetch-sources` reuses the address-checked transport of `research_checks`. Background synthesis and curation sessions run in a sandbox: scoped reads, an allow-list of `mem` subcommands, and `MEM_SANDBOX=1`, which turns off network, import, URL notes and body files outside allowed roots.

**Tech Stack:** Python 3.12+, pytest, PyYAML; `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (full suite about 5 min).

**Spec:** [project review](../../studies/2026-11-24-project-review.md) § Recommended sequence step 1; findings S1–S4 and S6 (details in `.local/studies/2026-11-24-security-review.md` until this plan merges). Owner rulings 2026-11-24: fix now, before other work; S2 light design: committing `.memory/` is a legitimate feature, so repository memories keep loading without owner trust (per-project approval with `mem trust` was dropped).

## Global Constraints

- Python `>=3.12,<3.15` (`engine/run.py`); no new dependency.
- New logic goes into focused modules (`safe_io.py`, `records.py` and `rules.py` helpers, `corroborate.py`), not into `mem.py` beyond thin `cmd_*` wiring and parser lines (owner rule: every edit leaves the touched code compliant or better; `mem.py` is 5,924 lines).
- Every behavior change adds a user-facing line under `## [Unreleased]` in `plugins/memory/CHANGELOG.md`; no version bump.
- No line numbers in docs (ADR 0014). English in code, docs and commits.
- Tests rely on the autouse `isolated_env` fixture in `tests/conftest.py`. A test outside a task's Step 4 list that fails in Task 6 means a missed caller: stop and look before patching.

## Verified facts the tasks rely on (2026-11-24)

- `claude -p` passes its environment to Bash children (`MEM_SANDBOX=1` reached `env`).
- `--allowedTools "Read(//abs/**)" "Grep(//abs/**)" "Glob(//abs/**)"` without a bare `Read` denies reads outside those roots; the session's working directory stays readable.
- `git ls-files -- .memory/` lists only the gitlink when `.memory` is a submodule.

## Review Focus

1. A tracked lesson whose file claims `owner_confirmed`: never shown as vouched, never established by that field — test in Task 3a.
2. A `.memory` submodule: its files count as tracked — test in Task 3a.
3. A tracked lesson grouped with an owner lesson by corroboration: it must not reach `write_global` or a sighting — test in Task 3b.
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

- [x] **Step 1: Write the failing tests** in `test_safe_io.py`:
  - `test_update_does_not_follow_a_planted_temp_symlink`: plant `.{name}.tmp` → victim file; `records.update` on that memory; victim unchanged, memory updated.
  - `test_replace_file_replaces_a_symlinked_target_not_its_target`: `<h>.md` → victim; `replace_file`; victim unchanged, `<h>.md` a regular file whose mode is not 0o777.
  - `test_replace_file_keeps_the_mode`: 0o644 file stays 0o644; `mode=0o600` gives 0o600.
  - `test_append_text_refuses_a_symlinked_log`: `.curation-log` → victim; `records.log_before` raises `OSError`; victim unchanged.
  - `test_project_memories_skip_symlinked_files`: `load_memories(folder, "project")` returns the regular memory only.
  - `test_a_symlinked_project_folder_loads_nothing_and_refuses_writes`: `.memory` → another folder with a valid memory; `load_memories(..., "project")` is `[]`; `write_memory(..., scope="project")` raises `safe_io.UnsafePath`.
  - `test_synthesis_write_refuses_a_symlinked_syntheses_folder`: `.memory/syntheses` → another folder; `project_syntheses.write_part` raises `UnsafePath`, nothing written in the target; `load_each` skips symlinked files.
- [x] **Step 2: Run** `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_safe_io.py -q` — expected: failures (module missing).
- [x] **Step 3: Implement** `safe_io.py`; route `records.update`, `records.restore`, `syntheses._write` through `replace_file`; every `.curation-log` append in `records.py` and `syntheses.py` through `append_text`; project-scope `load_memories` returns `[]` for a symlinked folder and skips symlinked entries (global scope unchanged: a user may link a synced folder); `write_memory` and `project_syntheses.write_part` call `refuse_symlink_chain` from the project folder.
- [x] **Step 4: Run** the new file, then `test_records.py test_syntheses.py test_settle.py test_curation.py test_project_syntheses.py test_project_synthesis_commands.py` — expected: PASS.
- [x] **Step 5: CHANGELOG line** (Security: writes into memory folders no longer follow symlinks; a symlinked project `.memory` is ignored) and **commit** `fix(memory): never follow symlinks when writing memory files`.

### Task 2: Same guarantee for the other store writes and imports

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`_swap_file`, the note-restore writes, the two JSON state writers that use `path.name + ".tmp"`, every `records.CURATION_LOG` append, `cmd_import`'s walk and its `topics.yaml` read), `plugins/memory/engine/store_git.py` (curation-log trim), `plugins/memory/engine/auto_state.py` (`write_json`, passing `mode=0o600`)
- Test: `plugins/memory/engine/tests/test_safe_io.py` (extend), `plugins/memory/engine/tests/test_import.py` (extend)

**Interfaces:**
- Consumes: `safe_io.replace_file`, `safe_io.append_text`, `safe_io.refuse_symlink_chain` (Task 1).

- [x] **Step 1: Failing tests:**
  - `test_note_restore_does_not_follow_a_planted_temp_symlink` (through `mem restore` on a note).
  - `test_import_skips_symlinks_at_any_depth`: a source with `literature/x/a.md` → a secret file and `literature/y` → a folder outside; after `mem import`, the secret text is in no store file and the output names each skipped path.
  - `test_state_files_stay_private`: `auto_state.write_json` gives 0o600.
  - `test_no_predictable_temp_names_remain`: scans only `engine/*.py` and `bin/*` (never `tests/`) for `with_name(f".{` and `+ ".tmp"`; no match.
- [x] **Step 2: Run** them — expected: FAIL.
- [x] **Step 3: Implement**: route the listed writes through `safe_io`; `cmd_import` checks each path with `refuse_symlink_chain(source_root, path)`, skips and reports it.
- [x] **Step 4: Run** the new tests, then `test_import.py test_store_git.py test_auto_curation.py test_note_edit.py test_curate_apply.py test_capture_state.py test_capture_auto.py test_memory_edit.py` — expected: PASS.
- [x] **Step 5: CHANGELOG line** (`mem import` skips symlinks) and **commit** `fix(memory): route every store write through safe_io; import skips symlinks`.

### Task 3a: Repository memories carry no owner trust

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, new helpers), `plugins/memory/engine/rules.py` (`standing_words`), `plugins/memory/engine/mem.py` (`cmd_session_index`/`session_index`, `cmd_rules`: pass the tracked set; no logic), `plugins/memory/README.md` (Project memories row: one sentence on repository memories)
- Test: `plugins/memory/engine/tests/test_repo_memories.py`

**Interfaces:**
- Produces:
  - `records.tracked_memories(project: Path) -> frozenset[str] | None`: handles of `.memory/*.md` tracked by git, from `git -C <project> ls-files -z --recurse-submodules -- .memory/` with a 2 s timeout; `None` ("all tracked") when `.memory` is itself a gitlink or holds a `.git`; empty set when git is missing, fails or times out.
  - `records.mark_repository(memories: Sequence[Memory], tracked: frozenset[str] | None) -> list[Memory]`: copies (`dataclasses.replace`) of the tracked ones with `from_repository=True` and `owner_confirmed=None`; others unchanged. `Memory` gains `from_repository: bool = False`.
  - `rules.standing_words(m)` returns `"(from repository)"` when `m.from_repository`; such a memory never gets `"(the user vouched for it)"`.
  - `session_index(..., tracked: frozenset[str] | None = frozenset())`: applies `mark_repository` right after `load_memories(project)`; `cmd_session_index` computes `tracked` so `session_index` itself runs no git. `cmd_rules` does the same.
- Behavior: repository memories still load, list and qualify as rules through their sightings; only the owner confirmation written in the file stops counting, and the reader sees where they came from.

- [x] **Step 1: Failing tests** in `test_repo_memories.py` (a temporary git repository as `MEM_PROJECT`, memories committed with `git add -f`):
  - `test_tracked_lesson_with_forged_owner_confirmation_is_not_vouched`: tracked lesson with `origin: transcript`, `owner_confirmed`, a valid `short`, no sightings → `mem session-index` output contains neither `the user vouched for it` nor the short (not established without that field).
  - `test_tracked_established_lesson_loads_marked_from_repository`: the same lesson with two session sightings → its short is loaded and its line ends with `(from repository)`.
  - `test_untracked_owner_confirmed_lesson_keeps_its_mark`.
  - `test_submodule_memory_folder_counts_as_tracked`.
- [x] **Step 2: Run** `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_repo_memories.py -q` — expected: FAIL.
- [x] **Step 3: Implement.**
- [x] **Step 4: Run** `test_repo_memories.py test_session_index.py test_session_index_due.py test_rules_session.py test_rules.py test_records.py test_project_synthesis_curation.py` — expected: PASS (`test_session_index_runs_no_git` unchanged).
- [x] **Step 5: README + CHANGELOG** (Security: memories committed to a repository never show as owner-vouched and are marked "from repository") and **commit** `fix(memory): repository memories carry no owner trust`.

### Task 3b: Corroboration does not lift repository memories into global ones

**Files:**
- Modify: `plugins/memory/engine/corroborate.py` (`collect`, `fill_records`, `reword_candidates`)
- Test: `plugins/memory/engine/tests/test_repo_memories.py` (extend)

**Interfaces:**
- Consumes: `records.tracked_memories` (3a).
- Behavior: each registered project's tracked memories are left out where corroboration loads project memories; a project whose set is `None` contributes none. This includes the fill job (`fill_records`, and the candidate order that puts `owner_confirmed` lessons first): it must never pick a tracked memory or write `short`/`topic` into a tracked file. Capture is unchanged: it may still see them, and after 3a they carry no owner trust.

- [x] **Step 1: Failing test:** `test_corroboration_ignores_repository_lessons` (a dry run lists no `p<n>:` id of a tracked memory, and a tracked lesson grouped with a global one yields no `write_global` or sighting).
- [x] **Step 2: Run** — expected: FAIL.
- [x] **Step 3: Implement.**
- [x] **Step 4: Run** `test_repo_memories.py test_corroborate.py test_mem_corroborate.py` — expected: PASS.
- [x] **Step 5: CHANGELOG line** and **commit** `fix(memory): corroboration skips repository memories`.

### Task 4: Address-checked downloads in `mem fetch-sources`

**Files:**
- Modify: `plugins/memory/engine/research_checks.py` (extract the hop loop), `plugins/memory/engine/mem.py` (`_download`; delete `_HttpOnlyRedirects`)
- Test: `plugins/memory/engine/tests/test_fetch_sources.py` (extend; delete `test_redirect_handler_refuses_non_http_targets` with the class; rewrite `test_download_refuses_oversized_and_non_http_redirects` for the new transport), `plugins/memory/engine/tests/test_research_checks.py` (stays green unchanged, including the `/big` truncation test)

**Interfaces:**
- Produces: `research_checks.fetch_raw(url: str, limit_for: Callable[[str], int], *, over: Literal["truncate", "fail"] = "truncate", headers: Mapping[str, str] | None = None, deadline: float | None = None, max_redirects: int = MAX_REDIRECTS, allow_hosts: Iterable[str] = ()) -> tuple[bytes, str]` — body and lowercased content type; scheme, credential, public-address, pinned-connection, redirect and deadline rules as today; `limit_for(content_type)` gives the byte limit; past it, `"truncate"` cuts and `"fail"` raises `FetchFailed`. `fetch_text` keeps its signature and behavior and calls it (its content-type refusal and decoding stay in `fetch_text`).
- `mem._download(url) -> tuple[bytes, str]` keeps its signature: `fetch_raw(url, lambda _: FETCH_MAX_BYTES, over="fail", headers={"User-Agent": _USER_AGENT}, deadline=120, max_redirects=10)`; `FetchError` becomes `ValueError` with the messages its callers print today.
- Known limit: the pinned connection ignores `HTTPS_PROXY` (as `research_checks` already does); note it in the CHANGELOG line.

- [x] **Step 1: Failing tests:** `test_download_refuses_a_private_address` (patch `research_checks.socket.getaddrinfo` → `169.254.169.254`; `ValueError` mentioning "non-public"); `test_download_refuses_a_redirect_to_localhost` (first host public, patched `_connection` answers `302` to `http://127.0.0.1/`); `test_download_keeps_its_user_agent_and_ten_redirects`.
- [x] **Step 2: Run** — expected: FAIL.
- [x] **Step 3: Implement**; fix `_download`'s docstring (it is no longer "the only network access").
- [x] **Step 4: Run** `test_fetch_sources.py test_research_checks.py test_research_run.py` — expected: PASS.
- [x] **Step 5: CHANGELOG line** and **commit** `fix(memory): fetch-sources refuses non-public addresses`.

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
