"""`mem-synthesize` for topics without a synthesis: one pipeline per topic, then the reference step."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Required, TypedDict, Unpack

from synthesize import backfill
from synthesize import pipeline as sp
from synthesize import references as bf
from synthesize import run as sr

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class RunOptions(backfill.BackfillRunOptions, total=False):
    """Keyword options of `run`; `references=False` skips the last step (adding references)."""

    references: bool


class TopicOptions(TypedDict, total=False):
    settings: Required[Path]
    log: Required[Callable[[str], None]]
    budget_left: Callable[[], float] | None
    references: bool


class ReferenceOptions(TypedDict, total=False):
    settings: Required[Path]
    log: Required[Callable[[str], None]]
    budget_left: Required[float | None]
    done: dict | None


class TopicReferenceOptions(TypedDict):
    settings: Path
    log: Callable[[str], None]
    row: dict
    budget: float | None


def new_row(topic: str, status: str = "ok") -> dict:
    return {
        "topic": topic,
        "parts": 0,
        "attached": 0,
        "fixed": 0,
        "deleted": 0,
        "reverted": 0,
        "refs": 0,
        "refs_refused": 0,
        "refs_none": 0,
        "mem_check": "-",
        "cost": 0.0,
        "status": status,
    }


def add_references(
    claude: str,
    env: dict,
    root: Path,
    store: Path,
    handle: str,
    **options: Unpack[ReferenceOptions],
) -> dict | None:
    """The reference step, one implementation for `--backfill`'s normal-mode twin and the trial harness: one read-only
    session for the due parts of synthesis `handle` (`backfill_one`), None when no part is due. `root` holds the
    step's own folder `root/<handle>`; `done` receives the parts the answer settled."""
    parts = bf.select(store / "syntheses" / f"{handle}.md", {})
    if not parts:
        return None
    done = options.get("done")
    return backfill.backfill_one(
        claude,
        env,
        root,
        store,
        handle,
        parts=parts,
        settings=options["settings"],
        log=options["log"],
        budget_left=options["budget_left"],
        done={} if done is None else done,
    )


@dataclass
class _TopicRun:
    """The state of one topic's pipeline: its steps put what they learn in `row`, and the sessions they ran in
    `sessions`."""

    claude: str
    env: dict
    base: Path
    store: Path
    topic: str
    settings: Path
    log: Callable[[str], None]
    budget_left: Callable[[], float] | None
    references: bool
    row: dict = field(init=False)
    sessions: list[dict] = field(default_factory=list)
    ref_cost: float = 0.0

    def __post_init__(self) -> None:
        self.row = new_row(self.topic)

    @property
    def work(self) -> Path:
        return self.base / "work"

    @property
    def synthesis(self) -> Path:
        return self.store / "syntheses" / f"{self.topic}.md"

    def left(self) -> float:
        """USD still allowed for this topic's next session (only with a budget)."""
        if self.budget_left is None:
            msg = "no budget to count against"
            raise TypeError(msg)
        return self.budget_left() - sum(s["cost"] for s in self.sessions)

    def remaining(self) -> float | None:
        return None if self.budget_left is None else self.left()

    def execute(self) -> dict:
        self.work.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        try:
            self._steps()
        except Exception as exc:  # a failed topic must not stop the run
            logger.debug("topic %s failed", self.topic, exc_info=True)
            self.row["status"] = f"failed: {type(exc).__name__}: {exc}"[:100]
        finally:
            self._close()
        return self.row

    def _steps(self) -> None:
        if self.synthesis.exists():
            self.row["status"] = "failed: a synthesis exists already"
            return
        answer = self._write()
        if answer is None or not self._check_and_fix():
            return
        self._attach(answer)
        self.row["parts"] = sr.count_parts(self.synthesis)
        self.row["mem_check"] = sp.mem(self.store, self.env, "check").returncode
        if self.references:
            self.ref_cost = add_topic_references(
                self.claude,
                self.env,
                self.base,
                self.store,
                self.topic,
                settings=self.settings,
                log=self.log,
                row=self.row,
                budget=self.remaining(),
            )

    def _write(self) -> str | None:
        """The writer session: its answer, or None when the topic stopped (`status` says why)."""
        remaining = self.remaining()
        if remaining is not None and remaining <= 0:
            self.row["status"] = "failed: budget spent"
            return None
        prompt = (
            f"Topic: {self.topic}\nSlug: {self.topic}\nStore: {self.store}\nWork folder: {self.work}\n"
            f"The memory-synthesis skill file: {sp.SKILL}"
        )
        w = sp.run_session(
            self.claude,
            "haiku",
            prompt,
            self.work,
            self.settings,
            env=self.env,
            log=self.base / "01-writer.jsonl",
            effort="high",
            agent=sr.AGENT,
            max_budget=remaining,
            read_roots=sp.session_roots(self.store, self.env, self.work),
        )
        w.update(role="writer", model="haiku", costs=sp.cost_by_family(w["model_usage"]))
        self.sessions.append(sp.summary(w))
        answer = w["answer"].strip()
        self.row["status"] = self._writer_status(w, answer)
        return answer if self.row["status"] == "ok" else None

    def _writer_status(self, writer: dict, answer: str) -> str:
        if self.budget_left is not None and not writer["has_result"]:
            return f"failed: {sp.NO_COST}"
        if not self.sessions[-1]["ok"]:
            return "failed: writer session"
        if answer.startswith("STOP"):
            return f"failed: {answer.splitlines()[0][:80]}"
        if not self.synthesis.is_file():
            return "failed: no synthesis written"
        return "ok"

    def _check_and_fix(self) -> bool:
        """The check, fix and delete-only steps; False when the loop ended the topic (`status` says why)."""
        done = sp.lean_loop(
            self.claude,
            self.env,
            self.base,
            self.store,
            self.work,
            settings=self.settings,
            topic=self.topic,
            sessions=self.sessions,
            left=self.left if self.budget_left is not None else None,
            read_roots=sp.session_roots(self.store, self.env, self.work),
        )
        self.log(
            f"{self.topic}: loop {json.dumps({k: v for k, v in done.items() if k != 'arm_count'})}"
        )
        if done["why"]:
            self.row["status"] = f"failed: {done['why']}"
            return False
        first = done["arm_count"]
        self.row["deleted"] = done["deleted"]
        self.row["reverted"] = len(done["reverted"])
        self.row["fixed"] = max(0, (first["unsupported"] if first else 0) - done["deleted"])
        return True

    def _attach(self, answer: str) -> None:
        for rel, target in sr.attach_lines(answer):
            self.row["attached"] += self._attach_one(rel, target)

    def _attach_one(self, rel: str, target: str) -> bool:
        note = self.store / rel
        if not note.is_file():
            self.log(f"{self.topic}: attach skipped, no note {rel}")
            return False
        current = sr.part_of(note)
        if current and not current.startswith(f"{self.topic}#"):
            self.log(f"{self.topic}: attach skipped, {rel} is part of s:{current}")
            return False
        out = sp.mem(self.store, self.env, "synthesis", "attach", rel, target)
        if out.returncode:
            self.log(f"{self.topic}: attach failed {rel} {target}: {out.stderr.strip()}")
        return out.returncode == 0

    def _close(self) -> None:
        self.row["cost"] = sum(s["cost"] for s in self.sessions) + self.ref_cost
        if self.synthesis.is_file() and not self.row["parts"]:
            self.row["parts"] = sr.count_parts(self.synthesis)
        for s in self.sessions:
            self.log(
                f"{self.topic}: {s['role']} {s['model']} ok={s['ok']} cost={s['cost']:.3f} wall={s['wall']:.0f}s "
                f"denied={s['denied']} tool_errors={s['tool_errors']}"
            )


def run_topic(
    claude: str,
    env: dict,
    root: Path,
    store: Path,
    topic: str,
    **options: Unpack[TopicOptions],
) -> dict:
    """Run the pipeline for one topic; the row never raises: a failed step is `status`. The last step adds references:
    its failure leaves the synthesis as the loop left it (`status` says so) and a later `--backfill` sends it."""
    return _TopicRun(
        claude=claude,
        env=env,
        base=root / topic,
        store=store,
        topic=topic,
        settings=options["settings"],
        log=options["log"],
        budget_left=options.get("budget_left"),
        references=options.get("references", True),
    ).execute()


def _reference_status(result: dict, topic: str) -> str | None:
    """The topic's new `status` after the reference step, None when the step left it a pass."""
    if (
        result["applied"] and result["mem_check"] != 0
    ):  # the step wrote, and the store no longer checks
        return f"failed: mem check exit {result['mem_check']} after references (undo: mem restore s:{topic})"
    if result["status"] != "ok":
        return f"ok, references not added: {result['status'].removeprefix('failed: ')}"[:100]
    return None


def _save_done_list(store: Path, topic: str, done: dict, log: Callable[[str], None]) -> None:
    try:
        bf.save_done(backfill.done_file(), str(Path(store).resolve()), topic, done)
    except Exception as exc:  # the references are applied; the next `--backfill` just asks again
        logger.debug("%s: done list not saved", topic, exc_info=True)
        log(f"{topic}: done list not saved: {exc}")


def add_topic_references(
    claude: str,
    env: dict,
    base: Path,
    store: Path,
    topic: str,
    **options: Unpack[TopicReferenceOptions],
) -> float:
    """Run the reference step after a successful topic and put its figures in `row`; returns its cost. A step that
    did not run or did not finish leaves the topic a pass (`ok, references not added: ...`); the one failure is a
    `mem check` that no longer exits 0 after references were written. A success is marked in the done list as
    `--backfill` marks it; a failure is not, so a later `--backfill` sends the synthesis."""
    row, budget = options["row"], options["budget"]
    if (
        budget is not None and budget < sr.ESTIMATE_PER_BACKFILL
    ):  # a session capped below its usual cost only spends
        row["status"] = "ok, references not added: budget spent"
        return 0.0
    done: dict = {}
    try:
        result = add_references(
            claude,
            env,
            base / "references",
            store,
            topic,
            settings=options["settings"],
            log=options["log"],
            budget_left=budget,
            done=done,
        )
    except Exception as exc:  # selecting the parts failed: the synthesis stays as the loop left it
        logger.debug("topic %s: references not added", topic, exc_info=True)
        row["status"] = f"ok, references not added: {type(exc).__name__}: {exc}"[:100]
        return 0.0
    if result is None:
        return 0.0
    row.update(
        refs=result["applied"],
        refs_refused=result["refused"],
        refs_none=result["none"],
        mem_check=result["mem_check"],
    )
    status = _reference_status(result, topic)
    if status is not None:
        row["status"] = status
    elif done:
        _save_done_list(store, topic, done, options["log"])
    return result["cost"]


def table(rows: list[dict]) -> str:
    lines = [
        sr.HEADER,
        *(
            (
                r["topic"],
                r["parts"],
                r["attached"],
                r["fixed"],
                r["deleted"],
                r["reverted"],
                r["refs"],
                r["refs_refused"],
                r["refs_none"],
                r["mem_check"],
                f"{r['cost']:.3f}",
                r["status"],
            )
            for r in rows
        ),
    ]
    return sr._aligned(lines)


def _dry_run_line(topics: list[str], budget: float, *, references: bool) -> str:
    each = sr.ESTIMATE_PER_TOPIC + (sr.ESTIMATE_PER_BACKFILL if references else 0.0)
    step = (
        "each ends with a reference step (--no-references skips it); "
        if references
        else "no reference step; "
    )
    return (
        f"mem-synthesize dry run: {len(topics)} topics: {', '.join(topics)}; {step}"
        f"estimated cost {len(topics) * each:.2f} USD (budget {budget:.2f})"
    )


@dataclass
class _TopicBatch:
    """The topics of one run, one after the other, with the budget they share."""

    claude: str
    env: dict
    root: Path
    store: Path
    settings: Path
    log: Callable[[str], None]
    budget: float
    references: bool
    rows_out: list[dict] | None
    rows: list[dict] = field(default_factory=list)
    spent: float = 0.0
    unknown: bool = False

    def run(self, topics: list[str]) -> None:
        for topic in topics:
            if self.spent >= self.budget or self.unknown:
                row = new_row(topic, "not started: budget")
            else:
                row = self._topic(topic)
            self.rows.append(row)
            if self.rows_out is not None:
                self.rows_out.append(row)

    def _topic(self, topic: str) -> dict:
        self.log(f"{topic}: start (spent {self.spent:.3f})")
        remaining = self.budget - self.spent
        row = run_topic(
            self.claude,
            self.env,
            self.root,
            self.store,
            topic,
            settings=self.settings,
            log=self.log,
            budget_left=lambda: remaining,
            references=self.references,
        )
        self.spent += row["cost"]
        self.log(f"{topic}: {row}")
        if sp.NO_COST in row["status"]:
            self.unknown = True
        return row


def _synthesize(
    claude: str,
    env: dict,
    store: Path,
    topics: list[str],
    budget: float,
    **options: Unpack[RunOptions],
) -> int:
    out = options.get("out", sr.say)
    root = (
        options.get("root")
        or sr.state_dir() / f"synthesize-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    )
    root.mkdir(mode=0o700, parents=True)  # the sessions' transcripts are private
    log_file = root / "log.txt"
    log = sr._file_logger(log_file)
    out(
        f"mem-synthesize: {len(topics)} topics ({', '.join(topics)}), budget {budget:.2f} USD, log {log_file}"
    )
    settings = root / "settings.json"
    settings.write_text(
        json.dumps({
            "pluginConfigs": {"memory": {"options": {"store": str(store)}}},
            "disableAllHooks": True,
        }),
        encoding="utf-8",
    )  # no session-end hook may commit between our two
    label = ", ".join(topics)
    sr.history_commit(store, env, f"mem-synthesize: before {label}", log)
    batch = _TopicBatch(
        claude=claude,
        env=env,
        root=root,
        store=store,
        settings=settings,
        log=log,
        budget=budget,
        references=options.get("references", True),
        rows_out=options.get("rows_out"),
    )
    batch.run(topics)
    sr.history_commit(store, env, f"mem-synthesize: after {label}", log)
    out(table(batch.rows))
    out(f"total cost USD {batch.spent:.3f}; log {log_file}")
    return (
        0 if all(r["status"].split(",")[0] == "ok" for r in batch.rows) else 1
    )  # "ok, references not added" is a pass


def run(
    claude: str | None,
    store: Path,
    topics: list[str],
    budget: float,
    dry_run: bool,
    **options: Unpack[RunOptions],
) -> int:
    """`root`: the run folder (default: a new one in the state folder, mode 0700); `rows_out` receives the rows;
    `references=False` skips the last step (adding references)."""
    out = options.get("out", sr.say)
    env = sr.session_env(store)
    if not topics:
        found = sp.mem(store, env, "curate", "--notes")
        if found.returncode:
            print(
                f"mem-synthesize: mem curate --notes failed: {found.stderr.strip()}",
                file=sys.stderr,
            )
            return 2
        topics = sr.topics_without_synthesis(found.stdout)
    if not topics:
        out("mem-synthesize: no topic without a synthesis")
        return 0
    if dry_run:
        out(_dry_run_line(topics, budget, references=options.get("references", True)))
        return 0
    if not claude:
        print(
            "mem-synthesize: no claude binary (use --claude, or CLAUDE_CODE_EXECPATH)",
            file=sys.stderr,
        )
        return 2
    return _synthesize(claude, env, store, topics, budget, **options)
