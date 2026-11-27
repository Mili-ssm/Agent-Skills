#!/usr/bin/env python3
"""Choose the signal thresholds on the labelled set (set.json), by the rule written in the stage 6 plan.

Run: uv run --with pyyaml python plugins/memory/evals/signal/score.py
The set is split by alternating briefs: odd ids tune, even ids test. For each pair of thresholds it prints, on
the tuning half, how many signalled briefs name only related records (precision by brief) and how many briefs
that have a related record get a signal (coverage); then the same two figures for every pair on the test half.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
from memories import records

DATA = json.loads((Path(__file__).parent / "set.json").read_text())


def scores(brief: str) -> dict[str, float]:
    text = set(records.tokenize(brief + "\n" + DATA["boilerplate"]))
    out = {
        h: records.containment(records.tokenize(claim), text)
        for h, claim in DATA["memories"].items()
    }
    out.update({
        stem: records.containment(records.tokenize(stem.replace("-", " ")), text)
        for stem in DATA["notes"]
    })
    return out


def figures(briefs: list[dict], strong: float) -> tuple[int, int, int, int]:
    signalled = clean = with_related = covered = 0
    for brief in briefs:
        named = {h for h, s in scores(brief["text"]).items() if s >= strong}
        related = set(brief["related"])
        with_related += bool(related)
        if named:
            signalled += 1
            clean += named <= related
            covered += bool(named & related)
    return clean, signalled, covered, with_related


def main() -> int:
    tune = [b for b in DATA["briefs"] if b["id"] % 2]
    test = [b for b in DATA["briefs"] if not b["id"] % 2]
    print("strong  tune: clean/signalled  covered/related   test: clean/signalled  covered/related")
    for strong in (0.4, 0.5, 0.6, 0.67, 0.75, 0.8, 0.9, 1.0):
        a, b = figures(tune, strong), figures(test, strong)
        print(
            f"{strong:<6}  {a[0]:>5}/{a[1]:<9}  {a[2]:>5}/{a[3]:<9}  {b[0]:>10}/{b[1]:<9}  {b[2]:>5}/{b[3]}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
