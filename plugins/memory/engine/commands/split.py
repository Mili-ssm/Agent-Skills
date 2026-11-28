"""CLI for inspectable, recoverable synthesis splits."""

import datetime
import json
import os
import sys
from pathlib import Path

import yaml
from notes import note as note_files

from commands import common, split_plan, split_transaction


def _proposal(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    keys = {"part", "topic", "parent_text", "child_heading", "child_text", "expected"}
    if not isinstance(data, dict) or set(data) != keys:
        raise ValueError("proposal must contain exactly the candidate proposal fields")
    if any(not isinstance(data[k], str) for k in keys - {"expected"}):
        raise ValueError("proposal text fields must be strings")
    expected = data["expected"]
    if not isinstance(expected, dict) or any(
        not isinstance(k, str) or (v is not None and not isinstance(v, str))
        for k, v in expected.items()
    ):
        raise ValueError("expected must map paths to digests or null")
    return split_plan.SplitProposal(**data)


def _run(args):  # ruff: ignore[complex-structure]
    root = args.root.resolve()
    if args.candidate:
        print(json.dumps(split_plan.candidate_input(root, *args.candidate), ensure_ascii=False))
    elif args.preview or args.apply:
        proposal = _proposal(args.preview or args.apply)

        def prepare():
            return split_plan.prepare_split(root, proposal, datetime.date.today(), os.environ)

        if args.apply:
            print(split_transaction.apply_split(root, prepare))
        else:
            plan = prepare()
            print(
                json.dumps(
                    {
                        "original": plan.original,
                        "retained": plan.parent_text,
                        "moved": plan.child_text,
                        "destination": plan.destination,
                        "moves": plan.moves,
                        "conflicts": plan.conflicts,
                    },
                    ensure_ascii=False,
                )
            )
    elif args.undo:
        split_transaction.undo_split(root, args.undo)
        print("undone")
    elif args.recover:
        print("recovered" if split_transaction.recover_split(root) else "nothing to recover")
    else:
        pending, groups = split_transaction.split_status(root)
        print(json.dumps({"pending": pending, "groups": groups}))
    return 0


def cmd_split(args):
    try:
        return _run(args)
    except (
        common.NewNoteError,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        note_files.FrontmatterError,
        yaml.YAMLError,
    ) as exc:
        print(f"mem: {exc}", file=sys.stderr)
        return 2


def register(sub):
    parser = sub.add_parser("split", help="preview and manage a recoverable synthesis split")
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--candidate", nargs=2, metavar=("PART", "TOPIC"))
    choices.add_argument("--preview", metavar="FILE")
    choices.add_argument("--apply", metavar="FILE")
    choices.add_argument("--undo", metavar="GROUP")
    choices.add_argument("--recover", action="store_true")
    choices.add_argument("--status", action="store_true")
    parser.set_defaults(func=cmd_split)
