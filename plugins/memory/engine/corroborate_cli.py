"""mem-corroborate: the commands that need the whole engine, and the self-check."""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

import capture_state as cs
import corroborate_digest
import corroborate_fill
import corroborate_reword
import corroborate_run
import corroborate_state
import jobs

logger = logging.getLogger(__name__)

_CHECK_BUDGET = 0.6
_PRIVATE_MODE = 0o700


def cmd_run(args) -> int:
    if args.dry_run and not args.out:
        print("mem-corroborate: --dry-run needs --out FILE", file=sys.stderr)
        return 2
    if args.out and not args.dry_run:
        print("mem-corroborate: --out goes with --dry-run", file=sys.stderr)
        return 2
    if args.dry_run and args.groups:
        print(
            "mem-corroborate: --dry-run runs the sessions: it does not take --groups",
            file=sys.stderr,
        )
        return 2
    if args.dry_run:
        repo = corroborate_run.repo_above(Path(args.out).expanduser().resolve().parent)
        if repo is not None:
            print(
                f"mem-corroborate: --out is inside a repository ({repo}); the result holds memory text",
                file=sys.stderr,
            )
            return 2
    line = corroborate_run.execute(args.claude, args.budget, args.groups, args.dry_run, args.out)
    print(
        summary(line)
        if not line.get("failed_reason")
        else f"mem-corroborate: failed: {line['failed_reason']}"
    )
    return 1 if line["failed"] else 0


def cmd_fill(args) -> int:
    usage = "usage: mem-corroborate fill --dry-run --out FILE [--claude PATH] [--budget USD] | fill --items FILE"
    if args.items:
        if args.dry_run or args.out:
            print(
                f"mem-corroborate: --items applies a file and goes with neither --dry-run nor --out\n{usage}",
                file=sys.stderr,
            )
            return 2
        return corroborate_fill.fill_items(args)
    if not (args.dry_run and args.out):
        print(
            f"mem-corroborate: fill writes nothing unread: it needs --dry-run --out FILE or --items FILE\n{usage}",
            file=sys.stderr,
        )
        return 2
    return corroborate_fill.fill_dry_run(args)


def cmd_reword(args) -> int:
    if (
        args.every and not args.dry_run
    ):  # --every is for the gate on a copy: on a real store it would mark every lesson reworded
        print(
            "mem-corroborate: --every goes with --dry-run: it takes lessons that did not get worse, for a trial on a copy",
            file=sys.stderr,
        )
        return 2
    sheet = Path(args.sheet).expanduser() if args.sheet else None
    if sheet is not None:
        repo = corroborate_run.repo_above(sheet.resolve().parent)
        if repo is not None:
            print(
                f"mem-corroborate: --sheet is inside a repository ({repo}); the sheet holds memory text",
                file=sys.stderr,
            )
            return 2
    result = corroborate_reword.reword_auto(
        args.claude,
        args.budget,
        every=args.every,
        apply=not args.dry_run,
        sheet=sheet,
        limit=args.limit,
    )
    print(json.dumps(result))
    return 1 if result["stopped"] else 0


def cmd_digest(args) -> int:
    sheet = Path(args.sheet).expanduser() if args.sheet else None
    if sheet is not None:
        repo = corroborate_run.repo_above(sheet.resolve().parent)
        if repo is not None:
            print(
                f"mem-corroborate: --sheet is inside a repository ({repo}); the sheet holds memory text",
                file=sys.stderr,
            )
            return 2
    result = corroborate_digest.digest_auto(
        args.claude, args.budget, apply=not args.dry_run, sheet=sheet
    )
    print(json.dumps(result))
    return 1 if result["stopped"] else 0


def _auto_budget() -> float | None:
    """The budget of `auto`, or None when the option is off or cannot be read."""
    try:
        if os.environ.get(cs.OPTION) != "true":
            return None
        return corroborate_state.budget_of(os.environ.get(cs.BUDGET_OPTION))
    except BaseException:
        logger.debug("auto: the option could not be read", exc_info=True)
        return None


def _quietly(step) -> None:
    """Run one step of `auto`; whatever it raises is logged at debug level and dropped."""
    try:
        step()
    except BaseException:
        logger.debug("auto: a step failed", exc_info=True)


def _logged_pass(key: str, run_pass) -> None:
    """Run a pass and append its result and duration to the corroborate log."""
    began = time.time()
    stamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    result = run_pass()
    corroborate_state.append_log(
        corroborate_state.corroborate_dir(corroborate_state.data_dir()),
        {"t": stamp, key: result, "ms": int((time.time() - began) * 1000)},
    )


def _loaded_rules_passes(claude, budget: float) -> None:
    """The passes over the lessons that load as rules; the optional ones fail on their own."""
    if (
        os.environ.get("CLAUDE_PLUGIN_OPTION_LOADED_RULES") == "false"
        or os.environ.get("MEM_LOADED_RULES") == "off"
    ):
        return
    _logged_pass("fill", lambda: corroborate_fill.fill_auto(claude, budget))
    if (
        os.environ.get("CLAUDE_PLUGIN_OPTION_AUTO_REWORD") == "true"
    ):  # option auto_reword, off by default
        _quietly(
            lambda: _logged_pass("reword", lambda: corroborate_reword.reword_auto(claude, budget))
        )
    if (
        os.environ.get("CLAUDE_PLUGIN_OPTION_RULES_LAYOUT") == "digest"
    ):  # option rules_layout, "flat" by default
        _quietly(
            lambda: _logged_pass("digest", lambda: corroborate_digest.digest_auto(claude, budget))
        )


def cmd_auto(args) -> int:
    """The whole of `auto`; never raises and never prints."""
    budget = _auto_budget()
    if budget is None:
        return 0
    _quietly(lambda: corroborate_run.execute(args.claude, budget))
    _quietly(lambda: _loaded_rules_passes(args.claude, budget))
    return 0


def summary(line: dict) -> str:
    if line["failed"]:
        return f"mem-corroborate: failed: {line['failed']}"
    if line["skipped"]:
        return f"mem-corroborate: skipped: {line['skipped']}"
    more = (
        f", {line['failed_actions']} failed (tried again next run)"
        if line["failed_actions"]
        else ""
    )
    return (
        f"mem-corroborate: {line['lessons']} lessons, {line['verified']} of {line['proposed']} groups applied: "
        f"{line['written']} written, {line['sightings']} sightings, {line['links']} links, {line['merges']} merges, "
        f"{line['refused']} refused{more}"
    )


def self_check() -> int:
    """No model: the briefs, the tool list, the gate of `auto`, the lock and the folder mode, the journal and undo."""
    assert (
        corroborate_state.budget_of("x") == corroborate_state.DEFAULT_BUDGET
        and corroborate_state.budget_of("0.6") == _CHECK_BUDGET
        and corroborate_state.budget_of("0") == corroborate_state.DEFAULT_BUDGET
    )
    corroborate_run.PROPOSE_BRIEF.format(lessons="a", out="b")
    corroborate_run.VERIFY_BRIEF.format(groups="a", out="b")
    corroborate_run.FILL_BRIEF.format(lessons="a", out="b")
    corroborate_run.REWORD_BRIEF.format(lessons="a", out="b")
    corroborate_run.DIGEST_BRIEF.format(topics="a", out="b")
    corroborate_run.DIGEST_CHECK_BRIEF.format(pairs="a", out="b")
    with tempfile.TemporaryDirectory(prefix="mem-corroborate-check-") as tmp_name:
        tmp = Path(tmp_name)
        os.environ.pop(cs.OPTION, None)
        os.environ["MEM_DATA"] = str(tmp / "data")
        cmd_auto(argparse.Namespace(claude="/nonexistent"))
        assert not corroborate_state.corroborate_dir(tmp / "data").exists(), (
            "auto ran without the option"
        )
        cdir = corroborate_state.corroborate_dir(tmp / "data")
        held = jobs.take_run_lock(cdir)
        assert held is not None and jobs.take_run_lock(cdir) is None
        assert (cdir.stat().st_mode & 0o777) == _PRIVATE_MODE, oct(cdir.stat().st_mode)
        os.close(held)
        cmd = corroborate_run.session_cmd(
            "claude",
            tmp / "w",
            "brief",
            tmp / "s.json",
            corroborate_run.SessionLimits("haiku", 0.25),
        )
        allowed = cmd[cmd.index("--allowedTools") + 1 : cmd.index("--disallowedTools")]
        assert (
            not any(t.startswith("Bash") for t in allowed)
            and "Bash" in cmd[cmd.index("--disallowedTools") + 1 :]
        )
        assert all(
            t.startswith(("Read(", "Write(", "Edit(")) and f"{tmp}/w" in t for t in allowed
        ), allowed
        run = cdir / "runs" / "x"
        jobs.private_dir(run)
        a, b = tmp / "a.md", tmp / "b.md"
        a.write_text("one")
        journal = corroborate_state.Journal(run)
        watched = journal.watch([a, b])
        a.write_text("two")
        b.write_text("new")
        journal.commit("check", watched)
        assert corroborate_state.undo_run(run)[0] and a.read_text() == "one" and not b.exists()
        a.write_text("two")
        run2 = cdir / "runs" / "y"
        jobs.private_dir(run2)
        journal = corroborate_state.Journal(run2)
        watched = journal.watch([a])
        a.write_text("three")
        journal.commit("check", watched)
        a.write_text("edited")
        assert not corroborate_state.undo_run(run2)[0] and a.read_text() == "edited", (
            "undo ran over an edited file"
        )
    print("self-check passed")
    return 0
