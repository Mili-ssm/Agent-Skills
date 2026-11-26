"""Settling new global memories against their look-alikes (`mem settle`): which pairs a model session is asked to
judge, how its verdicts are enforced, and the state and log that make the result visible and reversible.

A model never acts: it writes verdicts, and `apply_verdicts` runs only what the rules below allow, through the same
code as `mem merge`, `mem supersede` and `mem distinct` (the callables in `Actions`), so every change has its
`.curation-log` entries and `mem restore`. The older record is always the one dropped or superseded.

State and log sit beside the global memories: `.settle-state.json` (the handles already judged, the end of the last
apply, the last log number acknowledged) and `.settle-log` (JSON lines). `mem-auto` keeps its own window elsewhere;
nothing here reads or writes it. Standard library plus `records`."""

from __future__ import annotations

import contextlib
import datetime
import fcntl
import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict, Unpack

from core import jobs, safe_io, store_git
from store import records

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)

STATE_NAME = ".settle-state.json"
LOG_NAME = ".settle-log"
LOCK_NAME = ".settle-lock"
# a pair offered this many times without an applied decision is left as it is
OFFERS_BEFORE_LEFT = 2
DECISIONS = ("merge", "supersede", "distinct", "nothing")
CLAIM_WIDTH = 70


class Actions(NamedTuple):
    """The existing code paths, each returning the line it prints. Undo records are written inside them."""

    merge: Callable[[records.Memory, records.Memory, datetime.date], list[str]]  # keep, drop
    supersede: Callable[[records.Memory, records.Memory, datetime.date], list[str]]  # old, new
    distinct: Callable[[records.Memory, records.Memory, datetime.date], list[str]]


def _stems(folder: Path) -> list[str]:
    try:
        return sorted(p.stem for p in folder.glob("*.md") if p.is_file())
    except OSError:
        return []


class BusyError(ValueError):
    pass


Busy = BusyError


class NoListingError(ValueError):
    """`apply` ran with no `pending` listing recorded; `lines` are the refusals, one per row."""

    def __init__(self, lines: list[str]):
        super().__init__("run `mem settle pending` first: nothing was changed")
        self.lines = lines


NoListing = NoListingError


class NothingToUndoError(ValueError):
    pass


NothingToUndo = NothingToUndoError


@contextlib.contextmanager
def locked(folder: Path):
    """Exclusive, non-blocking lock beside the state: two settle commands never change it at once."""
    fd = os.open(folder / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise BusyError(
            "another mem settle command is running: nothing was changed, try again later"
        ) from None
    try:
        yield
    finally:
        os.close(fd)  # closing releases the flock


def load_state(folder: Path) -> dict:
    """The settle state. The first use (no state file) records every memory that exists as judged, except those in
    quarantine, which are new once released: only records written after that are new. This writes the file, so an
    unwritable folder raises OSError. A file that exists but cannot be read as a state raises ValueError and is never
    replaced."""
    path = folder / STATE_NAME
    if not path.exists():
        state = {
            "judged": _unjudged_stems(folder, set()),
            "last_apply": None,
            "acked": 0,
            "offered": None,
        }
        save_state(folder, state)
        return state
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"{STATE_NAME} cannot be read ({exc}): nothing was changed; repair or remove it by hand"
        ) from exc
    if not _is_state(state):
        raise ValueError(
            f"{STATE_NAME} has no list of judged memories: nothing was changed; repair or remove it by hand"
        )
    return state


def _is_state(state: object) -> bool:
    return isinstance(state, dict) and isinstance(state.get("judged"), list)


def _ensure_ignored(folder: Path) -> None:
    """The store's .gitignore keeps the settle files out of history; `mem history init` writes it, so a store that
    was made a repository before this feature gets the lines when settle first writes here."""
    for candidate in (folder, folder.parent):  # the store holds the memories folder
        if store_git.is_repo(candidate):
            store_git.ensure_ignored(candidate)
            return


def save_state(folder: Path, state: dict) -> None:
    if not (folder / STATE_NAME).exists():
        _ensure_ignored(folder)
    jobs.write_json(folder / STATE_NAME, state)


def _counts_as_new(m: records.Memory, judged: set[str], today: datetime.date) -> bool:
    return (
        m.handle not in judged
        and records.is_live(m, today)
        and m.origin not in {"pipeline", "web"}
        and not records.quarantined(m)
    )  # settling leaves quarantine alone, in its state too


def _unjudged_stems(folder: Path, judged: set[str]) -> list[str]:
    """Stems not yet judged and not in quarantine: a record in quarantine is invisible here, so it is offered as new
    only once it is released. Parses only the files whose stem is not judged."""
    return [
        s
        for s in _stems(folder)
        if s not in judged and not records.quarantined(records._parse(folder / f"{s}.md", "global"))
    ]


def unjudged_count(folder: Path, state: dict, today: datetime.date) -> int:
    """Live memories not yet judged, other than those of origin pipeline or web or in quarantine. Parses only the files whose handle is not in the judged list."""
    judged = set(state["judged"])
    count = 0
    for stem in _stems(folder):
        if stem not in judged and _counts_as_new(
            records._parse(folder / f"{stem}.md", "global"), judged, today
        ):
            count += 1
    return count


def due(folder: Path, minutes: float, now: float, today: datetime.date) -> int | None:
    """The number of new memories when a settling run is due (some exist and the last apply ended more than
    `minutes` ago, or never), else None."""
    state = load_state(folder)
    last = state.get("last_apply")
    if isinstance(last, (int, float)) and now - last <= minutes * 60:
        return None
    count = unjudged_count(folder, state, today)
    return count or None


def newer_first(
    a: records.Memory, b: records.Memory, judged: set[str]
) -> tuple[records.Memory, records.Memory] | None:
    """(newer, older), or None when it cannot be told. Creation dates have day precision, so: the one record not yet
    judged is the newer; otherwise the later `created`; the same date is undecidable."""
    if (a.handle in judged) != (b.handle in judged):
        return (b, a) if a.handle in judged else (a, b)
    da, db = (a.created or datetime.date.min), (b.created or datetime.date.min)
    if da == db:
        return None
    return (a, b) if da > db else (b, a)


def pending(
    memories: Sequence[records.Memory], state: dict, today: datetime.date, *, tokenize
) -> list[dict]:
    """The look-alike pairs to judge: queue pairs of live global memories where one side is new. `newer` is null
    when it cannot be told (see `newer_first`)."""
    judged = set(state["judged"])
    out = []
    for a, b, _ in records.pairs(memories, today, tokenize=tokenize):
        if records.quarantined(a) or records.quarantined(b):
            continue  # settling leaves quarantine alone
        if not (_counts_as_new(a, judged, today) or _counts_as_new(b, judged, today)):
            continue
        order = newer_first(a, b, judged)
        out.append({
            "pair": len(out) + 1,
            "a": a.handle,
            "b": b.handle,
            "claim_a": " ".join(a.claim.split()),
            "claim_b": " ".join(b.claim.split()),
            "newer": order[0].handle if order else None,
            "flagged_words": records.flagged_words(a.claim, b.claim),
        })
    return out


def _key(pair) -> str:
    return "|".join(sorted(pair))


def offer(folder: Path, state: dict, found: list[dict], now: float) -> None:
    """Remember what this look at the queue covered: the handles, and the pairs, and count one more offer for each
    pair shown. What is written afterwards stays new for the next run. With no pair to judge, the handles examined are judged at once and the run counts as done, so
    `due` stops reporting work and no model session is needed."""
    judged = set(state["judged"])
    unjudged = _unjudged_stems(folder, judged)
    if found:
        state["offered"] = unjudged
        state["offered_pairs"] = [sorted((p["a"], p["b"])) for p in found]
        before = state.get("offers") or {}
        state["offers"] = {
            _key((p["a"], p["b"])): int(before.get(_key((p["a"], p["b"])), 0)) + 1 for p in found
        }
    else:
        state["judged"] = sorted(judged | set(unjudged))
        state["offered"] = state["offered_pairs"] = None
        state["offers"] = {}
        state["last_apply"] = now
    save_state(folder, state)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_log(folder: Path) -> list[dict]:
    try:
        lines = (folder / LOG_NAME).read_text(encoding="utf-8").split("\n")
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def _append_log(folder: Path, entry: dict) -> None:
    safe_io.append_text(folder / LOG_NAME, json.dumps(entry, ensure_ascii=False) + "\n")


def settlings(folder: Path) -> list[dict]:
    """The logged settlings, each with `undone` (the date, or None)."""
    undone = {e["undo"]: e.get("date") for e in read_log(folder) if isinstance(e.get("undo"), int)}
    return [
        {**e, "undone": undone.get(e["seq"])}
        for e in read_log(folder)
        if isinstance(e.get("seq"), int)
    ]


def _short(text: str) -> str:
    return text if len(text) <= CLAIM_WIDTH else text[: CLAIM_WIDTH - 1].rstrip() + "…"


def _claims(older: records.Memory, newer: records.Memory) -> dict:
    return {
        "older": _short(" ".join(older.claim.split())),
        "newer": _short(" ".join(newer.claim.split())),
    }


class VerdictOptions(TypedDict):
    """The keyword arguments of `apply_verdicts`."""

    actions: Actions
    reason_ok: Callable[[str], bool]
    tokenize: Callable[..., Any]


class _Row(NamedTuple):
    number: int
    a: str
    b: str
    decision: str
    reason: str


class _Done(NamedTuple):
    """What an action did to a pair: the sides, the files it changed, the line it printed, what it raised."""

    newer: records.Memory
    older: records.Memory
    files: dict
    out: list[str]
    failure: Exception | None


_ROW_KEYS = ("a", "b", "decision", "reason")


def _parse_row(number: int, row: object) -> _Row | None:
    if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in _ROW_KEYS):
        return None
    a, b = (row[k].strip().removeprefix("m:") for k in ("a", "b"))
    return _Row(number, a, b, row["decision"], " ".join(row["reason"].split()))


def _is_fatal(failure: Exception) -> bool:
    """Only `OSError` and `ValueError` from an action are a row failure; any other exception is raised."""
    return not isinstance(failure, (OSError, ValueError))


def _act(
    actions: Actions,
    decision: str,
    newer: records.Memory,
    older: records.Memory,
    today: datetime.date,
) -> list[str]:
    if decision == "merge":
        return actions.merge(newer, older, today)
    if decision == "supersede":
        return actions.supersede(older, newer, today)
    return actions.distinct(older, newer, today)


def _attempt(
    actions: Actions,
    decision: str,
    newer: records.Memory,
    older: records.Memory,
    today: datetime.date,
) -> tuple[list[str], Exception | None]:
    try:
        return _act(actions, decision, newer, older, today), None
    except Exception as exc:  # a half-done action must still be logged, whatever raised
        logger.debug("settle action %s raised", decision, exc_info=True)
        return [], exc


def _changed_files(before: dict[str, str], by_handle: dict[str, records.Memory]) -> dict:
    files = {}
    for handle, sha in before.items():
        try:
            after = _sha(by_handle[handle].path)
        except OSError:
            continue
        if after != sha:
            files[handle] = {"before": sha, "after": after}
    return files


def _pair_keys(
    memories: Sequence[records.Memory], state: dict, today: datetime.date, tokenize
) -> set[frozenset]:
    return {frozenset((p["a"], p["b"])) for p in pending(memories, state, today, tokenize=tokenize)}


def _require_listing(state: dict, rows: list) -> None:
    if isinstance(state.get("offered_pairs"), list):
        return
    why = "no listing is recorded: run `mem settle pending` first"
    raise NoListingError(
        [f"refused\trow {n}\t{why}" for n in range(1, len(rows) + 1)] or [f"refused\t{why}"]
    )


class _Run:
    """One `apply_verdicts` call: what its rows share, and the rules each row must pass."""

    def __init__(
        self,
        folder: Path,
        memories: Sequence[records.Memory],
        state: dict,
        today: datetime.date,
        options: VerdictOptions,
    ):
        self.folder = folder
        self.today = today
        self.options = options
        self.judged_now = set(state["judged"])
        self.listed = _pair_keys(memories, state, today, options["tokenize"])
        self.by_handle = {m.handle: m for m in memories}
        self.touched: set[str] = set()
        self.decided: set[frozenset] = set()
        self.lines: list[str] = []
        self.seq = 0

    def _order(self, a: str, b: str) -> tuple[records.Memory, records.Memory] | None:
        return newer_first(self.by_handle[a], self.by_handle[b], self.judged_now)

    def _refuse(self, number: int, why: str) -> None:
        self.lines.append(f"refused\trow {number}\t{why}")

    def _pair_refusal(self, row: _Row) -> str | None:
        if row.decision not in DECISIONS:
            return f"decision must be one of {', '.join(DECISIONS)}"
        if frozenset((row.a, row.b)) not in self.listed or row.a == row.b:
            return f"m:{row.a} and m:{row.b} are not a pair waiting for a decision"
        if self.touched & {row.a, row.b}:
            return "one of the memories was already changed by an earlier row"
        return None

    def _reason_refusal(self, row: _Row) -> str | None:
        if row.decision != "nothing" and not row.reason:
            return "a reason is needed"
        if row.decision == "merge" and (
            flagged := records.flagged_words(
                self.by_handle[row.a].claim, self.by_handle[row.b].claim
            )
        ):
            return (
                f"the claims differ in {', '.join(flagged)}: they may be opposites or different versions; "
                "only supersede, distinct or nothing are allowed"
            )
        return None

    def _claims_refusal(self, row: _Row) -> str | None:
        if row.decision != "nothing" and not self.options["reason_ok"](row.reason):
            return "the reason was refused (secret or forbidden term)"
        if row.decision in {"merge", "supersede"} and self._order(row.a, row.b) is None:
            return (
                "cannot tell which is newer (same creation date, both or neither judged): "
                "only distinct or nothing are allowed"
            )
        return None

    def _refusal(self, row: _Row) -> str | None:
        return self._pair_refusal(row) or self._reason_refusal(row) or self._claims_refusal(row)

    def _outcome_line(self, row: _Row, done: _Done) -> str:
        if done.failure is not None:
            return (
                f"failed\trow {row.number}\t{done.failure}; the records it changed are logged as settling "
                f"{self.seq}: mem settle undo {self.seq} puts them back"
            )
        return f"applied\trow {row.number}\tsettling {self.seq}: {done.out[0] if done.out else row.decision}"

    def _record(self, row: _Row, done: _Done) -> None:
        self.seq += 1
        entry = {
            "seq": self.seq,
            "date": self.today.isoformat(),
            "decision": row.decision,
            "older": done.older.handle,
            "newer": done.newer.handle,
            "reason": row.reason,
            "files": done.files,
            "claims": _claims(done.older, done.newer),
        }
        if done.failure is not None:
            entry["partial"] = True
        _append_log(self.folder, entry)
        if done.failure is not None and _is_fatal(done.failure):
            raise done.failure  # the state is unchanged, so the listing still stands for a retry
        self.touched |= {row.a, row.b}
        self.decided.add(frozenset((row.a, row.b)))
        self.lines.append(self._outcome_line(row, done))

    def _apply(self, row: _Row) -> None:
        # distinct: the order carries no meaning
        newer, older = self._order(row.a, row.b) or (self.by_handle[row.b], self.by_handle[row.a])
        before = {m.handle: _sha(m.path) for m in (newer, older)}
        out, failure = _attempt(self.options["actions"], row.decision, newer, older, self.today)
        files = _changed_files(before, self.by_handle)
        if failure is not None and not files:
            if _is_fatal(failure):
                raise failure
            self._refuse(row.number, f"{failure}")
            return
        self._record(row, _Done(newer, older, files, out, failure))

    def _row(self, number: int, raw: object) -> None:
        row = _parse_row(number, raw)
        if row is None:
            self._refuse(number, "a row needs a, b, decision and reason as text")
        elif why := self._refusal(row):
            self._refuse(number, why)
        elif row.decision == "nothing":
            self.decided.add(frozenset((row.a, row.b)))
            self.lines.append(
                f"applied\trow {number}\tnothing: m:{row.a} and m:{row.b} left as they are"
            )
        else:
            self._apply(row)

    def run_rows(self, rows: list) -> None:
        self.seq = max(
            (e["seq"] for e in read_log(self.folder) if isinstance(e.get("seq"), int)), default=0
        )
        for number, raw in enumerate(rows, 1):
            self._row(number, raw)

    def _log_left(self, pair: frozenset, count: int) -> None:
        a, b = sorted(pair)
        newer, older = self._order(a, b) or (self.by_handle[b], self.by_handle[a])
        self.seq += 1
        _append_log(
            self.folder,
            {
                "seq": self.seq,
                "date": self.today.isoformat(),
                "decision": "left",
                "older": older.handle,
                "newer": newer.handle,
                "reason": f"no decision after {count} offers",
                "files": {},
                "claims": _claims(older, newer),
            },
        )

    def _retain_or_leave(
        self, offered: set[frozenset], state: dict
    ) -> tuple[dict[str, int], set[frozenset]]:
        offers: dict[str, int] = {}
        retained: set[frozenset] = set()
        for pair in sorted(offered, key=_key):
            if pair in self.decided:
                continue
            count = int((state.get("offers") or {}).get(_key(pair), 0))
            if count < OFFERS_BEFORE_LEFT:
                offers[_key(pair)] = count
                retained.add(pair)
            else:
                self._log_left(pair, count)
        return offers, retained

    def finish(self, state: dict, now: float) -> None:
        """Update the state after the rows: which handles are judged, which pairs stay offered."""
        covered = state.get("offered")
        if not isinstance(covered, list):
            covered = _unjudged_stems(self.folder, self.judged_now)
        # what is still a valid pair after this file's changes: a merged or superseded record drops out of it
        still = _pair_keys(
            records.load_memories(self.folder, "global"),
            state,
            self.today,
            self.options["tokenize"],
        )
        offered = (
            {frozenset(p) for p in state["offered_pairs"] if isinstance(p, list)}
            & self.listed
            & still
        )
        offers, retained = self._retain_or_leave(offered, state)
        waiting = {h for pair in retained for h in pair if h not in self.judged_now}
        state["judged"] = sorted(
            ((self.judged_now | set(covered)) - waiting) & set(_stems(self.folder))
        )
        state["offered"] = state["offered_pairs"] = None
        state["offers"] = offers
        state["last_apply"] = now
        save_state(self.folder, state)


def apply_verdicts(
    folder: Path,
    memories: Sequence[records.Memory],
    rows: object,
    today: datetime.date,
    now: float,
    **options: Unpack[VerdictOptions],
) -> list[str]:
    """Carry out the verdict rows the rules allow; one line per row (`applied`, `refused` or `failed`, and why).

    Rules, enforced here: the pair is one `pending` lists now; the older record is the one merged away or
    superseded, and a pair whose newer side cannot be told allows only distinct or nothing; a pair with flagged
    words is never merged; a record changed by an earlier row of the file is not touched again. A refused row
    leaves the others untouched. A pair offered `OFFERS_BEFORE_LEFT` times without an applied decision is logged as
    `left`; before that it stays pending. A handle is judged only when no pair it belongs to is still retained.
    Without a recorded `pending` listing every row is refused (`NoListing`) and nothing changes. Only `OSError` and
    `ValueError` from an action are a row failure; any other exception is logged if a record changed, then raised."""
    state = load_state(folder)
    if not isinstance(rows, list):
        return ["refused\tthe file must hold a list of verdicts"]
    run = _Run(folder, memories, state, today, options)
    _require_listing(state, rows)
    run.run_rows(rows)
    run.finish(state, now)
    return run.lines


def listing(folder: Path, everything: bool) -> list[str]:
    state = load_state(folder)
    acked = state.get("acked", 0)
    out = []
    for s in settlings(folder):
        if not everything and (s["seq"] <= acked or s["undone"]):
            continue
        claims = s.get("claims", {})
        mark = f"  (undone {s['undone']})" if s["undone"] else ""
        out.append(
            f"{s['seq']}\t{s['date']}\t{s['decision']}\t{claims.get('older', '')} | {claims.get('newer', '')}{mark}"
        )
    return out


def ack(folder: Path) -> int:
    """Mark every settling acknowledged; returns how many were not yet."""
    state = load_state(folder)
    top = max((s["seq"] for s in settlings(folder)), default=0)
    fresh = len([
        s for s in settlings(folder) if state.get("acked", 0) < s["seq"] and not s["undone"]
    ])
    state["acked"] = top
    save_state(folder, state)
    return fresh


def _undoable(folder: Path, number: int) -> dict:
    found = next((s for s in settlings(folder) if s["seq"] == number), None)
    if found is None:
        raise ValueError(f"no settling {number}")
    if found["undone"]:
        raise ValueError(f"settling {number} was already undone on {found['undone']}")
    if not found.get("files"):
        raise NothingToUndoError(f"settling {number} changed no record: nothing to undo")
    return found


def _checked_entry(
    folder: Path, handle: str, shas: dict, found: dict
) -> tuple[records.Memory, dict]:
    """The record and its log entry, once both are as the settling left them (else ValueError)."""
    number = found["seq"]
    path = folder / f"{handle}.md"
    memory = records._parse(path, "global") if path.is_file() else None
    if memory is None or _sha(path) != shas["after"]:
        raise ValueError(
            f"m:{handle} was changed again since settling {number}: nothing was undone; "
            f"look at it with mem show m:{handle} and decide by hand"
        )
    entry = records.last_log_entry(memory)
    if (
        entry is None
        or entry.get("action") != found["decision"]
        or hashlib.sha256(entry["before"].encode("utf-8")).hexdigest() != shas["before"]
    ):
        raise ValueError(
            f"the logged text of m:{handle} is not the one settling {number} wrote: nothing was undone"
        )
    return memory, entry


def undo(folder: Path, number: int, today: datetime.date) -> list[str]:
    """Put back, in one step, every record settling `number` changed. Raises ValueError, changing nothing, when the
    settling is unknown or undone, or a record is not as the settling left it or its logged text is not the one
    the settling wrote."""
    found = _undoable(folder, number)
    todo = [_checked_entry(folder, handle, shas, found) for handle, shas in found["files"].items()]
    lines = []
    for memory, entry in todo:
        records.restore(memory, entry)
        lines.append(
            f"m:{memory.handle}\trestored to before {found['decision']} of settling {number}"
        )
    _append_log(folder, {"undo": number, "date": today.isoformat()})
    return lines
