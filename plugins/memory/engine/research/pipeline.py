"""`mem-research`: answer a question from memory, then (by depth) check notes and the question against the web.

Plan 2026-11-17-memory-seamless, stage 1b. Five steps, three of them model sessions and none with a shell:
1 memory (Python runs `mem search`; a Haiku session reads the results and writes `need.json`; at most one more round),
2 web input (`research.checks.web_input`: only what passes the secret and forbidden-terms checks), 3 web (a Haiku
session with WebSearch and WebFetch only, in an empty folder, with no `mem` and no `MEM_*` around it), 4 check (Python
fetches each page and picks the passages), 5 verdict (a Haiku session reads the passages as data and writes
`verdicts.json`), 6 apply (Python enforces quotes, URLs and stances, then runs three fixed `mem` commands).
Every step's input and output stay in the run folder. Standard library only; the run never reads or writes the
`mem-auto` or settle state.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Required, TypedDict, Unpack

from core import codex_pass, config, headless, jobs
from memories.records import tokenize
from notes.note import FrontmatterError, split_frontmatter
from synthesize import pipeline as sp

from research import checks as rc

logger = logging.getLogger(__name__)

DEPTHS = ("memory", "contrast", "deep")
DEFAULT_DEPTH = "contrast"
LIMITS = {
    "memory": (0.25, 180),
    "contrast": (0.50, 300),
    "deep": (2.00, 540),
}  # (USD, seconds) for the whole run; under the 10 minutes a shell call of an agent may last
PAGES = {"contrast": 5, "deep": 15}
SHARE = {
    "memory": 0.15,
    "web": 0.55,
}  # of the budget, at most, per such session; the verdict gets what is left
MAX_NOTES = 8  # notes contrasted in one run: the web prompt and the passages stay bounded
SEARCHES = 3  # extra searches the memory session may ask for
SEARCH_LIMIT = 5  # results per `mem search`
SHOWN = 6  # `mem show` calls per run
SHOW_CHARS, RESULT_CHARS = 1500, 8000
MEMORY_ROUNDS = 2  # the memory session runs once, and once more when it asks for searches
EPSILON = 1e-9  # a budget below this counts as spent
KEEP_SECONDS = 30 * 86400
RESULT_LINE = re.compile(r"^knowledge/[^\t]*?([^/\t]+)\.md\t", re.MULTILINE)
URL = re.compile(r"https?://[^\s\"'<>)\]]+")


class StopError(Exception):
    """The run ends here and reports what it has."""


class ResearchOptions(TypedDict, total=False):
    """The settings of one `research` run; `contrast` and `allow_hosts` default to none."""

    depth: Required[str]
    contrast: list[str]
    claude: Required[str | None]
    budget: Required[float]
    seconds: Required[float]
    allow_hosts: list[str]


class StepOptions(TypedDict, total=False):
    """What the steps after the memory step need; `contrast` and `allow_hosts` default to none."""

    question: Required[str]
    claude: Required[str]
    depth: Required[str]
    contrast: list[str]
    allow_hosts: list[str]
    settings: Required[Path]


# ---- places and environments ----


state_dir = jobs.state_dir


def default_store() -> Path | None:
    return config.resolve_store(None, os.environ)


def runs_dir(store: Path) -> Path:
    return (
        state_dir()
        / "research"
        / hashlib.sha1(str(store.resolve()).encode()).hexdigest()[:12]
        / "runs"
    )


def mem_env(store: Path) -> dict[str, str]:
    """The `mem` calls: aimed at `store`; a configured memories folder is kept; no other project's memories."""
    # The left side is an environment variable name: a str, so a set literal is safe.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"MEM_STORE", "MEM_PROJECT"} and not k.startswith("CLAUDE_PLUGIN_OPTION_")
    }
    env["PATH"] = os.pathsep.join(
        p for p in env.get("PATH", "").split(os.pathsep) if "/plugins/cache/" not in p
    )
    env["MEM_STORE"] = str(store)
    return env


# ---- sessions ----


def file_cmd(claude: str, prompt: str, work: Path, settings: Path, max_budget: float) -> list[str]:
    """A session of the memory or verdict step. Only Read, Write and Edit exist (`--tools`, no MCP server), and the
    rules allow them inside `work` only (`//` is an absolute path in a permission rule); no shell, no web."""
    return headless.command(
        headless.Session(
            claude=claude,
            prompt=prompt,
            model="haiku",
            effort="medium",
            settings=settings,
            tools=("Read", "Write", "Edit"),
            allowed=(f"Read(/{work}/**)", f"Write(/{work}/**)", f"Edit(/{work}/**)"),
            max_budget=max_budget,
        )
    )


def web_cmd(claude: str, prompt: str, settings: Path, max_budget: float) -> list[str]:
    """The web session: only WebSearch and WebFetch, no MCP server, no plugin, hooks off, project settings only.
    `--tools` says which tools exist; a headless session still needs the permission to call them."""
    return headless.command(
        headless.Session(
            claude=claude,
            prompt=prompt,
            model="haiku",
            effort="medium",
            settings=settings,
            tools=("WebSearch", "WebFetch"),
            allowed=("WebSearch", "WebFetch"),
            max_budget=max_budget,
        )
    )


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _stream_events(raw: str) -> list[dict[str, Any]]:
    """The lines of a session stream that are JSON objects."""
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _content_parts(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = _dict_or_empty(event.get("message")).get("content")
    return [part for part in content if isinstance(part, dict)] if isinstance(content, list) else []


def _tool_use_inputs(part: dict[str, Any]) -> tuple[str | None, str | None]:
    """(query, url) a tool call was given, each None when absent or not a string."""
    given = _dict_or_empty(part.get("input"))
    query = given.get("query") if part.get("name") == "WebSearch" else None
    url = given.get("url")
    return (
        query if isinstance(query, str) else None,
        url if isinstance(url, str) else None,
    )


def _result_text(body: Any) -> str:
    if isinstance(body, str):
        return body
    return " ".join(b.get("text", "") for b in body or [] if isinstance(b, dict))


def _collect_part(part: dict[str, Any], queries: list[str], urls: list[str]) -> None:
    """Add the query and URLs of one content part of the stream to `queries` and `urls`."""
    if part.get("type") == "tool_use":
        query, url = _tool_use_inputs(part)
        if query is not None:
            queries.append(query)
        if url is not None:
            urls.append(url)
    elif part.get("type") == "tool_result":
        urls += URL.findall(_result_text(part.get("content")))


def web_events(raw: str) -> dict[str, list[str]]:
    """What the web session searched and fetched, from its stream: queries, and every URL its tools were given or
    returned."""
    queries: list[str] = []
    urls: list[str] = []
    for event in _stream_events(raw):
        for part in _content_parts(event):
            _collect_part(part, queries, urls)
    return {"queries": list(dict.fromkeys(queries)), "urls": list(dict.fromkeys(urls))}


def render(name: str, **values: str) -> str:
    """A brief with its `{PLACEHOLDER}`s filled in one pass, so a value that holds braces is never read as one."""
    text = (sp.BRIEFS / f"{name}-brief.md").read_text()
    return re.sub(r"\{([A-Z_]+)\}", lambda m: values.get(m.group(1), m.group(0)), text)


class Run:
    """One run's folder, spend and clock."""

    def __init__(self, folder: Path, budget: float, seconds: float):
        self.folder, self.budget = folder, budget
        self.deadline = time.monotonic() + seconds
        self.cost = 0.0
        self.sessions: list[dict[str, Any]] = []
        self.status: dict[str, Any] = {}

    def left(self) -> float:
        return self.budget - self.cost

    def seconds_left(self) -> float:
        return self.deadline - time.monotonic()

    def log(self, text: str) -> None:
        fd = os.open(self.folder / "log.txt", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    def save(self, **changes: Any) -> None:
        self.status.update(changes)
        jobs.write_json(self.folder / jobs.STATUS_NAME, self.status)

    def step_dir(self, name: str) -> Path:
        folder = self.folder / name
        jobs.private_dir(folder / "work")
        return folder

    def session(
        self, name: str, cmd: list[str], cwd: Path, env: dict[str, str], prompt: str
    ) -> dict:
        """Run one session, keep its prompt and stream next to its work folder, count its spend."""
        folder = cwd.parent
        (folder / "brief.txt").write_text(prompt, encoding="utf-8")
        start = time.monotonic()
        try:
            out = headless.run_raw(cmd, cwd=cwd, env=env, timeout=max(1.0, self.seconds_left()))
            raw = out.stdout
            failed = "time limit reached" if out.timed_out else ""
        except OSError as exc:
            raw, failed = "", f"cannot start claude: {exc}"
        (folder / "session.jsonl").write_text(raw)
        result = sp.parse(raw)
        result["raw"] = raw
        self.cost += result["cost"]
        self.sessions.append({
            "step": name,
            "cost": result["cost"],
            "wall": round(time.monotonic() - start, 1),
        })
        self.save(cost=self.cost, sessions=self.sessions)
        self.log(
            f"{name}: has_result={result['has_result']} error={result['error']} cost={result['cost']:.3f} {failed}"
        )
        if failed:
            raise StopError(failed)
        if not result["has_result"]:
            raise StopError(sp.NO_COST)
        if result["error"]:
            raise StopError(
                f"the {name} session failed: {' '.join(result['answer'].split())[:150]}"
            )
        return result

    def gate(self, share: float | None) -> float:
        """The `--max-budget-usd` of the next session; StopError when nothing is left."""
        if self.left() <= EPSILON:
            raise StopError(f"budget spent ({self.cost:.2f} of {self.budget:.2f} USD)")
        if self.seconds_left() <= 0:
            raise StopError("time limit reached")
        return min(self.left(), share * self.budget) if share else self.left()


# ---- step 1: memory ----


def mem_text(store: Path, *args: str) -> str:
    done = sp.mem(store, mem_env(store), *args)
    return (
        done.stdout
        if done.returncode == 0
        else f"(mem {args[0]} failed: {(done.stderr or done.stdout).strip()[:200]})"
    ).strip()


def search_block(store: Path, query: str, shown: set[str]) -> str:
    """`mem search` for one query (one argument, no shell) and `mem show` for its first knowledge results."""
    found = mem_text(store, "search", "--limit", str(SEARCH_LIMIT), "--", query)
    block = [f"## search: {query}", found[:RESULT_CHARS] or "(no results)"]
    for handle in RESULT_LINE.findall(found):
        if len(shown) >= SHOWN:
            break
        if handle in shown:
            continue
        shown.add(handle)
        text = mem_text(store, "show", handle, "--section", "conclusion")
        block += [f"## show: {handle}", text[:SHOW_CHARS] or "(nothing)"]
    return "\n".join(block) + "\n"


def knowledge_notes(store: Path) -> dict[str, Path]:
    return {
        p.stem: p for p in sorted((store / "knowledge").glob("*/*.md")) if p.name != "README.md"
    }


def _search_texts(value: object) -> list[str]:
    """The distinct, searchable queries of `more_searches`: whitespace collapsed, at most 200 characters each."""
    searches: list[str] = []
    for item in value if isinstance(value, list) else []:
        text = " ".join(item.split())[:200] if isinstance(item, str) else ""
        if text and tokenize(text) and text not in searches:
            searches.append(text)
    return searches


def read_need(path: Path) -> dict | str:
    """`need.json` as a dict with `answer`, `covers`, `more_searches`, `contrast`; else why not."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "the memory session wrote no valid need.json"
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("answer"), str)
        or not isinstance(data.get("covers"), bool)
    ):
        return "need.json lacks an answer or a covers flag"
    searches = _search_texts(data.get("more_searches"))
    contrast = (
        [h for h in data.get("contrast", []) if isinstance(h, str)]
        if isinstance(data.get("contrast"), list)
        else []
    )
    return {
        "answer": data["answer"],
        "covers": data["covers"],
        "more_searches": searches[:SEARCHES],
        "contrast": contrast,
    }


def memory_step(run: Run, store: Path, claude: str, question: str, settings: Path) -> dict:
    env = headless.session_env()
    shown: set[str] = set()
    text = search_block(store, question, shown)
    need: dict | str = {}
    for number in range(1, MEMORY_ROUNDS + 1):
        folder = run.step_dir(f"memory-{number}")
        work = folder / "work"
        (work / "results.txt").write_text(text, encoding="utf-8")
        rule = (
            "up to three short searches (plain words, no quotes or operators) for what the results lack, each run "
            "once on its own, after which you read the added results; an empty list when the results are enough"
            if number == 1
            else "an empty list: no further search is made"
        )
        prompt = render(
            "memory",
            QUESTION=question,
            RESULTS_FILE=str(work / "results.txt"),
            NEED_FILE=str(work / "need.json"),
            SEARCH_RULE=rule,
        )
        run.session(
            f"memory-{number}",
            file_cmd(claude, prompt, work, settings, run.gate(SHARE["memory"])),
            work,
            env,
            prompt,
        )
        need = read_need(work / "need.json")
        if isinstance(need, str):
            raise StopError(need)
        if number == MEMORY_ROUNDS or not need["more_searches"]:
            break
        for query in need["more_searches"]:
            text += "\n" + search_block(store, query, shown)
    run.log(f"memory: covers={need['covers']} contrast={need['contrast']}")
    return need


# ---- steps 2 to 6 ----


def web_prompt(items: list[dict[str, str]], depth: str) -> str:
    lines = [f"- {key}: {item['text']}" for key, item in rc.item_ids(items).items()]
    papers = (
        " Ask for scientific papers too: prefer them to blogs, and give them `source_kind` `paper`."
        if depth == "deep"
        else ""
    )
    return render("web", PAGES=str(PAGES[depth]), PAPERS=papers, ITEMS="\n".join(lines))


def web_step(
    run: Run, claude: str, items: list[dict[str, str]], depth: str, settings: Path
) -> list | None:
    folder = run.step_dir("web")
    work = folder / "work"  # empty: the session has nothing to read
    prompt = web_prompt(items, depth)
    done = run.session(
        "web",
        web_cmd(claude, prompt, settings, run.gate(SHARE["web"])),
        work,
        headless.session_env(),
        prompt,
    )
    events = web_events(done["raw"])
    (folder / "events.json").write_text(json.dumps(events, indent=1), encoding="utf-8")
    (folder / "reply.txt").write_text(done["answer"], encoding="utf-8")
    run.log(f"web: {len(events['queries'])} searches, {len(events['urls'])} urls")
    return rc.parse_web_reply(done["answer"])


def verdict_input(
    question: str, items: list[dict[str, str]], entries: list[dict]
) -> dict[str, Any]:
    """What the verdict session reads: the question, the claims sent to the web and the evidence found."""
    return {
        "question": question,
        "notes": [{"note": i["handle"], "claim": i["text"]} for i in items if i["kind"] == "claim"],
        "evidence": entries,
    }


def verdict_step(run: Run, claude: str, data: dict[str, Any], settings: Path) -> dict:
    folder = run.step_dir("verdict")
    work = folder / "work"
    (work / "input.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    prompt = render(
        "verdict", INPUT_FILE=str(work / "input.json"), VERDICTS_FILE=str(work / "verdicts.json")
    )
    run.session(
        "verdict",
        file_cmd(claude, prompt, work, settings, run.gate(None)),
        work,
        headless.session_env(),
        prompt,
    )
    try:
        verdicts = json.loads((work / "verdicts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StopError("the verdict session wrote no valid verdicts.json") from None
    if not isinstance(verdicts, dict):
        raise StopError("verdicts.json is not a JSON object")
    return verdicts


def _frontmatter_field(path: Path, key: str) -> object:
    """A field of a note's frontmatter; None when the note is unreadable or its frontmatter is not a mapping."""
    try:
        return split_frontmatter(path.read_text(encoding="utf-8"))[0].get(key)
    except (OSError, FrontmatterError, AttributeError):
        return None


def contrast_notes(
    store: Path, handles: list[str]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """({handle, claim} of the knowledge notes among `handles`, the handles dropped with their reason). A handle that
    is not a knowledge note of the store cannot be confirmed or disputed, so it is dropped."""
    known = knowledge_notes(store)
    notes: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for raw in handles:
        handle = Path(raw.strip()).name.removesuffix(".md")
        if handle in {n["handle"] for n in notes}:
            continue
        if handle not in known:
            dropped.append({"handle": raw, "reason": "not a knowledge note of the store"})
            continue
        claim = _frontmatter_field(known[handle], "claim")
        if not isinstance(claim, str) or not claim.strip():
            dropped.append({"handle": handle, "reason": "no claim"})
        elif len(notes) >= MAX_NOTES:
            dropped.append({"handle": handle, "reason": f"over the {MAX_NOTES}-note limit"})
        else:
            notes.append({"handle": handle, "claim": claim})
    return notes, dropped


def marks(applied: list[list[str]]) -> dict[str, tuple[str, str]]:
    """Note handle -> (verdict, url) of the commands that were applied."""
    out: dict[str, tuple[str, str]] = {}
    for args in applied:
        if args[:2] in (["note", "confirm"], ["note", "dispute"]):
            out[args[2]] = (
                "confirmed" if args[1] == "confirm" else "contradicted",
                args[args.index("--source") + 1],
            )
    return out


def _memory_lines(need: Any) -> list[str]:
    if not need:
        return ["From memory", "  (the memory step did not finish)"]
    covers = "yes" if need["covers"] else "no"
    return [
        f"From memory (covers the question: {covers})",
        f"  {need['answer'].strip() or '(nothing)'}",
    ]


def _unmarked_result(state: dict[str, Any], handle: str) -> str:
    """The result column of a contrasted note that no applied command marked."""
    why = next(
        (
            r["reason"]
            for r in state.get("refused", [])
            if isinstance(r["row"], dict) and r["row"].get("note") == handle
        ),
        "",
    )
    if any(f["args"][2:3] == [handle] for f in state.get("failed", [])):
        return "failed to write"
    if state.get("judged"):
        return "no source" + (f" ({why})" if why else "")
    return "not judged" if state.get("web_ran") else "not checked"


def _contrast_lines(state: dict[str, Any]) -> list[str]:
    lines = ["", "Contrasted notes", "  | note | result | source |", "  |---|---|---|"]
    got = marks(state.get("applied", []))
    for handle in state["sent"]:
        if handle in got:
            lines.append(f"  | {handle} | {got[handle][0]} | {got[handle][1]} |")
        else:
            lines.append(f"  | {handle} | {_unmarked_result(state, handle)} | |")
    return lines


def _web_lines(state: dict[str, Any]) -> list[str]:
    lines = ["", "From the web (new and unconfirmed)"]
    findings = [a for a in state.get("applied", []) if a[0] == "remember"]
    lines += [
        f"  - {a[a.index('--claim') + 1]} ({a[a.index('--source') + 1]})" for a in findings
    ] or ["  nothing added"]
    if state.get("web_answer"):
        lines.append(f"  Summary: {' '.join(state['web_answer'].split())[:1200]}")
    if state.get("sent"):
        lines += _contrast_lines(state)
    return lines


def report_text(question: str, run: Run, state: dict[str, Any]) -> str:
    """The short answer."""
    out = [f"Question: {question}", ""]
    out += _memory_lines(state.get("need"))
    if state.get("depth") != "memory":
        out += _web_lines(state)
    dropped = state.get("dropped", [])
    if dropped:
        out += ["", "Dropped"] + [f"  - {d}" for d in dropped]
    if state.get("stopped"):
        out += ["", f"Stopped: {state['stopped']}"]
    out += [
        "",
        f"Cost: {run.cost:.3f} USD of {run.budget:.2f} ({len(run.sessions)} sessions). Run folder: {run.folder}",
    ]
    return "\n".join(out)


def _prune_old_runs(base: Path) -> None:
    """Delete the run folders older than `KEEP_SECONDS`."""
    for old in base.iterdir():
        try:
            if time.time() - old.stat().st_mtime > KEEP_SECONDS:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            continue


def _run_steps(run: Run, store: Path, state: dict[str, Any], **step: Unpack[StepOptions]) -> None:
    """The memory step, then (by depth) the web and verdict steps; a `StopError` ends the run and is reported."""
    try:
        state["need"] = memory_step(run, store, step["claude"], step["question"], step["settings"])
        if step["depth"] != "memory":
            web_and_verdicts(run, store, state, **step)
    except StopError as stop:
        state["stopped"] = str(stop)
        run.log(f"stopped: {stop}")
    run.save(
        state="stopped" if state.get("stopped") else "ok",
        finished=time.time(),
        reason=state.get("stopped", ""),
    )


def _run_guarded(run: Run, store: Path, state: dict[str, Any], **step: Unpack[StepOptions]) -> int:
    """Exit code of the run: 0, or 1 when something other than a `StopError` went wrong."""
    try:
        _run_steps(run, store, state, **step)
    except Exception as exc:  # the run folder still tells what happened
        logger.debug("the research run failed", exc_info=True)
        state["stopped"] = f"{type(exc).__name__}: {exc}"[:200]
        run.save(state="failed", finished=time.time(), reason=state["stopped"])
        return 1
    return 0


def research(store: Path, question: str, **options: Unpack[ResearchOptions]) -> int:
    question = " ".join(question.split())
    depth, claude = options["depth"], options["claude"]
    if depth != "memory":
        problem = rc.question_problem(question)
        if problem:
            print(f"mem-research: {problem}; nothing was sent anywhere.", file=sys.stderr)
            return 2
    if not claude:
        print(
            "mem-research: no claude binary (--claude, CLAUDE_CODE_EXECPATH or PATH)",
            file=sys.stderr,
        )
        return 2
    base = runs_dir(store)
    jobs.private_dir(base)
    _prune_old_runs(base)
    folder = base / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    jobs.private_dir(folder)
    budget = options["budget"]
    run = Run(folder, budget, options["seconds"])
    run.save(
        state="running",
        started=time.time(),
        depth=depth,
        question=question,
        budget=budget,
        cost=0.0,
    )
    settings = folder / "settings.json"
    settings.write_text(
        json.dumps({"disableAllHooks": True})
    )  # no hook of a session may commit or start a run
    state: dict[str, Any] = {
        "depth": depth,
        "dropped": [],
        "applied": [],
        "refused": [],
        "failed": [],
    }
    code = _run_guarded(
        run,
        store,
        state,
        question=question,
        claude=claude,
        depth=depth,
        contrast=options.get("contrast", []),
        allow_hosts=options.get("allow_hosts", []),
        settings=settings,
    )
    text = report_text(question, run, state)
    (folder / "report.txt").write_text(text, encoding="utf-8")
    print(text)
    return code


def without_experience(store: Path, handles: list[str]) -> tuple[list[str], list[str]]:
    """(handles kept, handles dropped): a note of origin `experience` records the owner's own experiments, which the
    web cannot confirm and which are the most private notes, so the memory step's choice never sends one. A handle
    that is not a readable knowledge note stays, for `contrast_notes` to drop with its own reason."""
    known = knowledge_notes(store)
    kept: list[str] = []
    dropped: list[str] = []
    for raw in handles:
        path = known.get(Path(raw.strip()).name.removesuffix(".md"))
        origin = _frontmatter_field(path, "origin") if path else None
        (dropped if origin == "experience" else kept).append(raw)
    return kept, dropped


def web_and_verdicts(
    run: Run, store: Path, state: dict[str, Any], **step: Unpack[StepOptions]
) -> None:
    question, depth, settings = step["question"], step["depth"], step["settings"]
    chosen = step.get("contrast", [])
    if (
        not chosen
    ):  # named with --contrast, an experience note goes; chosen by the memory step, it does not
        chosen, own = without_experience(store, state["need"]["contrast"])
        state["dropped"] += [f"{h}: own experience: not sent to the web" for h in own]
    notes, dropped = contrast_notes(store, chosen)
    state["dropped"] += [f"{d['handle']}: {d['reason']}" for d in dropped]
    web = rc.web_input(question, notes)
    state["dropped"] += [f"{d['handle']}: {d['reason']}" for d in web.dropped]
    state["sent"] = [i["handle"] for i in web.items if i["kind"] == "claim"]
    (run.folder / "web-input.json").write_text(
        json.dumps({"items": web.items, "dropped": web.dropped}, indent=1)
    )
    rows = web_step(run, step["claude"], web.items, depth, settings)
    state["web_ran"] = True
    if rows is None:
        state["dropped"].append(
            "the web session's reply was not the expected JSON list: no web results"
        )
        return
    checked = rc.check_rows(
        rows,
        rc.item_ids(web.items),
        functools.partial(rc.fetch_text, allow_hosts=step.get("allow_hosts", [])),
        max_urls=PAGES[depth],
    )
    state["dropped"] += [
        f"web row {json.dumps(d['row'], ensure_ascii=False)[:120]}: {d['reason']}"
        for d in checked.dropped
    ]
    (run.folder / "check.json").write_text(
        json.dumps(
            {
                "entries": checked.entries,
                "dropped": checked.dropped,
                "fetched": {u: len(t) for u, t in checked.pages.items()},
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    if not checked.entries:
        state["dropped"].append("no web page could be used")
        return
    verdicts = verdict_step(
        run,
        step["claude"],
        verdict_input(question, web.items, checked.entries),
        settings,
    )
    state["web_answer"] = verdicts["answer"] if isinstance(verdicts.get("answer"), str) else ""
    state["judged"] = True
    applied = rc.apply(
        verdicts,
        checked.entries,
        checked.pages,
        state["sent"],
        mem_cmd=[str(sp.MEM)],
        root=store,
        env=mem_env(store),
    )
    (run.folder / "apply.json").write_text(json.dumps(applied, ensure_ascii=False, indent=1))
    state.update(applied=applied["applied"], refused=applied["refused"], failed=applied["failed"])
    state["dropped"] += [
        f"verdict row {json.dumps(r['row'], ensure_ascii=False)[:120]}: {r['reason']}"
        for r in applied["refused"]
    ]


# ---- command line ----


def budget_of(value: str | float | None, depth: str) -> float:
    if value is None:
        return LIMITS[depth][0]
    try:
        number = float(value)
    except ValueError:
        return LIMITS[depth][0]
    return number if number > 0 else LIMITS[depth][0]


def self_check() -> int:
    """No model and no network: the limits, the web session's command and environment, the tool lists of the others,
    the reply and passage helpers, and a refusal of an uncovered finding."""
    assert math.isclose(budget_of("x", "deep"), LIMITS["deep"][0])
    assert math.isclose(budget_of("0.3", "deep"), float("0.3"))
    assert math.isclose(budget_of("-1", "contrast"), LIMITS["contrast"][0])
    with tempfile.TemporaryDirectory(prefix="mem-research-check-") as tmp_name:
        tmp = Path(tmp_name)
        (tmp / "bin").mkdir()
        (tmp / "bin" / "mem").write_text("#!/bin/sh\n")
        (tmp / "bin" / "mem").chmod(0o755)
        os.environ.update({
            "MEM_STORE": "x",
            "CLAUDE_PLUGIN_ROOT": "x",
            "CLAUDE_PLUGIN_OPTION_STORE": "x",
            "PATH": f"{tmp / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        })
        env = headless.session_env()
        assert not any(k.startswith(("MEM_", "CLAUDE_PLUGIN")) for k in env), (
            "a MEM or plugin variable reached a session"
        )
        assert not any(headless.has_mem(p) for p in env["PATH"].split(os.pathsep)), (
            "mem is on a session's PATH"
        )
        cmd = web_cmd("claude", "prompt", tmp / "s.json", 0.2)
        assert (
            cmd[cmd.index("--tools") + 1] == "WebSearch,WebFetch" and "--strict-mcp-config" in cmd
        )
        assert "--plugin-dir" not in cmd
        assert cmd[cmd.index("--allowedTools") + 1 : cmd.index("--allowedTools") + 3] == [
            "WebSearch",
            "WebFetch",
        ]
        cmd = file_cmd("claude", "prompt", tmp / "w", tmp / "s.json", 0.2)
        assert (
            cmd[cmd.index("--tools") + 1] == "Read,Write,Edit"
            and "--strict-mcp-config" in cmd
            and "Bash" not in cmd
        )
        allowed = cmd[cmd.index("--allowedTools") + 1 : cmd.index("--allowedTools") + 4]
        assert all(t.startswith(("Read(", "Write(", "Edit(")) for t in allowed)
    assert (
        rc.parse_web_reply('```json\n[{"item": "q"}]\n```') == [{"item": "q"}]
        and rc.parse_web_reply("no") is None
    )
    assert rc.select_passages(
        "Alpha beta gamma are named here.\n\nUnrelated words only here.", "alpha beta"
    )[0].startswith("Alpha")
    assert rc.finding_problem("It holds 5000 cycles", "It holds 4000 cycles in the lab") is not None
    assert rc.question_problem("What is the limit?", {}) is None
    print("self-check passed")
    return 0


DESCRIPTION = (__doc__ or "").splitlines()[0]


def _need_question(parser: argparse.ArgumentParser, question: str | None) -> None:
    if not (question or "").strip():
        parser.error("a question is required")


def _requested_store(requested: Path | None) -> Path | None:
    """The store to use; None (and a message) when there is none."""
    store = requested.expanduser().resolve() if requested else default_store()
    if store is None or not (store / "mem-store.yaml").is_file():
        print(f"mem-research: no store at {store}", file=sys.stderr)
        return None
    return store


def _default_claude() -> str | None:
    return (
        os.environ.get("MEM_CLAUDE")
        or os.environ.get("CLAUDE_CODE_EXECPATH")
        or shutil.which("claude")
    )


def _default_depth() -> str:
    option = os.environ.get("MEM_RESEARCH_DEPTH") or os.environ.get(
        "CLAUDE_PLUGIN_OPTION_RESEARCH_DEPTH"
    )
    return option if option in DEPTHS else DEFAULT_DEPTH


def _dry_run(args: argparse.Namespace, store: Path, budget: float, seconds: int) -> int:
    problem = rc.question_problem(args.question) if args.depth != "memory" else None
    print(
        f"depth: {args.depth}; budget: {budget:.2f} USD; time limit: {seconds / 60:.0f} min; "
        f"pages: {PAGES.get(args.depth, 0)}; claude: {args.claude or '(none)'}; store: {store}; "
        + (f"would stop: {problem}" if problem else "would start")
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mem-research", description=DESCRIPTION)
    parser.add_argument("question", nargs="?")
    parser.add_argument(
        "--depth",
        choices=DEPTHS,
        default=_default_depth(),
        help="memory: only the memory; contrast: also 5 web pages; deep: 15 pages, papers asked for "
        "(default: the plugin option research_depth, else contrast)",
    )
    parser.add_argument(
        "--contrast",
        nargs="+",
        default=[],
        metavar="NOTE",
        help="knowledge notes to check against the web (replaces the choice of the memory step)",
    )
    parser.add_argument("--store", type=Path, help="default: MEM_STORE, else the default store")
    parser.add_argument(
        "--claude",
        default=_default_claude(),
    )
    parser.add_argument(
        "--budget", help="USD for the whole run (default: contrast 0.50, deep 2, memory 0.25)"
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help="a host fetched although it resolves to a non-public address (a local test page)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would run; start and change nothing"
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="no model: prove the session limits and the checks",
    )
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    if (refused := codex_pass.refuse_codex("mem-research")) is not None:
        return refused
    _need_question(parser, args.question)
    store = _requested_store(args.store)
    if store is None:
        return 2
    budget = budget_of(args.budget, args.depth)
    seconds = LIMITS[args.depth][1]
    if args.dry_run:
        return _dry_run(args, store, budget, seconds)
    for name in headless.SESSION_VARS:
        os.environ.pop(name, None)
    return research(
        store,
        args.question,
        depth=args.depth,
        contrast=args.contrast,
        claude=args.claude,
        budget=budget,
        seconds=seconds,
        allow_hosts=args.allow_host,
    )
