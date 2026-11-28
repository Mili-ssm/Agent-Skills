# Memory plugin, stage 2 (notes and memories) Implementation Plan

Status: done · merged in #117, 2026-11-17 · boxes left unticked during execution are not open work (checked 2026-11-19).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** an agent writes a memory in one call, in the project it is working in or in the store, and `mem search` returns memories beside notes, labelled so a memory is never read as a fact.

**Architecture:** memories are a second kind of record with their own small model in a new module, `plugins/memory/engine/records.py`, which `mem.py` imports; the copied engine is not restructured. Memories are ranked as their own corpus and printed in their own sections, so the ranking of notes stays identical to the original tool's. A store is writable only when it carries a marker file, so the owner's note repository stays read-only without any setting.

**Tech Stack:** Python 3.12, `uv`, `pyyaml`, `pytest`, `git` (to find a project's main worktree).

**Spec:** [../specs/2026-11-17-memory-plugin-design.md](../../specs/2026-11-17-memory-plugin-design.md), sections "Notes and memories", "What goes where", "Project scope"; stage 2 of [2026-11-17-memory-plugin.md](../2026-11-17-memory-plugin.md).

## Global Constraints

- Nothing outside `plugins/memory/` and `docs/` changes. The owner's note repository is never written; tests and trials use temporary folders or a disposable clone.
- With no memory present, the output of every existing command is byte-identical to before this stage (the stage 1 parity run must still pass).
- Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (350 passed, 1 skipped before this stage). The autouse fixture `isolated_env` already isolates home and data; this stage adds `MEM_PROJECT` to what it unsets.
- `records.py` imports nothing from `mem.py` (no import cycle); `mem.py` imports `records`.
- A memory file is Markdown with YAML frontmatter. Fields: `kind` (one of `decision`, `constraint`, `pitfall`, `lesson`, `finding`, `state`), `claim` (one sentence, required), `created` (ISO date), `observed` (integer, at least 1), `status` (`active`, `refuted` or `superseded`), and optional `context` (string), `valid_until` (ISO date), `sources` (list of URLs). Dates are written as quoted strings.
- Project memories live in `<main worktree root>/.memory/`, global memories in `<store>/memories/`, one file per memory, named by a slug of the claim.
- Exit codes of the new commands: 0 written; 2 usage or environment problem; 3 a near-duplicate exists and nothing was written; 4 a forbidden term was found and nothing was written.
- The repository is public: no home-directory path or private name in any file. Commit after each task on `feat/memory-plugin`; do not push.

## Review Focus

1. A linked git worktree: the memory must land in the main worktree's `.memory/`, not the linked one's.
2. A folder that is not a git repository: `remember` without `--global` or `MEM_PROJECT` exits 2 with a message, and writes nothing.
3. A memory file edited by hand into invalid YAML or an unknown `kind`: `search` and `show` still work and report that file on stderr, without a traceback.
4. Two memories whose claims give the same slug: the second file gets a numeric suffix; nothing is overwritten.
5. A claim made only of punctuation or non-ASCII letters: the slug is never empty.

---

### Task 1: The memory model (`records.py`)

**Files:**
- Create: `plugins/memory/engine/records.py`, `plugins/memory/engine/tests/test_records.py`
- Modify: `plugins/memory/engine/tests/conftest.py` (`isolated_env` also deletes `MEM_PROJECT`)

**Interfaces (all in `records.py`):**

```python
KINDS = ("decision", "constraint", "pitfall", "lesson", "finding", "state")
STATUSES = ("active", "refuted", "superseded")
PROJECT_DIR = ".memory"
GLOBAL_DIR = "memories"
STORE_MARKER = "mem-store.yaml"

@dataclass
class Memory:
    scope: str            # "project" or "global"
    path: Path
    handle: str           # the file stem
    kind: str
    claim: str
    created: datetime.date | None
    observed: int
    status: str
    context: str | None
    valid_until: datetime.date | None
    sources: list[str]
    body: str
    error: str | None     # set when the file could not be parsed or validated; the other fields then hold defaults

def project_root(cwd: Path, env: Mapping[str, str]) -> Path | None
    # env["MEM_PROJECT"] when non-empty; else the parent of `git -C cwd rev-parse --path-format=absolute --git-common-dir`; None when not in a repository or git is missing
def memory_dir(scope: str, *, store: Path | None, project: Path | None) -> Path | None
    # project/PROJECT_DIR or store/GLOBAL_DIR; None when the base is None
def load_memories(folder: Path | None, scope: str) -> list[Memory]
    # every *.md directly in the folder, sorted by handle; [] when the folder is None or missing; never raises
def slug_of(claim: str) -> str
    # lower-case ASCII words of the claim joined by hyphens, at most 8 words and 60 characters; "memory" when that is empty
def write_memory(folder: Path, scope: str, *, kind: str, claim: str, body: str, today: datetime.date,
                 context: str | None = None, valid_until: datetime.date | None = None,
                 sources: Sequence[str] = ()) -> Memory
    # creates the folder; file name slug_of(claim) + ".md", then "-2", "-3"… when taken; observed 1, status "active"; raises ValueError for an unknown kind or an empty claim
def is_live(memory: Memory, today: datetime.date) -> bool
    # no error, status "active", and valid_until absent or not before today
def similarity(a: Iterable[str], b: Iterable[str]) -> float
    # Jaccard index of the two token sets; 0.0 when either is empty
def observe(memory: Memory, today: datetime.date) -> Memory
    # rewrites the file with observed + 1 and `last_observed`; the body and other fields unchanged
def ensure_excluded(project: Path) -> bool
    # called before the first write: when project/PROJECT_DIR does not exist yet and the project is a git repository, appends ".memory/" to <git common dir>/info/exclude unless a line already says so; True when it appended; never raises
def forbidden_line(text: str, env: Mapping[str, str]) -> int | None
    # 1-based line number of the first non-empty line of the file agent-memory/forbidden-terms (under XDG_CONFIG_HOME, else HOME/.config) that occurs in text, case-insensitively; None when the file is missing or nothing matches
def store_is_writable(store: Path, env: Mapping[str, str]) -> bool
    # (store / STORE_MARKER).is_file() or env.get("MEM_ALLOW_WRITE") == "1"
```

- [ ] **Step 1: Write the failing tests** in `test_records.py`, one per behavior above, including the five Review Focus cases that belong here. Use a `repo` fixture that runs `git init -q` in `tmp_path / "proj"`. Required assertions:

```python
def test_write_then_load_round_trip(tmp_path):
    m = records.write_memory(tmp_path / ".memory", "project", kind="pitfall",
        claim="The staging database rejects connections after 20:00.", body="Seen twice.",
        today=datetime.date(2026, 11, 17), context="billing service", sources=["https://example.org/a"])
    assert m.handle == "the-staging-database-rejects-connections-after-20-00"
    [loaded] = records.load_memories(tmp_path / ".memory", "project")
    assert (loaded.kind, loaded.claim, loaded.observed, loaded.status, loaded.context, loaded.sources, loaded.body.strip(), loaded.created, loaded.error) == \
        ("pitfall", "The staging database rejects connections after 20:00.", 1, "active", "billing service", ["https://example.org/a"], "Seen twice.", datetime.date(2026, 11, 17), None)

def test_same_slug_gets_a_suffix(tmp_path):
    a = records.write_memory(tmp_path, "project", kind="lesson", claim="Same claim.", body="", today=TODAY)
    b = records.write_memory(tmp_path, "project", kind="lesson", claim="Same claim.", body="", today=TODAY)
    assert (a.handle, b.handle) == ("same-claim", "same-claim-2") and a.path.exists()

def test_slug_is_never_empty():
    assert records.slug_of("¿¡…!?") == "memory" and records.slug_of("Ünïcödé only ñ") != ""

def test_project_root_of_a_linked_worktree_is_the_main_one(repo, tmp_path):
    # commit once in repo, then: git worktree add ../wt
    assert records.project_root(tmp_path / "wt", {}) == repo

def test_project_root_outside_git_is_none(tmp_path):
    assert records.project_root(tmp_path, {}) is None
    assert records.project_root(tmp_path, {"MEM_PROJECT": "/p"}) == Path("/p")

def test_broken_file_is_reported_not_raised(tmp_path):
    (tmp_path / "bad.md").write_text("---\nkind: [unclosed\n---\n")
    (tmp_path / "odd.md").write_text("---\nkind: rumor\nclaim: x\n---\n")
    got = records.load_memories(tmp_path, "project")
    assert [m.handle for m in got] == ["bad", "odd"] and all(m.error for m in got)

def test_is_live():
    # active and no date: True; valid_until yesterday: False; today: True; status refuted or superseded: False; error set: False

def test_similarity():
    assert records.similarity(["a", "b", "c"], ["a", "b", "d"]) == 0.5 and records.similarity([], ["a"]) == 0.0

def test_observe_increments_and_keeps_the_body(tmp_path): ...  # observed 1 -> 2, last_observed set, body and claim equal

def test_ensure_excluded_once(repo):
    assert records.ensure_excluded(repo) is True
    assert (repo / ".git" / "info" / "exclude").read_text().splitlines()[-1] == ".memory/"
    (repo / ".memory").mkdir()
    assert records.ensure_excluded(repo) is False       # the folder exists: the owner's choice is kept

def test_forbidden_line(tmp_path):
    cfg = tmp_path / "agent-memory"; cfg.mkdir(); (cfg / "forbidden-terms").write_text("\nAcme Corp\nzeta\n")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert records.forbidden_line("we met ACME corp today", env) == 2
    assert records.forbidden_line("nothing here", env) is None and records.forbidden_line("x", {}) is None

def test_store_is_writable(tmp_path):
    assert not records.store_is_writable(tmp_path, {})
    assert records.store_is_writable(tmp_path, {"MEM_ALLOW_WRITE": "1"})
    (tmp_path / "mem-store.yaml").write_text(""); assert records.store_is_writable(tmp_path, {})
```

- [ ] **Step 2:** Run `…pytest plugins/memory/engine/tests/test_records.py -q`. Expected: fails, no module `records`.
- [ ] **Step 3:** Implement `records.py`.
- [ ] **Step 4:** Run the whole suite. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(memory): add the memory record model`.

### Task 2: Writing memories (`remember`, `observe`, `init`) and the store marker

**Files:**
- Modify: `plugins/memory/engine/mem.py`
- Create: `plugins/memory/engine/tests/test_remember.py`

**Interfaces:**
- Consumes: everything in Task 1's block.
- `mem remember --kind K --claim "…" [--body-file PATH|-] [--context C] [--valid-until YYYY-MM-DD] [--source URL]… [--global] [--force]`
  - Without `--global`: the project scope. No project root: stderr `mem: not inside a git repository: pass --global, or set MEM_PROJECT to the project folder.`, exit 2. It calls `ensure_excluded` before the first write. It needs no store.
  - With `--global`: needs a store that `store_is_writable`; otherwise the read-only message below, exit 2. The claim, context and body are checked with `forbidden_line`; a hit prints `mem: the text contains a forbidden term (line N of the forbidden-terms list); nothing was written.`, exit 4.
  - Duplicate check, both scopes: among the live memories of the target scope, any whose claim has `similarity` of at least 0.8 with the new claim (tokens from `mem.tokenize`) stops the write unless `--force`: stderr lists each as `m:<handle>\t<claim>`, then `mem: a similar memory exists; run "mem observe m:<handle>" if it is the same, or repeat with --force to write a new one.`, exit 3.
  - On success: stdout is one line, `m:<handle>\t<path relative to the project root or the store>`; then up to three live memories of the same scope with similarity between 0.3 and 0.8 are listed on stderr under `similar memories:`.
- `mem observe m:<handle>`: finds the memory in the project scope first, then the global scope (global needs a writable store); prints `m:<handle>\tobserved N`; an unknown handle exits 2 with `mem: no memory named m:<handle>`.
- `mem init <folder>`: creates the folder when missing and, in it, `mem-store.yaml` (containing `format: 1`), `topics.yaml` (an empty mapping), and the folders `literature`, `knowledge`, `research`, `memories`; refuses a folder that already holds anything other than those names (exit 2, `mem: <folder> is not empty and is not a store`). It needs no configured store.
- The stage 1 write guard changes: the four guarded commands and global memory writes run when `store_is_writable(root, os.environ)`. The message becomes `mem: <command> writes to the store, which is read-only: it has no mem-store.yaml (create a store with "mem init"), or set MEM_ALLOW_WRITE=1.` The stage 1 tests of the guard are updated to this message.
- `remember`, `observe` and `init` resolve the store with `resolve_root`, but a missing store is an error only where the command needs one.

- [ ] **Step 1: Write the failing tests** in `test_remember.py` through `mem.main([...])` with `monkeypatch.setenv("MEM_PROJECT", …)` or a `repo` fixture: project write prints `m:<handle>\t.memory/<handle>.md` and creates the file; outside git exits 2 with the exact message and creates nothing; in a `git init` folder the exclude line appears and `git status --porcelain` is empty afterwards; a second `remember` with the same claim exits 3 and writes nothing, with `--force` writes `…-2`; `--global` on a store without the marker exits 2 with the exact message, with the marker writes `memories/<handle>.md`; a forbidden term exits 4 and writes nothing; `observe` raises `observed` to 2; `observe m:nope` exits 2; `init` creates the five entries, a second `init` on the same folder succeeds, `init` on a folder holding `notes.txt` exits 2; `--body-file -` reads standard input; `--valid-until 2026-13-01` and `--kind rumor` exit 2 through argparse.
- [ ] **Step 2:** Run them. Expected: fail, unknown command `remember`.
- [ ] **Step 3:** Implement the three commands and the guard change in `mem.py`.
- [ ] **Step 4:** Run the whole suite. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(memory): write memories with remember, observe and init`.

### Task 3: Reading memories (`search`, `show`, `stats`)

**Files:**
- Modify: `plugins/memory/engine/mem.py`
- Create: `plugins/memory/engine/tests/test_memory_search.py`

**Interfaces:**
- Consumes: Task 1's block; the memory files Task 2 writes.
- `mem search` gains `--scope {all,notes,memories}` (default `all`) and `--all-memories`.
  - Notes are ranked and printed exactly as before. With `--scope memories` they are not printed.
  - Memories form two corpora, project and global, each ranked alone with the existing BM25F code over two fields: `title` = the claim, `body` = context plus body. Only `is_live` memories are ranked, unless `--all-memories`.
  - After the notes (and before the page footer), for each scope that has at least one match: a header line `-- memories (project) --` or `-- memories (global) --`, then up to 5 lines `m:<handle>\t<score, two decimals>\t[<kind>, observed N]\t<claim>`; a memory that is not live (shown only with `--all-memories`) has `<status>` or `expired` added inside the brackets. With `--detail paths` the line is `m:<handle>` alone.
  - When no memory matches, the output is byte-identical to the output before this stage.
  - A memory file with an error is skipped and named once on stderr: `mem: skipped <path>: <error>`.
  - Search works with no store when `--scope memories` is given and a project exists; with `--scope all` and no store the stage 1 message and exit code stay.
  - The usage log entry gains `"memories": [<handles printed>]` when any were printed.
- `mem show` accepts `m:<handle>` among its arguments (project first, then global): it prints `== m:<handle> (<scope>)`, a line `kind: K · observed N · status S · created D` plus ` · valid until D` and ` · context: C` when set, then `## Claim`, the claim, and the body. With `--section conclusion` it stops after the claim. Notes are shown as before; an unknown `m:` handle is reported like an unknown note and makes the exit code 1.
- `mem stats` adds, after the store line, `memories: P project, G global (L live)` when either number is non-zero.

- [ ] **Step 1: Write the failing tests** in `test_memory_search.py`: with no memory, `search attention` output equals the output captured before any memory is written (same store); a project memory whose claim contains a query word appears under `-- memories (project) --` after the notes, with the exact line format; a refuted and an expired memory are absent, and present with `--all-memories` carrying `refuted` and `expired`; `--scope memories` prints no note; `--scope notes` prints no memory section; at most 5 memories per scope; a broken memory file gives one stderr line and exit 0; `show m:<handle>` prints the four parts in order and `--section conclusion` stops after the claim; `show m:nope` exits 1; `stats` prints the memories line; `search --scope memories` works with `MEM_STORE` unset and `MEM_PROJECT` set.
- [ ] **Step 2:** Run them. Expected: fail.
- [ ] **Step 3:** Implement in `mem.py`, reusing `tokenize`, `Corpus`, `term_idf` and the scoring loop of `rank` (extract the loop into a helper both use, without changing what `rank` returns).
- [ ] **Step 4:** Run the whole suite. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(memory): return memories beside notes in search, show and stats`.

### Task 4: The skill and README say how to write

Written by the main conversation (prompt text).

- [ ] **Step 1:** `plugins/memory/skills/memory/SKILL.md`: replace "Limits in this stage" with a "Writing a memory" section: when (a task ended with something learned, the owner corrected the agent, a web-research subagent returned), the one call, what goes where (project by default; `--global` only for what does not depend on the project and names no business), what exit codes 3 and 4 mean, and that a memory is experience, not fact. Keep the file within N1 and the description within N2; the description gains the writing triggers.
- [ ] **Step 2:** `plugins/memory/README.md`: the two kinds of record, the two scopes, `mem init`, the marker file, the forbidden-terms file.
- [ ] **Step 3:** Commit: `docs(memory): teach the skill to write memories`.

### Task 5: Measurements

Run by the main conversation; "Results" records counts and pass or fail only.

- [ ] **Step 1:** Parity again: the stage 1 run (20 queries and `search-eval`, disposable clone, no memory present). Expected: identical.
- [ ] **Step 2:** A headless session in a scratch git repository with the plugin loaded and a store made by `mem init`: asked to record one project lesson and then find it. Expected: the transcript shows `mem remember`, not a file write; a second session finds it with `mem search`; `git status --porcelain` in the scratch repository is empty.
- [ ] **Step 3:** In that repository, a memory written from a linked worktree is still found after `git worktree remove`.
- [ ] **Step 4:** With a forbidden-terms file, a headless `remember --global` containing a listed term is refused, and a scan of the store's `memories/` for the list finds nothing.
- [ ] **Step 5:** Tick stage 2 in [the stage plan](../2026-11-17-memory-plugin.md).

## Amendments after the pre-mortem (2026-11-17)

These override the task text above wherever they differ. Each comes from a failure the pre-mortem reproduced or measured.

### A. Writing is allowed by a marker or an explicit folder, never by a variable

- `MEM_ALLOW_WRITE` is removed everywhere (code, tests, README, skill). `store_is_writable(store: Path) -> bool` is `(store / STORE_MARKER).is_file()` and takes no `env`. The `hub_root` test fixture creates the marker; tests of the read-only guard delete it.
- The guard message becomes `mem: <command> writes to the store, which is read-only: it has no mem-store.yaml (create a store with "mem init").`
- **Global memories have their own folder**, so they can be written while the note store stays read-only. `records.memories_root(env: Mapping[str, str], store: Path | None) -> Path | None`: `env["MEM_MEMORIES"]`; else the first line of the file `agent-memory/memories` (under `XDG_CONFIG_HOME`, else `HOME/.config`); else `store / GLOBAL_DIR` when the store is writable; else `None`. A folder named through the variable or the file is written without a marker: naming it is the permission. One exception, added after review: a named folder that is the store, or inside it, is refused when the store has no marker, and the folder actually written is tested after resolving symlinks. `memory_dir("global", …)` is replaced by this function.
- `plugin.json` gains a second option, `memories` (`type: directory`, title `Global memories`, description `Folder for memories that do not belong to one project. Leave empty to keep them in the store.`), and `hooks/session-env.sh` handles it exactly as it handles `store` (file `agent-memory/memories`, `export MEM_MEMORIES=…`), with the same tests.
- `remember --global` with no folder: `mem: no folder for global memories: set the plugin's "memories" option, or MEM_MEMORIES, or use a store made with "mem init".`, exit 2.

### B. Business names: stricter gate for the global scope

- `forbidden_line` checks the claim, the context, the body and every source URL.
- `remember --global` is refused when the forbidden-terms file does not exist: `mem: global memories need the file <path> (one forbidden term per line; it may be empty), so that a business name is not written by mistake.`, exit 2. An existing empty file allows the write.

### C. Duplicates: exact match blocks, neighbours are shown

Measured: a claim and its negation had a Jaccard index of 0.89, and a real paraphrase 0.25, so no threshold separates "the same" from "the opposite".

- Exit 3 only when a live memory of the target scope has the same token sequence as the new claim (`mem.tokenize` of both). `--force` overrides.
- Otherwise the write happens, and stderr lists up to three live memories of the same scope chosen by the match rule of amendment D (the new claim as the query), under the line `related memories (if one is the same, run "mem observe m:<handle>"; if one says the opposite, keep both):`, each as `m:<handle>\t[<kind>, observed N, <created>]\t<claim>`.
- `similarity` stays in `records.py`, unused by the commands.

### D. Reading: a match rule that works on a handful of records

Measured: on a tiny corpus every common word has a positive BM25 weight, so nearly every query would print memories that share only stop words. Memories are therefore not ranked with BM25.

- `records.STOPWORDS`: a frozenset of about sixty common English words (articles, prepositions, auxiliaries, pronouns, question words).
- `records.match_memories(memories: Sequence[Memory], query_tokens: Sequence[str], today: datetime.date, *, tokenize: Callable[[str], list[str]], limit: int = 3, include_dead: bool = False) -> list[Memory]`. The distinct query tokens minus `STOPWORDS` are the terms; with no term left, the result is empty. A memory matches when its claim, context and body together contain at least half of the terms, rounded up. Order: more terms in the claim first, then more terms overall, then higher `observed`, then newer `created`, then handle. Only live memories unless `include_dead`.
- `mem search` prints memory sections **before** the notes, at most 3 lines per scope: header `-- memories (project) --` or `-- memories (global) --`, then `m:<handle>\t[memory: <kind>, observed N, <created>]\t<claim>` (no score; a dead memory shown with `--all-memories` has `, refuted`, `, superseded` or `, expired` before the bracket closes). When at least one memory line was printed and notes follow, the notes are preceded by the line `-- notes --`. The note lines themselves never change.
- No memory section is printed when `--offset` is above 0, when any of `--type`, `--topic`, `--kind`, `--status`, `--confidence`, `--level` is given, or with `--detail paths` (unless `--scope memories`, which then prints bare `m:<handle>` lines and no header). With `--also`, each query gets its own memory sections after its `== query ==` line. `no matches` goes to stderr only when neither a note nor a memory was printed.
- Parity rule, restated: for any query, removing the memory sections and the `-- notes --` line from stdout leaves the output the command gave before this stage.

### E. Smaller fixes

- `records.project_root`: the main worktree is the first `worktree` line of `git -C cwd worktree list --porcelain`. Tests: a linked worktree, a submodule (its own root, not the parent's `.git/modules`), not a repository.
- `records.observe` keeps frontmatter keys it does not know, and writes through a temporary file and `os.replace`.
- A `finding` needs at least one `--source`; without `--valid-until` it expires 90 days after `created`. Other kinds have no default expiry.
- `log_usage` accepts `root: Path | None`; `remember` and `observe` log `{"cmd": …, "scope": …}` and never the claim.
- `show` and `observe` take exact `m:` handles only; when both scopes hold the handle, the project one wins.
- `mem init` accepts a folder that already holds `.git`, `.gitignore`, `README.md` or the store's own entries.
- `--body-file` may be empty or absent.

### F. Left to the owner or to a later stage

- A note line carries no label of its own; the `-- notes --` header labels the block when memories are present. Labelling every line would end byte-for-byte parity with the original.
- The engine is not split into modules in this stage after all: new code goes in `records.py`, and the old code is split only when a change needs it.
- A search tool that honours git's ignore rules does not look inside `.memory/` once it is excluded; a subagent reaches a memory by its path or through `mem`. Stage 3's session index lists the handles.
- Whether agents call `remember` unprompted, and in English, is measured in Task 5 with a session that is not told to.

## Results

Measured on 2026-11-17; counts and pass or fail only. Each trial with an agent is one run.

| Item | Result |
|---|---|
| Tasks 1 to 3 | Done, with two review rounds and three fix rounds. Suite: 447 passed, 1 skipped |
| Task 4 | Done. Trigger case after the description change: 2 of 2 runs loaded the skill (Sonnet). No negative case was run, so over-triggering is unmeasured |
| Parity (Task 5, step 1) | Pass. 20 of 20 queries and `search-eval` identical to the original tool with no memory present |
| A store without its marker | Pass. Against a real one: `index`, `init`, `remember` from inside it, `remember --global` with the memories folder inside it or equal to it, and a `.memory` symlinked into it all exit 2; its `git status --ignored` and `.git/info/exclude` were identical before and after |
| Worktree (step 3) | Pass. A memory written from a linked worktree was found after `git worktree remove`; `git status` empty |
| Forbidden terms (step 4) | Pass. A claim with an accented spelling of a listed term was refused (exit 4); a scan of the global folder for the term found nothing |
| Agent use without a session index (step 2) | **Fail.** Told in Spanish to remember a pitfall, a Sonnet session wrote it to Claude Code's auto memory and never loaded the skill or called `mem` |
| Agent use with a three-line text at session start | Pass. The same request loaded the skill and ran `mem remember` with an English claim (`git status` empty); a new session, asked in Spanish whether to mind anything before deploying, ran `mem search` unasked, opened the memory and gave the warning. It first tried `mem read`, which is now an alias of `show` |

What this changes: the session index of stage 3 is a condition for the plugin being used at all, not an addition; and "auto memory left as it is" (an agent's choice in the design) holds only if the index tells the agent where project facts go.

Limits kept on purpose: a folder shaped like a store is protected only when it is the configured store; `observe` has no lock; a note line carries no label of its own.
