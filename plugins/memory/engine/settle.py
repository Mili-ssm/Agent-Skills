"""Settling new global memories against their look-alikes (`mem settle`): which pairs a model session is asked to
judge, how its verdicts are enforced, and the state and log that make the result visible and reversible.

A model never acts: it writes verdicts, and `apply_verdicts` runs only what the rules below allow, through the same
code as `mem merge`, `mem supersede` and `mem distinct` (the callables in `Actions`), so every change has its
`.curation-log` entries and `mem restore`. The older record is always the one dropped or superseded.

State and log sit beside the global memories: `.settle-state.json` (the handles already judged, the end of the last
apply, the last log number acknowledged) and `.settle-log` (JSON lines). `mem-auto` keeps its own window elsewhere;
nothing here reads or writes it. Standard library plus `records`."""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Callable, NamedTuple, Sequence

import auto_state
import records

STATE_NAME = ".settle-state.json"
LOG_NAME = ".settle-log"
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


def load_state(folder: Path) -> dict:
    """The settle state. The first use (no state file) records every memory that exists as judged: only records
    written after that are new. This writes the file, so an unwritable folder raises OSError."""
    state = auto_state.read_json(folder / STATE_NAME)
    if not isinstance(state.get("judged"), list):
        state = {"judged": _stems(folder), "last_apply": None, "acked": 0, "offered": None}
        save_state(folder, state)
    return state


def save_state(folder: Path, state: dict) -> None:
    auto_state.write_json(folder / STATE_NAME, state)


def _counts_as_new(m: records.Memory, judged: set[str], today: datetime.date) -> bool:
    return m.handle not in judged and records.is_live(m, today) and m.origin != "pipeline"


def unjudged_count(folder: Path, state: dict, today: datetime.date) -> int:
    """Live, non-pipeline memories not yet judged. Parses only the files whose handle is not in the judged list."""
    judged = set(state["judged"])
    count = 0
    for stem in _stems(folder):
        if stem not in judged and _counts_as_new(records._parse(folder / f"{stem}.md", "global"), judged, today):
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


def newer_first(a: records.Memory, b: records.Memory) -> tuple[records.Memory, records.Memory]:
    """(newer, older) by creation date; on a tie the one that `mem memories` lists first (lower handle) is the newer."""
    first, second = sorted((a, b), key=lambda m: (-(m.created or datetime.date.min).toordinal(), m.handle))
    return first, second


def pending(memories: Sequence[records.Memory], state: dict, today: datetime.date, *, tokenize) -> list[dict]:
    """The look-alike pairs to judge: queue pairs of live global memories where one side is new."""
    judged = set(state["judged"])
    out = []
    for a, b, _ in records.pairs(memories, today, tokenize=tokenize):
        if not (_counts_as_new(a, judged, today) or _counts_as_new(b, judged, today)):
            continue
        newer, _older = newer_first(a, b)
        out.append({"pair": len(out) + 1, "a": a.handle, "b": b.handle, "claim_a": " ".join(a.claim.split()),
                    "claim_b": " ".join(b.claim.split()), "newer": newer.handle,
                    "flagged_words": records.flagged_words(a.claim, b.claim)})
    return out


def offer(folder: Path, state: dict) -> None:
    """Remember which handles this look at the queue covered: what is written afterwards stays new for the next run."""
    state["offered"] = [s for s in _stems(folder) if s not in set(state["judged"])]
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
    with (folder / LOG_NAME).open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def settlings(folder: Path) -> list[dict]:
    """The logged settlings, each with `undone` (the date, or None)."""
    undone = {e["undo"]: e.get("date") for e in read_log(folder) if isinstance(e.get("undo"), int)}
    return [{**e, "undone": undone.get(e["seq"])} for e in read_log(folder) if isinstance(e.get("seq"), int)]


def _short(text: str) -> str:
    return text if len(text) <= CLAIM_WIDTH else text[:CLAIM_WIDTH - 1].rstrip() + "…"


def apply_verdicts(folder: Path, memories: Sequence[records.Memory], rows: object, today: datetime.date, now: float, *,
                   actions: Actions, reason_ok: Callable[[str], bool], tokenize) -> list[str]:
    """Carry out the verdict rows the rules allow; one line per row (`applied` or `refused` and why).

    Rules, enforced here: the pair is one `pending` lists now; the older record is the one merged away or
    superseded; a pair with flagged words is never merged; a record changed by an earlier row of the file is not
    touched again. A refused row leaves the others untouched."""
    state = load_state(folder)
    listed = {frozenset((p["a"], p["b"])) for p in pending(memories, state, today, tokenize=tokenize)}
    by_handle = {m.handle: m for m in memories}
    touched: set[str] = set()
    lines: list[str] = []
    if not isinstance(rows, list):
        return ["refused\tthe file must hold a list of verdicts"]
    seq = max((e["seq"] for e in read_log(folder) if isinstance(e.get("seq"), int)), default=0)
    for number, row in enumerate(rows, 1):
        def refuse(why: str, number=number) -> None:
            lines.append(f"refused\trow {number}\t{why}")
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("a", "b", "decision", "reason")):
            refuse("a row needs a, b, decision and reason as text")
            continue
        a, b = (row[k].strip().removeprefix("m:") for k in ("a", "b"))
        decision, reason = row["decision"], " ".join(row["reason"].split())
        if decision not in DECISIONS:
            refuse(f"decision must be one of {', '.join(DECISIONS)}")
        elif frozenset((a, b)) not in listed or a == b:
            refuse(f"m:{a} and m:{b} are not a pair waiting for a decision")
        elif touched & {a, b}:
            refuse("one of the memories was already changed by an earlier row")
        elif decision != "nothing" and not reason:
            refuse("a reason is needed")
        elif decision == "merge" and (flagged := records.flagged_words(by_handle[a].claim, by_handle[b].claim)):
            refuse(f"the claims differ in {', '.join(flagged)}: they may be opposites or different versions; "
                   "only supersede, distinct or nothing are allowed")
        elif decision != "nothing" and not reason_ok(reason):
            refuse("the reason was refused (secret or forbidden term)")
        elif decision == "nothing":
            lines.append(f"applied\trow {number}\tnothing: m:{a} and m:{b} left as they are")
        else:
            newer, older = newer_first(by_handle[a], by_handle[b])
            before = {m.handle: _sha(m.path) for m in (newer, older)}
            try:
                if decision == "merge":
                    out = actions.merge(newer, older, today)
                elif decision == "supersede":
                    out = actions.supersede(older, newer, today)
                else:
                    out = actions.distinct(older, newer, today)
            except (OSError, ValueError) as exc:
                refuse(f"{exc}")
                continue
            files = {h: {"before": before[h], "after": _sha(by_handle[h].path)} for h in before}
            files = {h: v for h, v in files.items() if v["before"] != v["after"]}
            seq += 1
            _append_log(folder, {"seq": seq, "date": today.isoformat(), "decision": decision, "older": older.handle,
                                 "newer": newer.handle, "reason": reason, "files": files,
                                 "claims": {"older": _short(" ".join(older.claim.split())),
                                            "newer": _short(" ".join(newer.claim.split()))}})
            touched |= {a, b}
            lines.append(f"applied\trow {number}\tsettling {seq}: {out[0] if out else decision}")
    stems = set(_stems(folder))
    covered = state.get("offered")
    if not isinstance(covered, list):
        covered = [s for s in stems if s not in set(state["judged"])]
    state["judged"] = sorted((set(state["judged"]) | set(covered)) & stems)
    state["offered"] = None
    state["last_apply"] = now
    save_state(folder, state)
    return lines


def listing(folder: Path, everything: bool) -> list[str]:
    state = load_state(folder)
    acked = state.get("acked", 0)
    out = []
    for s in settlings(folder):
        if not everything and (s["seq"] <= acked or s["undone"]):
            continue
        claims = s.get("claims", {})
        mark = f"  (undone {s['undone']})" if s["undone"] else ""
        out.append(f"{s['seq']}\t{s['date']}\t{s['decision']}\t{claims.get('older', '')} | {claims.get('newer', '')}{mark}")
    return out


def ack(folder: Path) -> int:
    """Mark every settling acknowledged; returns how many were not yet."""
    state = load_state(folder)
    top = max((s["seq"] for s in settlings(folder)), default=0)
    fresh = len([s for s in settlings(folder) if state.get("acked", 0) < s["seq"] and not s["undone"]])
    state["acked"] = top
    save_state(folder, state)
    return fresh


def undo(folder: Path, number: int, today: datetime.date) -> list[str]:
    """Put back, in one step, every record settling `number` changed. Raises ValueError, changing nothing, when the
    settling is unknown or undone, or a record is not as the settling left it or its logged text is not the one
    the settling wrote."""
    found = next((s for s in settlings(folder) if s["seq"] == number), None)
    if found is None:
        raise ValueError(f"no settling {number}")
    if found["undone"]:
        raise ValueError(f"settling {number} was already undone on {found['undone']}")
    todo = []
    for handle, shas in found.get("files", {}).items():
        path = folder / f"{handle}.md"
        memory = records._parse(path, "global") if path.is_file() else None
        if memory is None or _sha(path) != shas["after"]:
            raise ValueError(f"m:{handle} was changed again since settling {number}: nothing was undone; "
                             f"look at it with mem show m:{handle} and decide by hand")
        entry = records.last_log_entry(memory)
        if (entry is None or entry.get("action") != found["decision"]
                or hashlib.sha256(entry["before"].encode("utf-8")).hexdigest() != shas["before"]):
            raise ValueError(f"the logged text of m:{handle} is not the one settling {number} wrote: nothing was undone")
        todo.append((memory, entry))
    lines = []
    for memory, entry in todo:
        records.restore(memory, entry)
        lines.append(f"m:{memory.handle}\trestored to before {found['decision']} of settling {number}")
    _append_log(folder, {"undo": number, "date": today.isoformat()})
    return lines
