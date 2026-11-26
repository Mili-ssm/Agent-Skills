"""`mem.py` only shrinks while A5 moves the handlers to `commands/` (ADR 0028): each task lowers the ceiling."""

from pathlib import Path

MEM_PY = Path(__file__).resolve().parent.parent / "mem.py"
CEILING = 4203  # lines; lowered by every A5 task, at most 1,350 after the last (plan 2026-11-26-memory-mem-split.md)


def test_mem_py_stays_under_its_line_ceiling():
    lines = len(MEM_PY.read_text(encoding="utf-8").splitlines())
    assert lines <= CEILING, (
        f"mem.py grew to {lines} lines (ceiling {CEILING}): new code goes to a module, not mem.py"
    )
