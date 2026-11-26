"""`mem-synthesize --backfill`: one reference session per synthesis, the batch and its table."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Required, TypedDict, Unpack

from syntheses import document

from synthesize import pipeline as sp
from synthesize import references as bf
from synthesize import run

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class BackfillRunOptions(TypedDict, total=False):
    """Keyword options of `run_backfill`: `root` is the run folder (default: a new one in the state folder, mode
    0700); `rows_out` receives the rows one by one."""

    out: Callable[[str], None]
    root: Path | None
    rows_out: list[dict] | None


class BackfillOneOptions(TypedDict):
    parts: list[dict]
    settings: Path
    log: Callable[[str], None]
    budget_left: float | None
    done: dict


class BackfillBatchOptions(TypedDict, total=False):
    done: Required[dict]
    out: Callable[[str], None]
    root: Path | None
    rows_out: list[dict] | None


def done_file() -> Path:
    return run.state_dir() / "backfill-done.json"


def _backfill_row(handle: str, parts: int, units: int, status: str = "ok") -> dict:
    return {
        "synthesis": handle,
        "parts": parts,
        "units": units,
        "proposed": 0,
        "applied": 0,
        "refused": 0,
        "none": 0,
        "unreadable": 0,
        "repeated": 0,
        "mem_check": "-",
        "cost": 0.0,
        "status": status,
    }


@dataclass
class _BackfillRun:
    """One synthesis's reference session: its steps put what they learn in `row` and in `done`."""

    claude: str
    env: dict
    root: Path
    store: Path
    handle: str
    parts: list[dict]
    settings: Path
    log: Callable[[str], None]
    budget_left: float | None
    done: dict
    row: dict

    @property
    def path(self) -> Path:
        return self.store / "syntheses" / f"{self.handle}.md"

    @property
    def work(self) -> Path:
        return self.root / self.handle / "work"

    def steps(self) -> None:
        session = self._session()
        failure = self._session_failure(session)
        if failure:
            self.row["status"] = failure
            return
        found, self.row["unreadable"], self.row["repeated"], nothing = bf.parse_answer(
            session["answer"]
        )
        if not found and not nothing:
            self.row["status"] = "failed: no readable line in the answer"
            return
        proposals = self._proposals(found)
        self.row["proposed"] = len(proposals)
        if proposals and not self._apply(proposals):
            return
        self._mark_done(found)

    def _session(self) -> dict:
        units, notes = bf.write_input(self.path, self.parts, self.work)
        prompt = sp.brief(
            "backfill", SLUG=self.handle, UNITS_FILE=str(units), NOTES_FILE=str(notes)
        )
        cmd = bf.session_cmd(
            self.claude,
            prompt,
            self.work,
            self.store,
            settings=self.settings,
            max_budget=self.budget_left,
        )
        s = bf.run_session(cmd, self.work, self.env, self.root / self.handle / "backfill.jsonl")
        self.row["cost"] = s["cost"]
        self.log(
            f"{self.handle}: session has_result={s['has_result']} error={s['error']} cost={s['cost']:.3f} "
            f"wall={s['wall']:.0f}s denied={s['denied']} tool_errors={s['tool_errors']}"
        )
        return s

    @staticmethod
    def _session_failure(session: dict) -> str | None:
        if not session["has_result"]:
            return f"failed: {sp.NO_COST}"
        if session["error"]:
            return "failed: session error"
        return None

    @staticmethod
    def _unit_text(by_part: dict[str, dict], part: str, number: int) -> str:
        if part not in by_part:
            return "?"
        return next((u.plain for u in by_part[part]["units"] if u.n == number), "?")

    def _proposals(self, found: list) -> list[str]:
        proposals = []
        by_part = {p["handle"]: p for p in self.parts}
        for part, number, target in found:
            if target == "none":
                self.row["none"] += 1
                text = self._unit_text(by_part, part, number)
                self.log(f"{self.handle}: none: {part} | {number} | {' '.join(text.split())}")
            else:
                proposals.append(f"{part} | {number} | add {target}")
        return proposals

    def _apply(self, proposals: list[str]) -> bool:
        """Apply the proposals with `mem synthesis refs`; False when the command failed (`status` says so)."""
        file = self.work / "proposals.txt"
        file.write_text("".join(f"{ln}\n" for ln in proposals), encoding="utf-8")
        out = sp.mem(
            self.store, self.env, "synthesis", "refs", f"s:{self.handle}", "--file", str(file)
        )
        total = sp.REFS_TOTAL.findall(out.stdout)
        for line in out.stdout.splitlines():
            if line.startswith("refused: "):
                self.log(f"{self.handle}: {line}")
        if out.returncode or not total:
            self.row["status"] = (
                "failed: refs: "
                + (out.stderr.strip() or out.stdout.strip() or f"exit {out.returncode}")[:80]
            )
            return False
        added, _, refused = map(int, total[-1])
        self.row.update(applied=added, refused=refused)
        return True

    def _mark_done(self, found: list) -> None:
        now = {x.handle: document.fingerprint(x.text) for x in document.load_one(self.path).parts}
        # A part is marked done when the answer had no unreadable line (every selected part, even one without a line:
        # the session judged it had nothing to link) or when a readable line names it; with an unreadable line the
        # other parts may be the ones it was about, so they are sent again next run.
        named = {part for part, _, _ in found}
        for p in self.parts:  # the fingerprint ignores references, so adding them keeps it
            if p["handle"] in now and (not self.row["unreadable"] or p["handle"] in named):
                self.done[p["handle"]] = now[p["handle"]]


def backfill_one(
    claude: str,
    env: dict,
    root: Path,
    store: Path,
    handle: str,
    **options: Unpack[BackfillOneOptions],
) -> dict:
    """One session for the selected `parts` of synthesis `handle`; the row never raises. Marks the parts in `done`
    (the synthesis's entry of the done list: part handle -> fingerprint) only when the answer was parsed."""
    parts = options["parts"]
    step = _BackfillRun(
        claude=claude,
        env=env,
        root=root,
        store=store,
        handle=handle,
        parts=parts,
        settings=options["settings"],
        log=options["log"],
        budget_left=options["budget_left"],
        done=options["done"],
        row=_backfill_row(handle, len(parts), sum(len(p["units"]) for p in parts)),
    )
    step.work.mkdir(parents=True)
    try:
        step.steps()
    except Exception as exc:  # a failed synthesis must not stop the run
        logger.debug("synthesis %s: backfill failed", handle, exc_info=True)
        step.row["status"] = f"failed: {type(exc).__name__}: {exc}"[:100]
    finally:
        step.row["mem_check"] = sp.mem(store, env, "check").returncode
        step.log(f"{handle}: {step.row}")
    return step.row


def backfill_table(rows: list[dict]) -> str:
    cols = (
        "synthesis",
        "parts",
        "units",
        "proposed",
        "applied",
        "refused",
        "none",
        "unreadable",
        "repeated",
        "mem_check",
    )
    total = (
        "total",
        *(sum(r[c] for r in rows) for c in cols[1:9]),
        "",
        f"{sum(r['cost'] for r in rows):.3f}",
        "",
    )
    return run._aligned([
        run.BACKFILL_HEADER,
        *((*(r[c] for c in cols), f"{r['cost']:.3f}", r["status"]) for r in rows),
        total,
    ])


@dataclass
class _BackfillBatch:
    """The due syntheses of one `--backfill` run, one after the other, with the budget they share."""

    claude: str
    env: dict
    root: Path
    store: Path
    settings: Path
    log: Callable[[str], None]
    budget: float
    done: dict
    rows_out: list[dict] | None
    rows: list[dict] = field(default_factory=list)
    spent: float = 0.0
    unknown: bool = False

    def run(self, due: dict[str, list[dict]]) -> None:
        for n, parts in due.items():
            row = (
                self._skipped(n, parts)
                if self.spent >= self.budget or self.unknown
                else self._one(n, parts)
            )
            self.rows.append(row)
            if self.rows_out is not None:
                self.rows_out.append(row)

    def _skipped(self, n: str, parts: list[dict]) -> dict:
        why = "an earlier session returned no cost" if self.unknown else "budget"
        return _backfill_row(n, len(parts), 0, f"not started: {why}")

    def _one(self, n: str, parts: list[dict]) -> dict:
        self.log(f"{n}: start (spent {self.spent:.3f})")
        row = backfill_one(
            self.claude,
            self.env,
            self.root,
            self.store,
            n,
            parts=parts,
            settings=self.settings,
            log=self.log,
            budget_left=self.budget - self.spent,
            done=self.done.setdefault(n, {}),
        )
        self.spent += row["cost"]
        if self.done[n]:
            self._save_done(n, row)
        self.unknown = sp.NO_COST in row["status"]
        return row

    def _save_done(self, n: str, row: dict) -> None:
        try:
            bf.save_done(done_file(), str(Path(self.store).resolve()), n, self.done[n])
        except (
            Exception
        ) as exc:  # the references are applied: keep going to the commit and the table
            logger.debug("synthesis %s: done list not saved", n, exc_info=True)
            row["status"] = f"ok, done list not saved: {exc}"[:100]


def _backfill_root(root: Path | None) -> Path:
    if root is None:
        run.state_dir().mkdir(parents=True, exist_ok=True)
        return Path(
            tempfile.mkdtemp(
                prefix=f"backfill-{time.strftime('%Y%m%d-%H%M%S')}-", dir=run.state_dir()
            )
        )  # mode 0700
    root.mkdir(mode=0o700, parents=True)
    return root


def _backfill_dry_run(
    out: Callable[[str], None], due: dict[str, list[dict]], skipped: int, budget: float
) -> None:
    for n, parts in due.items():
        out(
            f"s:{n}: "
            + "; ".join(
                f"{p['handle']} ({len(p['bare'])} of {len(p['units'])} units without reference)"
                for p in parts
            )
        )
    out(
        f"mem-synthesize --backfill dry run: {len(due)} syntheses ({skipped} skipped); estimated cost "
        f"{len(due) * run.ESTIMATE_PER_BACKFILL:.2f} USD (budget {budget:.2f})"
    )


def _backfill_sessions(
    claude: str,
    env: dict,
    store: Path,
    due: dict[str, list[dict]],
    budget: float,
    **options: Unpack[BackfillBatchOptions],
) -> int:
    out = options.get("out", run.say)
    root = _backfill_root(options.get("root"))
    log_file = root / "log.txt"
    log = run._file_logger(log_file)
    out(
        f"mem-synthesize --backfill: {len(due)} syntheses ({', '.join(due)}), budget {budget:.2f} USD, log {log_file}"
    )
    settings = root / "settings.json"
    settings.write_text(
        json.dumps({"disableAllHooks": True}), encoding="utf-8"
    )  # no session-end hook may commit between our two
    label = ", ".join(due)
    run.history_commit(store, env, f"mem-synthesize: before backfill {label}", log)
    batch = _BackfillBatch(
        claude=claude,
        env=env,
        root=root,
        store=store,
        settings=settings,
        log=log,
        budget=budget,
        done=options["done"],
        rows_out=options.get("rows_out"),
    )
    batch.run(due)
    run.history_commit(store, env, f"mem-synthesize: after backfill {label}", log)
    out(backfill_table(batch.rows))
    out(f"total cost USD {batch.spent:.3f}; log {log_file}")
    return 0 if all(r["status"] == "ok" for r in batch.rows) else 1


def run_backfill(
    claude: str | None,
    store: Path,
    handles: list[str],
    budget: float,
    dry_run: bool,
    **options: Unpack[BackfillRunOptions],
) -> int:
    """Backfill inline references. `handles`: `s:<handle>` or bare handles; none means every synthesis of the store."""
    out = options.get("out", run.say)
    env = run.session_env(store)
    names = [h.removeprefix("s:") for h in handles] or [
        s.path.stem for s in document.load(store / "syntheses")
    ]
    missing = [n for n in names if not (store / "syntheses" / f"{n}.md").is_file()]
    if missing:
        print(f"mem-synthesize: no synthesis named {', '.join(missing)}", file=sys.stderr)
        return 2
    all_done, readable = bf.load_done(done_file())
    if not readable:
        print(
            f"mem-synthesize: {done_file()} is not a readable done list; move it away (the next run then treats every "
            f"part as due)",
            file=sys.stderr,
        )
        return 1
    done = all_done.setdefault(str(Path(store).resolve()), {})
    due = {
        n: p for n in names if (p := bf.select(store / "syntheses" / f"{n}.md", done.get(n, {})))
    }
    skipped = len(names) - len(due)
    if not due:
        out(f"mem-synthesize --backfill: nothing to do ({skipped} syntheses skipped: no due part)")
        return 0
    if dry_run:
        _backfill_dry_run(out, due, skipped, budget)
        return 0
    if not claude:
        print(
            "mem-synthesize: no claude binary (use --claude, or CLAUDE_CODE_EXECPATH)",
            file=sys.stderr,
        )
        return 2
    return _backfill_sessions(claude, env, store, due, budget, done=done, **options)
