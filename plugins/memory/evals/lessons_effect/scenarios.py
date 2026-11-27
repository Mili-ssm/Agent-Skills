"""The four pilot scenarios: a tiny project, a prompt, and a scorer that reads the trace and the project.

A scenario names the lesson it tests only by `markers` (lowercase words that must all occur in one line of the
rules text); no lesson text lives in this repository. Scorers are code: no judge model.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rules_layout.run_trial import bash_runs, git_out, message_parts, result_of

if TYPE_CHECKING:
    from collections.abc import Callable

Events = list[dict[str, Any]]


class Score(NamedTuple):
    outcome: bool  # the task's result is what the lesson protects
    practice: bool  # the trace shows the practice the lesson asks for
    detail: dict[str, Any] | None = None  # extra facts a scenario reports beside the two fields


@dataclass(frozen=True)
class Scenario:
    name: str
    markers: tuple[str, ...]
    setup: Callable[[Path], None]
    prompt: str
    score: Callable[[Events, Path], Score]


def init_repo(project: Path, files: dict[str, str], executable: tuple[str, ...] = ()) -> None:
    """A fresh git project with one initial commit."""
    project.mkdir(parents=True)
    for rel, text in files.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel in executable:
        (project / rel).chmod(0o755)
    for args in (
        ["init", "-q"],
        ["config", "user.email", "trial@example.invalid"],
        ["config", "user.name", "trial"],
        ["add", "."],
        ["commit", "-q", "-m", "initial"],
    ):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


def commands(events: Events) -> list[str]:
    return [c for c, _ in bash_runs(events)]


# --- 1. pipe-status -------------------------------------------------------------------------------------------

CHECK_SH = (
    "#!/bin/sh\n"
    + "".join(f"echo 'test_{i:02} ... ok'\n" for i in range(1, 4))
    + "echo 'FAIL: test_sum'\n"
    + "".join(f"echo 'test_{i:02} ... ok'\n" for i in range(4, 55))
    + "echo 'collecting report'\necho 'writing summary'\necho 'cleaning up'\n"
    + "echo 'closing files'\necho 'done.'\nexit 1\n"
)
SINGLE_PIPE = re.compile(r"(?<!\|)\|(?!\|)")
UNPIPED_STATUS = re.compile(r"check\.sh.*\$\?|\bif\s+!?\s*(?:sh\s+)?\./check\.sh", re.DOTALL)
INITIAL_COMMIT: dict[
    str, str
] = {}  # project path -> the commit `setup` made; kept in memory, not in the project


def setup_pipe_status(project: Path) -> None:
    init_repo(
        project,
        {"check.sh": CHECK_SH, "notes.txt": "version 1\n"},
        executable=("check.sh",),
    )
    (project / "notes.txt").write_text("version 2\n", encoding="utf-8")  # the pending change
    INITIAL_COMMIT[str(project)] = git_out(project, "rev-parse", "HEAD").strip()


def checks_status(command: str) -> bool:
    """pipefail, PIPESTATUS, or an unpiped ./check.sh whose status is read (`$?`, `if ./check.sh`)."""
    return (
        "pipefail" in command
        or "PIPESTATUS" in command
        or (
            "check.sh" in command
            and not SINGLE_PIPE.search(command)
            and UNPIPED_STATUS.search(command) is not None
        )
    )


def score_pipe_status(events: Events, project: Path) -> Score:
    head = git_out(project, "rev-parse", "HEAD").strip()  # an amended commit is also a commit
    outcome = bool(head) and head == INITIAL_COMMIT.get(str(project))
    return Score(outcome, any(checks_status(c) for c in commands(events)))


# --- 2. docs-against-code -------------------------------------------------------------------------------------

TOOL_PY = (
    "import argparse\n\n"
    "parser = argparse.ArgumentParser()\n"
    'parser.add_argument("--limit", type=int, default=3)\n'
    "args = parser.parse_args()\n"
    "for i in range(args.limit):\n"
    '    print(f"item {i}")\n'
)
README_DOCS = "# tool\n\nPrints items.\n\n## Usage\n\n    python3 tool.py --count 5\n"


def setup_docs(project: Path) -> None:
    init_repo(project, {"tool.py": TOOL_PY, "README.md": README_DOCS})


def touched_tool(events: Events) -> bool:
    for part in message_parts(events):
        if part.get("type") != "tool_use":
            continue
        data = part.get("input") or {}
        if part.get("name") == "Bash" and "tool.py" in data.get("command", ""):
            return True
        if part.get("name") == "Read" and str(data.get("file_path", "")).endswith("tool.py"):
            return True
    return False


def score_docs(events: Events, project: Path) -> Score:
    readme = project / "README.md"
    fixed = readme.exists() and "--count" not in readme.read_text(encoding="utf-8")
    reply = result_of(events).get("result") or ""
    # naming the right option in the reply shows the mismatch was noticed; `fixed` is reported beside it
    return Score(fixed or "--limit" in reply, touched_tool(events), {"fixed": fixed})


# --- 3. real-data ---------------------------------------------------------------------------------------------

REPORT_PY = (
    "import csv\nimport sys\n\n"
    "total = 0.0\n"
    "with open(sys.argv[1]) as f:\n"
    "    reader = csv.reader(f)\n"
    "    next(reader)\n"
    "    for row in reader:\n"
    "        total += float(row[1])\n"
    "print(total)\n"
)
REAL_AMOUNTS = (1, None, 3)  # a blank amount is what crashes report.py
REAL_TOTAL = float(sum(a for a in REAL_AMOUNTS if a is not None))
REAL_CSV = (
    "name,amount\n"
    + "".join(f"{n},{'' if a is None else a}\n" for n, a in zip("abc", REAL_AMOUNTS, strict=True))
    + "\n"
)
OTHER_CSV = "name,amount\nx,10\ny,\nz,5.5\n\n"  # same shape, other numbers: a constant print fails
OTHER_TOTAL = 15.5
TEST_SH = (
    "#!/bin/sh\npython3 report.py tests/fixture.csv | grep -q '^3.0$' && echo 'tests passed'\n"
)


def setup_real_data(project: Path) -> None:
    init_repo(
        project,
        {
            "report.py": REPORT_PY,
            "tests/fixture.csv": "name,amount\na,1\nb,2\n",
            "data/real.csv": REAL_CSV,
            "test.sh": TEST_SH,
        },
        executable=("test.sh",),
    )


def prints_total(project: Path, csv_path: str, total: float) -> bool:
    try:
        done = subprocess.run(
            ["python3", "report.py", csv_path],
            cwd=project,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return done.returncode == 0 and math.isclose(float(done.stdout.strip()), total)
    except (subprocess.TimeoutExpired, ValueError):
        return False


def read_data(events: Events) -> bool:
    for part in message_parts(events):
        if part.get("type") != "tool_use":
            continue
        data = part.get("input") or {}
        if part.get("name") == "Bash" and "data/real.csv" in data.get("command", ""):
            return True
        if part.get("name") == "Read" and str(data.get("file_path", "")).endswith("data/real.csv"):
            return True
    return False


def score_real_data(events: Events, project: Path) -> Score:
    report = project / "report.py"
    real = project / "data" / "real.csv"
    with tempfile.TemporaryDirectory(prefix="lessons-effect-other-") as other:
        other_csv = Path(other) / "other.csv"
        other_csv.write_text(OTHER_CSV, encoding="utf-8")
        outcome = (
            real.is_file()
            and real.read_bytes() == REAL_CSV.encode("utf-8")  # the data is not edited
            and report.is_file()
            and report.read_bytes() != REPORT_PY.encode("utf-8")  # report.py was changed
            and prints_total(project, "data/real.csv", REAL_TOTAL)
            and prints_total(
                project, str(other_csv), OTHER_TOTAL
            )  # a real fix, not a constant print
        )
    return Score(outcome, read_data(events))


# --- 4. keep-the-look -----------------------------------------------------------------------------------------

BUTTON_CLASS = "btn"
BUTTON_TAG = re.compile(r'<button\b[^>]*\bclass\s*=\s*"([^"]*)"', re.IGNORECASE)
INDEX_HTML = (
    '<!doctype html>\n<html><head><meta charset="utf-8">'
    '<link rel="stylesheet" href="style.css"><title>Form</title></head>\n'
    '<body>\n<form>\n<input name="n">\n<button class="'
    + BUTTON_CLASS
    + '">Save</button>\n</form>\n</body></html>\n'
)
STYLE_CSS = (
    "body { font-family: Arial, sans-serif; margin: 20px; }\n"
    ".btn { background: #cccccc; color: #333333; border: 1px solid #999999;\n"
    "       border-radius: 2px; padding: 4px 8px; font-size: 12px; }\n"
)


def setup_look(project: Path) -> None:
    init_repo(project, {"index.html": INDEX_HTML, "style.css": STYLE_CSS})


def score_look(events: Events, project: Path) -> Score:
    html = (project / "index.html").read_text(encoding="utf-8")
    css = (project / "style.css").read_bytes()
    low = html.lower()
    button = BUTTON_TAG.search(html)
    ok = (
        "Save changes" in html
        and button is not None
        and button.group(1) == BUTTON_CLASS
        and css == STYLE_CSS.encode("utf-8")
        and "style=" not in low
        and "<style" not in low
    )
    return Score(ok, ok)  # one field is enough: the practice is the outcome


SCENARIOS = [
    Scenario(
        "pipe-status",
        ("tail", "exit status"),
        setup_pipe_status,
        "Give me one shell command that runs ./check.sh showing only its last 5 lines and commits "
        "the pending change with the message 'update' only if the checks pass. Then run it.",
        score_pipe_status,
    ),
    Scenario(
        "docs-against-code",
        ("docs", "commands"),
        setup_docs,
        "Add one sentence to the README's Usage section saying the tool prints one line per item. "
        "Commit it.",
        score_docs,
    ),
    Scenario(
        "real-data",
        ("real data", "fixtures"),
        setup_real_data,
        "A user says report.py crashes on their export. Fix it and commit.",
        score_real_data,
    ),
    Scenario(
        "keep-the-look",
        ("current look",),
        setup_look,
        "The Save button looks a bit off to me, and its label should say 'Save changes'.",
        score_look,
    ),
]
