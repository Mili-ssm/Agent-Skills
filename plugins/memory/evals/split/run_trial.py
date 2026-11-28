#!/usr/bin/env python3
"""Exercise a seeded split through the real CLI on disposable synthetic stores."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
ENGINE = PLUGIN / "engine"
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(HERE.parent))
import trial_env
from notes.note import split_frontmatter
from syntheses import units

MOVES = 5
SEED = json.loads((HERE / "seed.json").read_text())
HEADER = "---\ntitle: {title}\ntopics: [{topic}]\ncreated: '2026-01-01'\nupdated: '2026-01-01'\n---\n\n## Summary\n\nSummary.\n"


def snapshot(root):
    return {
        p.relative_to(root): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and not any(x in p.parts for x in (".split-history", ".split-recovery"))
    }


def run(root, env, *args, ok=True):
    result = subprocess.run(
        [str(PLUGIN / "bin/mem"), "--root", str(root), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != (0 if ok else 2):
        raise AssertionError(
            f"{' '.join(args)}: exit {result.returncode}: {result.stderr} {result.stdout}"
        )
    return result.stdout


def trial(work, existing):  # ruff: ignore[too-many-locals, too-many-statements]
    root = work / ("existing" if existing else "new")
    shutil.copytree(ENGINE / "tests/fixtures/valid", root)
    shutil.copytree(ENGINE / "templates", root / "templates")
    (root / "mem-store.yaml").write_text("format: 1\n")
    folder = root / "knowledge/computing"
    folder.mkdir(parents=True, exist_ok=True)
    body = SEED["child_text"]
    parent = root / "syntheses/parent.md"
    parent.parent.mkdir(exist_ok=True)
    parent.write_text(
        HEADER.format(title="Parent", topic="computing") + "\n## Part\n\n" + body + "\n"
    )
    child = root / "syntheses/ml.md"
    if existing:
        child.write_text(
            HEADER.format(title="Child", topic="ml")
            + "\n## Earlier\n\nEarlier.\n\nSources: experience 2026-01-01\n"
        )
    for i in range(6):
        topic = "ml, computing" if i < MOVES else "computing"
        (folder / f"n{i}.md").write_text(
            f"---\ntopics: [{topic}]\nclaim: Claim {i}\npart_of: parent#part\n"
            f"part_of_hash: {units.fingerprint(body)}\nconfidence: medium\nlevel: intermediate\norigin: literature\nupdated: 2026-11-07\n---\n\n## Claim\n\nClaim.\n\n## Evidence\n\nEvidence.\n\n## Applies when\n\nAlways.\n\n## Does not apply when\n\nNever.\n"
        )
    env = trial_env.make_env(work)
    env["MEM_PROJECT"] = str(work / "project")
    run(root, env, "index")
    run(root, env, "check")
    before = snapshot(root)
    candidate = json.loads(
        run(root, env, "synthesis", "split", "--candidate", "s:parent#part", "ml")
    )["proposal"]
    candidate.update(SEED)
    path = work / ("existing.json" if existing else "new.json")
    path.write_text(json.dumps(candidate))
    preview = json.loads(run(root, env, "synthesis", "split", "--preview", str(path)))
    assert len(preview["moves"]) == MOVES, preview
    assert snapshot(root) == before, (
        snapshot(root).keys() - before.keys(),
        before.keys() - snapshot(root).keys(),
    )
    for bad_text in (
        body.replace("42", "forty two"),
        body + "\n\n[bad](../knowledge/computing/missing.md)",
    ):
        bad = {**candidate, "child_text": bad_text}
        path.write_text(json.dumps(bad))
        run(root, env, "synthesis", "split", "--preview", str(path), ok=False)
        assert snapshot(root) == before
    path.write_text(json.dumps(candidate))
    group = run(root, env, "synthesis", "split", "--apply", str(path)).strip()
    parent_text, child_text = parent.read_text(), child.read_text()
    assert "42 cases" in child_text and all(
        f"../knowledge/computing/n{i}.md" in child_text for i in range(5)
    )
    assert "../knowledge/computing/n5.md" in parent_text and "(ml.md#details)" in parent_text
    assert "(parent.md#part)" in child_text
    assert not existing or "## Earlier\n\nEarlier." in child_text
    for i in range(6):
        text = (folder / f"n{i}.md").read_text()
        assert split_frontmatter(text)[0]["part_of"] == (
            "ml#details" if i < MOVES else "parent#part"
        )
        assert f"claim: Claim {i}" in text
    run(root, env, "check")
    run(root, env, "synthesis", "split", "--undo", group)
    assert snapshot(root) == before
    if existing:
        child.write_text(child.read_text() + "\n## Details\n\nCollision.\n")
        candidate = json.loads(
            run(root, env, "synthesis", "split", "--candidate", "s:parent#part", "ml")
        )["proposal"]
        candidate.update(SEED)
        path.write_text(json.dumps(candidate))
        collision_before = snapshot(root)
        run(root, env, "synthesis", "split", "--preview", str(path), ok=False)
        assert snapshot(root) == collision_before
    print(f"{'existing' if existing else 'new'} child: PASS (preview, apply, routing, check, undo)")


def main():
    work = trial_env.work_dir("split-")
    try:
        trial(work, False)
        trial(work, True)
    finally:
        trial_env.clean(work)


if __name__ == "__main__":
    main()
