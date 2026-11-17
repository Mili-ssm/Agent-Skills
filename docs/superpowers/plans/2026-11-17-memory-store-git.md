# Local git history for the store: plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every change `mem` makes to the default store is a git commit in the store's own local repository, made by `mem` itself, so the owner has a full history and a later remote backup is a plain `git push`.

**Architecture:** No hook in `main()`: commits happen in three places only — `mem curate --done` (after recording the pass), `mem history commit` (run by a new `SessionEnd` hook in `plugins/memory/hooks/hooks.json`, and by hand), and `mem history init` (first commit). Every other command, the session-start and subagent hooks included, runs no git. A new module `plugins/memory/engine/store_git.py` owns the git calls (subprocess, timeout, lock). `mem history init` turns a store into a repository; `mem init` does not (it runs from the session-start hook under a 4 s timeout, which must not run git).

**Tech Stack:** Python 3.12+, git through `subprocess` (no new dependency), pytest.

**Status:** planned 2026-11-17.

## Decisions already taken (owner, 2026-11-17)

| Decision | Reason |
| --- | --- |
| A local git repository in the store folder holds the history; the remote is added later, after a period of use | History now, backup by `git push` later (D23, stage 7) |
| `mem` makes the commits through Python, never an agent | Predictable, no model cost, no agent running git by hand |
| One commit when a curation pass ends (`mem curate --done`) and one at session end (`SessionEnd` hook) for writes outside curation; no commit per command (owner, 2026-11-17, revised the same day) | A coarser history with few commits; `mem curate --done` already marks the end of a pass |
| The curation logs keep 30 days; older entries are trimmed after a commit, and only in a store that is a git repository (owner: 30 days; ruling: never trim where git does not hold the history, so project memories' logs are not trimmed) | The logs grew to 11.7 MB in one day of synthesis writing because each entry holds the whole previous file; git now holds the older states |
| `.curation-log` and `mem restore` stay as the per-record undo; project memories (`.memory/` inside a project) get no git of their own | Restore undoes one record without touching others and works in project memory; git is history and backup |

## Global Constraints

- Every git call: `subprocess.run(["git", "-C", store, ...], capture_output=True, text=True, check=False, timeout=10, env=…)` with `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` unset or kept as the user has them, and a repository-local identity set at init (`user.name = mem`, `user.email = mem@localhost`) so commits never depend on the owner's global identity.
- A git failure never fails the command: the change is already written; `mem` prints one line on stderr (`mem: history: <reason>`) and exits with the command's own code. The usage log records the failure.
- Concurrency: an exclusive lock (`fcntl.flock` on `<store>/.git/mem-commit.lock`, waiting up to 10 s) around `git add -A` and `git commit`. A commit may include changes of a concurrent writer that has not committed yet; that writer then finds nothing to commit. Accepted: the history stays complete, only the attribution of that one commit is shared. The message always names the command that commits.
- Commit message: first line `mem <command> <subcommand>` plus the first handle or path argument (no body text of the record, no secrets: arguments that carry text — `--claim`, `--context`, `--body-file` content — are never copied into the message).
- No commit when the store is not a repository, when nothing changed, or for read-only commands (they change nothing, so `git status` is empty).
- `.gitignore` written by `mem history init`: every folder of `_LOCAL_DIRS` (mem.py; includes `.sources/`), `research/*/data/`, temporary files (`.*.tmp`), and `.curation-log` files; files over `MAX_FILE_BYTES` (5 MB) are never staged. Ruling 2026-11-17 after the pre-mortem: the curation logs stay out of git because git already holds every earlier state, and `syntheses/.curation-log` was 11.7 MB that day (a full blob per commit); `mem restore` keeps using them locally.
- Commit messages: `curation pass <YYYY-MM-DD>: <N> files` for `curate --done`, `session end <YYYY-MM-DD HH:MM>: <N> files` for the hook, `mem history commit -m TEXT` for a manual one; never the text of a record. Nothing changed → no commit.
- The `SessionEnd` hook runs `mem history commit` under `timeout 5` and never blocks or fails the session end.
- Trimming: after a successful commit in `curate --done`, entries older than 30 days are removed from every `.curation-log` inside the store (the root one, `syntheses/`, `memories/`), keeping undo markers consistent (`restore` uses line numbers: rewrite the log so `last_log_entry` still finds the right entries, or keep removed lines as empty lines); never in project `.memory/` folders.
- Every git call passes `-c commit.gpgsign=false -c core.hooksPath=` so a user's global signing or hooks cannot hang or change a commit; while holding the lock, an `index.lock` older than 60 s (left by a killed git) is removed.
- Tests isolate `HOME` and `GIT_CONFIG_GLOBAL` (point them at temp files) so no real git config is read.
- The session-start hook runs no git (its budget is 0.5 s).
- Tests use temporary stores only (never the owner's store); `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`; `python3 scripts/validate.py` before every commit. Public repository.

---

### Task 1: `store_git` without a per-command hook

**Files:** `plugins/memory/engine/store_git.py`, `plugins/memory/engine/mem.py`, `plugins/memory/engine/tests/test_store_git.py`.

Commit 4efb128 built a per-command hook in `main()`; the owner then chose commits only at the end of a curation pass and at session end. Rework: remove the hook and the `_dispatch`/`_record_history` split from `main()` (restore `main()` to its earlier shape), keep `store_git.py` (`is_repo`, `commit_if_changed`, `init`, lock, stale lock, `.gitignore`, 5 MB limit, local identity, `-c commit.gpgsign=false -c core.hooksPath=`), and keep the 200-commit spike numbers in Results (1.7× the tracked tree).

- [x] **Step 0: Spike** — done in 4efb128: 200 commits on a synthetic store gave `.git` 7.5 MB for a 4.4 MB tracked tree (1.7×), under the 3× criterion; no `gc.auto` change.
- [ ] **Step 1: Tests** — no command runs git except the three commit points (monkeypatch `subprocess.run` in a write command, `session-index` and `signal`); the `store_git` unit tests stay.
- [ ] **Step 2: Implement the rework; whole suite and `scripts/validate.py` pass.**
- [ ] **Step 3: Commit** `refactor(memory): store git commits only at curation and session end`.

### Task 2: The commit points, the commands and log trimming

**Files:** `plugins/memory/engine/mem.py`, `plugins/memory/engine/store_git.py`, `plugins/memory/hooks/hooks.json` and a hook script, tests.

| Command or event | Effect |
| --- | --- |
| `mem history init [STORE]` | Makes a writable store a repository (`store_git.init`), first commit; refuses a store that is one already or is not writable |
| `mem history [-n N]` | Last N commits, one line each |
| `mem history commit [-m TEXT]` | Commits what changed; prints the commit or `nothing to commit` |
| `mem curate --done` | As today, then commits (`curation pass …`), then trims logs (30 days) |
| `SessionEnd` hook | `mem history commit` with a `session end …` message, under `timeout 5`, never failing the session |

- [ ] **Step 1: Failing tests** — one per row; trimming removes only entries older than 30 days, only after a commit, only inside a git store (a project `.memory/` log untouched), and `mem restore` still works on the entries left (including after an earlier restore marker); a store without git: `curate --done` behaves as today and trims nothing; the hook script exits 0 when git fails or times out.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Whole suite, `scripts/validate.py` and `claude plugin validate plugins/memory` pass.**
- [ ] **Step 5: Commit** `feat(memory): history commands, commits at curation and session end, 30-day log trimming`.

### Task 3: Document and turn it on

**Files:** `plugins/memory/README.md`, `plugins/memory/skills/memory-curation/SKILL.md`.

- [ ] **Step 1:** README: what the history is, the three commit points, `mem history init|commit` and `mem history`, the 30-day trimming, `mem restore` as the undo, the remote later. Curation skill: one line that `mem curate --done` also commits and trims (bodies only, no `description:` change).
- [ ] **Step 2:** After merge and plugin update, by the controller with the owner told first: back up the store, `mem history init` on the default store, check `git log` shows the first commit and that `curate --done` adds one.
- [ ] **Step 3: Commit** `docs(memory): the store keeps a git history`.

## Pre-mortem of 2026-11-17 and what changed

| Risk found | Change |
| --- | --- |
| Five early `return args.func(args)` paths would skip the hook (global memories never committed) | One dispatch path; explicit allowlist of writing commands, tested |
| The hook would run git in `session-index` and `signal`, which run in hooks | Those and all reads run no git |
| `git add -A` would sweep `.sources/` and research data | `.gitignore` from `_LOCAL_DIRS` plus research data; files over 5 MB never staged |
| The 11.7 MB `.curation-log` would bloat the repository by gigabytes | Logs out of git (ruling); a 200-commit spike measures `.git` |
| A killed git leaves `index.lock` and every later commit fails | Stale lock removed under the `flock` |
| `mem init` runs in the session-start hook | `mem init` does no git; only `mem history init` |

Kill criteria: `.git` over 3× the working tree after one week → stop and re-plan; `mem: history:` in normal use → turn the hook off and investigate.

## Results

Pending.
