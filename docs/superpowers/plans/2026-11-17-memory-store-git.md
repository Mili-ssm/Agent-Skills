# Local git history for the store: plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every change `mem` makes to the default store is a git commit in the store's own local repository, made by `mem` itself, so the owner has a full history and a later remote backup is a plain `git push`.

**Architecture:** `main()` in `plugins/memory/engine/mem.py` sends every path through one `code = dispatch(args)` (today five paths `return args.func(args)` early); after it, when `code == 0`, the command is on an explicit allowlist of writing commands, and the resolved store has a `.git` folder, `mem` stages and commits with a message naming the command. Read commands and the hook commands (`session-index`, `signal`) never run git. A new module `plugins/memory/engine/store_git.py` owns the git calls (subprocess, timeout, lock). `mem history init` turns a store into a repository; `mem init` does not (it runs from the session-start hook under a 4 s timeout, which must not run git).

**Tech Stack:** Python 3.12+, git through `subprocess` (no new dependency), pytest.

**Status:** planned 2026-11-17.

## Decisions already taken (owner, 2026-11-17)

| Decision | Reason |
| --- | --- |
| A local git repository in the store folder holds the history; the remote is added later, after a period of use | History now, backup by `git push` later (D23, stage 7) |
| `mem` makes the commits through Python, never an agent | Predictable, no model cost, no agent running git by hand |
| One commit per command that changed the store | The finest history: each commit says which command did what |
| `.curation-log` and `mem restore` stay as the per-record undo; project memories (`.memory/` inside a project) get no git of their own | Restore undoes one record without touching others and works in project memory; git is history and backup |

## Global Constraints

- Every git call: `subprocess.run(["git", "-C", store, ...], capture_output=True, text=True, check=False, timeout=10, env=…)` with `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` unset or kept as the user has them, and a repository-local identity set at init (`user.name = mem`, `user.email = mem@localhost`) so commits never depend on the owner's global identity.
- A git failure never fails the command: the change is already written; `mem` prints one line on stderr (`mem: history: <reason>`) and exits with the command's own code. The usage log records the failure.
- Concurrency: an exclusive lock (`fcntl.flock` on `<store>/.git/mem-commit.lock`, waiting up to 10 s) around `git add -A` and `git commit`. A commit may include changes of a concurrent writer that has not committed yet; that writer then finds nothing to commit. Accepted: the history stays complete, only the attribution of that one commit is shared. The message always names the command that commits.
- Commit message: first line `mem <command> <subcommand>` plus the first handle or path argument (no body text of the record, no secrets: arguments that carry text — `--claim`, `--context`, `--body-file` content — are never copied into the message).
- No commit when the store is not a repository, when nothing changed, or for read-only commands (they change nothing, so `git status` is empty).
- `.gitignore` written by `mem history init`: every folder of `_LOCAL_DIRS` (mem.py; includes `.sources/`), `research/*/data/`, temporary files (`.*.tmp`), and `.curation-log` files; files over `MAX_FILE_BYTES` (5 MB) are never staged. Ruling 2026-11-17 after the pre-mortem: the curation logs stay out of git because git already holds every earlier state, and `syntheses/.curation-log` was 11.7 MB that day (a full blob per commit); `mem restore` keeps using them locally.
- The allowlist of writing commands is explicit and tested (`remember --global`, `forget`, `refute`, `supersede`, `merge`, `restore`, `confirm`, `promote`, `distinct`, `memory edit`, `note edit`, `new`, `rename`, `unify`, `index`, `import`, `fetch-sources`, every `synthesis` write, `history init`); a command that changes nothing commits nothing.
- Every git call passes `-c commit.gpgsign=false -c core.hooksPath=` so a user's global signing or hooks cannot hang or change a commit; while holding the lock, an `index.lock` older than 60 s (left by a killed git) is removed.
- Tests isolate `HOME` and `GIT_CONFIG_GLOBAL` (point them at temp files) so no real git config is read.
- The session-start hook runs no git (its budget is 0.5 s).
- Tests use temporary stores only (never the owner's store); `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`; `python3 scripts/validate.py` before every commit. Public repository.

---

### Task 1: The commit hook and `store_git.py`

**Files:** Create `plugins/memory/engine/store_git.py`, `plugins/memory/engine/tests/test_store_git.py`; Modify `plugins/memory/engine/mem.py` (the end of `main()`).

**Interfaces:** `is_repo(store) -> bool`; `commit_if_changed(store, message) -> str | None` (the short commit id, or None when nothing changed; raises nothing — returns None and reports on stderr on failure); `init(store) -> None` (git init, local identity, `.gitignore`, first commit of everything present).

- [ ] **Step 0: Spike** — on a temporary copy of a store of realistic size, run 200 writing commands with history on and measure `.git` size; record it in Results; if `.git` exceeds 3× the working tree, set `gc.auto` low at init and re-measure.
- [ ] **Step 1: Write the failing tests** — a write command on a repo store makes exactly one commit whose message names it; `remember --global`, `forget` and `restore` commit; `session-index`, `signal` and a read command run no git at all (monkeypatch `subprocess.run`); a read command makes none; a failing command (non-zero exit) makes none; a store without `.git` is untouched; two writes give two commits; a git failure (monkeypatched `subprocess.run` raising or returning non-zero, or a missing `git`) leaves the command's exit code and prints `mem: history:`; the commit message never contains the text of `--claim`; concurrent commits (two processes, or a held lock released after a delay) both land; `.curation-log` files are ignored (ruling above).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Whole suite and `scripts/validate.py` pass.**
- [ ] **Step 5: Commit** `feat(memory): mem commits every change to a git store`.

### Task 2: `mem history init` and `mem init`

**Files:** Modify `plugins/memory/engine/mem.py`; Test `plugins/memory/engine/tests/test_store_git.py`.

| Command | Effect |
| --- | --- |
| `mem history init [STORE]` | Turns an existing writable store into a repository (`store_git.init`); refuses when it is one already; prints the first commit id |
| `mem history [-n N]` | The last N commits, one line each (`<id> <date> <message>`) |

- [ ] **Step 1: Write the failing tests** — one per row; `history init` on a non-writable folder refused; on an existing repo refused; the first commit holds every file present.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Whole suite and `scripts/validate.py` pass.**
- [ ] **Step 5: Commit** `feat(memory): mem history init and mem history`.

### Task 3: Turn on history in the owner's store and document it

**Files:** Modify `plugins/memory/README.md`, `plugins/memory/skills/memory-curation/SKILL.md` (one line: history is in the store's git log; `mem restore` stays the undo).

- [ ] **Step 1:** README: what the history is, `mem history init`, `mem history`, that `mem restore` stays the undo, that the remote comes later.
- [ ] **Step 2:** After the branch is merged and the installed plugin updated: back up the store (`backups/`), run `mem history init` on the default store, check `git -C <store> log --oneline | head` shows the first commit and a test write adds one more. (Owner-visible state change: done by the controller, reported.)
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
