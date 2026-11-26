"""A store with one synthesis part and the knowledge notes `mem synthesis integrate` joins to it. It is not a `conftest.py`: a second one would replace `tests/conftest.py` for the modules that import from it."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import mem
import pytest
from notes.note import split_frontmatter
from syntheses import document, units

if TYPE_CHECKING:
    from pathlib import Path

EXISTING = "../knowledge/computing/existing-note.md"
SENTENCE_ONE = "Values have exactly one owner."
SENTENCE_TWO = "Borrowing lends a value without moving it."
NEW_CLAIM = "Rust moves values by default."
PART = (
    f"{SENTENCE_ONE}[existing-note]({EXISTING}) {SENTENCE_TWO}[existing-note]({EXISTING})\n\n"
    f"Sources: [existing-note]({EXISTING})"
)


@dataclass
class Store:
    root: Path
    capsys: pytest.CaptureFixture[str]
    tmp: Path

    def mem(self, *argv: str) -> tuple[int, str, str]:
        code = mem.main(["--root", str(self.root), *argv])
        out = self.capsys.readouterr()
        return code, out.out, out.err

    def write(self, name: str, text: str) -> str:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def new_note(self, slug: str, claim: str) -> None:
        body = (
            f"## Claim\n\n{claim}\n\n## Evidence\n\nObserved.\n\n## Applies when\n\nAlways.\n\n"
            "## Does not apply when\n\nNever.\n"
        )
        code = self.mem(
            "new", "knowledge", "--slug", slug, "--claim", claim, "--topics", "ml",
            "--confidence", "low", "--level", "basic", "--origin", "experience",
            "--body-file", self.write(f"{slug}.md", body),
        )[0]  # fmt: skip
        assert code == 0

    def integrate(self, *rows: str) -> tuple[int, str, str]:
        return self.mem("synthesis", "integrate", self.write("rows.txt", "\n".join(rows) + "\n"))

    def candidates(self) -> list[dict]:
        code, out, _ = self.mem("synthesis", "integrate", "--candidates")
        assert code == 0
        return json.loads(out)

    def section(self, handle: str = "alpha", name: str = "basics") -> str:
        syn = document.load_one(self.root / "syntheses" / f"{handle}.md")
        return next(s.text for s in syn.sections if s.handle == name)

    def note_path(self, slug: str) -> Path:
        return next((self.root / "knowledge").glob(f"*/{slug}.md"))

    def meta(self, slug: str) -> dict:
        text = self.note_path(slug).read_text(encoding="utf-8")
        return split_frontmatter(text)[0]

    def edit_meta(self, slug: str, line: str) -> None:
        """Add one frontmatter line to a note."""
        path = self.note_path(slug)
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("\n---\n", f"\n{line}\n---\n", 1), encoding="utf-8")

    def set_line(self, slug: str, key: str, value: object) -> None:
        """Replace one frontmatter line of a note, bypassing the checks `mem new` and `mem note edit` make."""
        path = self.note_path(slug)
        text = re.sub(
            rf"(?m)^{key}:.*$", f"{key}: {json.dumps(value)}", path.read_text("utf-8"), count=1
        )
        path.write_text(text, encoding="utf-8")

    def fingerprint(self) -> str:
        return units.fingerprint(self.section())

    def snapshot(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file() and not p.name.startswith(".curation-log")
        }

    def log_lines(self) -> list[dict]:
        log = self.root / ".curation-log"
        if not log.exists():
            return []
        return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x]


@pytest.fixture
def store_with_part(hub_root, capsys, tmp_path) -> Store:
    """Synthesis `alpha` (topic ml), section `basics` with two sentences that cite `existing-note`, a member of the
    part; knowledge notes `n-new` and `n-dup` (its claim is the second sentence) are not part of anything."""
    s = Store(hub_root, capsys, tmp_path)
    s.new_note("existing-note", "Ownership is tracked by the compiler.")
    s.new_note("n-new", NEW_CLAIM)
    s.new_note("n-dup", SENTENCE_TWO)
    code = s.mem(
        "synthesis", "new", "--title", "Alpha", "--topics", "ml", "--slug", "alpha",
        "--summary-file", s.write("summary.md", "Rust ownership.\n"),
    )[0]  # fmt: skip
    assert code == 0
    code, _, err = s.mem(
        "synthesis", "add", "s:alpha", "--section", "Basics", "--body-file",
        s.write("part.md", PART + "\n"),
    )  # fmt: skip
    assert code == 0, err
    assert s.mem("synthesis", "attach", "existing-note", "s:alpha#basics")[0] == 0
    assert s.mem("check")[0] == 0
    return s
