"""mem-corroborate: a background pass that matches lessons by meaning and keeps one general record of each.

`run` collects the active transcript lessons of the registered projects and of the global scope, writes them to a
lessons file (ids only, no project name or path) and starts two tool-less headless sessions: the first proposes
groups of lessons that state the same thing; the second, a fresh process that sees only the proposals, says for each
group whether it is the same lesson, faithfully worded and general. Code validates both answers (`corroborate`) and
applies only the groups that pass, always through `bin/mem` (a secret, a forbidden term or a refused merge is
counted, never forced). The claim of an existing record is never changed.

Undo works on file copies: before a run's first write to a record's file the file is copied to
`runs/<stamp>/before/`, and `journal.jsonl` holds each action, the file, whether the run created it and the hash of
the file afterwards. `undo <stamp>` restores or removes them, and refuses, changing nothing, when a file changed
since. The run folder is private and may hold memory text; `log.jsonl` holds counts only.

`auto` is what a hook starts when the plugin option `auto_capture` is exactly `true`: it never raises and never prints.

Usage: mem-corroborate run [--claude PATH] [--budget USD] [--dry-run --out FILE] [--groups FILE]
       mem-corroborate auto [--claude PATH] | undo STAMP | status | ack | --self-check
       mem-corroborate fill --dry-run --out FILE [--claude PATH] [--budget USD] | fill --items FILE

`fill` proposes the one-line short form and the topic of the lessons that could load as rules at session start but
lack them. Nothing writes a short form unread: `--dry-run --out FILE` only writes the proposal (one session of the
small model); the owner reads and edits FILE, and `--items FILE` applies it through `mem memory edit` (journaled:
`undo STAMP` puts the records back). Each item also carries `load`: `yes` (a rule), `index` (only counted by topic)
or `no` (never loaded); the owner may change it. `seen.json` and the status of the pass are not touched.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import shutil
import sys
import time

from capture import state as cs
from core import runner as runners
from corroborate import state as corroborate_state

try:  # `auto` must still be able to write a failed status when the engine cannot be imported (e.g. no yaml)
    from corroborate import cli as corroborate_cli

    IMPORT_ERROR: Exception | None = None
except Exception as _exc:
    corroborate_cli = None
    IMPORT_ERROR = _exc
    logging.getLogger(__name__).debug("the engine cannot be loaded", exc_info=True)


def _no_engine(_args) -> int:
    print(f"mem-corroborate: cannot load the engine: {IMPORT_ERROR}", file=sys.stderr)
    return 1


def _failed_status_for_auto() -> None:
    if os.environ.get(cs.OPTION) != "true":
        return
    start = time.time()
    stamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    cdir = corroborate_state.corroborate_dir(corroborate_state.data_dir())
    reason = "engine import error"
    failure = {"at": time.time(), "reason": reason, "log": ""}
    corroborate_state.save_status(cdir, state="failed", finished=time.time(), failure=failure)
    counts = dict.fromkeys(("lessons", "groups", "proposed", "verified", "dropped", "written"), 0)
    counts |= dict.fromkeys(
        ("sightings", "links", "merges", "refused", "failed_actions", "cases"), 0
    )
    ms = int((time.time() - start) * 1000)
    line = {"t": stamp, **counts, "skipped": None, "cost": 0.0, "failed": reason, "ms": ms}
    corroborate_state.append_log(cdir, line)


def _auto_without_engine(_args) -> int:
    """`auto` when the engine cannot load: the failed status and the log line `execute` wrote for it, nothing else;
    never raises and never prints."""
    try:
        _failed_status_for_auto()
    except BaseException:
        logging.getLogger(__name__).debug("auto: the failed status was not written", exc_info=True)
    return 0


def _command(name: str, without_engine=_no_engine):
    """The engine's command, or `without_engine` when the engine cannot load (`status`, `ack` and `undo` never need it)."""
    return without_engine if corroborate_cli is None else getattr(corroborate_cli, name)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--self-check", action="store_true", help="no model: prove the briefs, gates, lock and undo"
    )
    commands = parser.add_subparsers(dest="command")
    default_claude = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    run = commands.add_parser(
        "run", help="match the lessons by meaning and apply the verified groups"
    )
    run.add_argument("--claude", default=default_claude)
    runners.add_flag(run)
    run.add_argument(
        "--budget",
        type=corroborate_state.budget_of,
        default=corroborate_state.DEFAULT_BUDGET,
        help=f"USD per session (default {corroborate_state.DEFAULT_BUDGET})",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="run both sessions; write the plan to --out and change nothing else",
    )
    run.add_argument(
        "--out",
        help="with --dry-run: the file for the proposal, the verdicts and the planned actions",
    )
    run.add_argument(
        "--groups", help="apply a reviewed file in the model's format; starts no model session"
    )
    run.set_defaults(func=_command("cmd_run"))
    fill = commands.add_parser(
        "fill",
        help="propose the short form and topic of lessons for the owner to read, or apply that file",
    )
    fill.add_argument("--claude", default=default_claude)
    runners.add_flag(fill)
    fill.add_argument(
        "--budget",
        type=corroborate_state.budget_of,
        default=corroborate_state.DEFAULT_BUDGET,
        help=f"USD for the session (default {corroborate_state.DEFAULT_BUDGET})",
    )
    fill.add_argument(
        "--dry-run",
        action="store_true",
        help="one session; write the proposal to --out and change no record",
    )
    fill.add_argument("--out", help="with --dry-run: the file for the proposal")
    fill.add_argument(
        "--items",
        help="apply a proposal file, as read and edited by the owner; starts no model session",
    )
    fill.set_defaults(func=_command("cmd_fill"))
    reword = commands.add_parser(
        "reword", help="write a new short form for loaded lessons that got worse, as the pass does"
    )
    reword.add_argument("--claude", default=default_claude)
    runners.add_flag(reword)
    reword.add_argument(
        "--budget",
        type=corroborate_state.budget_of,
        default=corroborate_state.DEFAULT_BUDGET,
        help=f"USD per session (default {corroborate_state.DEFAULT_BUDGET})",
    )
    reword.add_argument(
        "--every", action="store_true", help="take loaded lessons that did not get worse too"
    )
    reword.add_argument(
        "--limit", type=int, default=30, help="with --every: at most this many lessons (default 30)"
    )
    reword.add_argument(
        "--dry-run",
        action="store_true",
        help="run both sessions; change no record and save no state",
    )
    reword.add_argument(
        "--sheet", help="write a Markdown table of every candidate and its outcome to this file"
    )
    reword.set_defaults(func=_command("cmd_reword"))
    digest_cmd = commands.add_parser(
        "digest",
        help="write the heading and the lines of the loaded lessons' digest, as the pass does",
    )
    digest_cmd.add_argument("--claude", default=default_claude)
    runners.add_flag(digest_cmd)
    digest_cmd.add_argument(
        "--budget",
        type=corroborate_state.budget_of,
        default=corroborate_state.DEFAULT_BUDGET,
        help=f"USD per session (default {corroborate_state.DEFAULT_BUDGET})",
    )
    digest_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="run both sessions; write no digest and save no state",
    )
    digest_cmd.add_argument(
        "--sheet", help="write a Markdown table of every line judged and its outcome to this file"
    )
    digest_cmd.set_defaults(func=_command("cmd_digest"))
    auto = commands.add_parser(
        "auto", help="what a hook starts: one run when the option is on; silent"
    )
    auto.add_argument("--claude", default=default_claude)
    runners.add_flag(auto)
    auto.set_defaults(func=_command("cmd_auto", _auto_without_engine))
    undo = commands.add_parser("undo", help="put back the files a run changed")
    undo.add_argument("stamp")
    undo.set_defaults(func=corroborate_state.cmd_undo)
    commands.add_parser("status", help="the last run").set_defaults(
        func=lambda _a: corroborate_state.cmd_status()
    )
    commands.add_parser("ack", help="clear the failure line").set_defaults(
        func=lambda _a: corroborate_state.cmd_ack()
    )
    args = parser.parse_args()
    if args.self_check:
        return _no_engine(args) if corroborate_cli is None else corroborate_cli.self_check()
    if not args.command:
        parser.error("a command is required")
    runners.pin_flag(getattr(args, "runner", None))
    return args.func(args)
