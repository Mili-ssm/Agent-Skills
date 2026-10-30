#!/usr/bin/env python3
"""Print an outline of files with line ranges, so an agent can read only the range it needs.

Why: reading a whole long file costs model tokens on every read. This script computes a map of
the file for zero model tokens; the agent then reads one range (Read with offset/limit, or
`sed -n A,Bp`). Outlines are generated on demand and never stored: stored line numbers go stale
with every edit, a fresh run is always correct.

Output per file: a header `path (N lines)`, then one line per entry: `  START-END  <label>`
(1-based, inclusive, indented by nesting). Label = heading text with its `#`s (Markdown) or the
trimmed declaration line (code, truncated to 100 chars).

Supported: Markdown (.md .markdown .mdx), Python (.py .pyi, exact via `ast`), Rust (.rs),
TypeScript/JavaScript (.ts .tsx .js .jsx .mjs .cjs), Go (.go). Markdown ranges are exact (section
ends before the next heading of the same or higher level). Rust, TS/JS and Go (and Python files
with a syntax error) use a line-based regex method whose ranges are APPROXIMATE: an entry ends
before the next entry at the same or lower indentation. Verify a range with a quick read.

Usage:
  python3 outline.py PATH [PATH...] [--depth N] [--max-entries N]

PATH is a file or a directory (recursed; hidden dirs, node_modules, target, .venv, venv,
__pycache__, dist and build are skipped). --depth N (default 3) limits Markdown heading level or
code nesting (top level = 1). --max-entries N (default 200, across all files) caps the output.
Exit code 2 if a path does not exist. Standard library only.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys

Entry = tuple[int, int, int, str]  # start, end, depth, label

EXT_KIND = {
    ".md": "md", ".markdown": "md", ".mdx": "md", ".py": "py", ".pyi": "py", ".rs": "rust",
    ".ts": "ts", ".tsx": "ts", ".js": "ts", ".jsx": "ts", ".mjs": "ts", ".cjs": "ts", ".go": "go",
}  # fmt: skip
SKIP_DIRS = {"node_modules", "target", ".venv", "venv", "__pycache__", "dist", "build"}
MAX_LABEL = 100
# Trailing lines that belong to the next entry (comments, attributes, decorators) or close a parent.
LEADING_NOISE = ("//", "/*", "*", "#", "@")
CLOSERS = {"}", "};", ")", ");", "]", "];", "})", "});"}

# One regex per line-based language; a match at the start of a line begins an entry.
PATTERNS = {
    "py": re.compile(
        r"\s*(?:async\s+def|def|class)\s+\w+"
    ),  # fallback for syntax errors
    "rust": re.compile(
        r"\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:async|unsafe|const)\s+)*(?:fn|struct|enum|trait|impl|mod)\b"
    ),
    "ts": re.compile(
        r"\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
        r"(?:(?:function\*?|class)\b|(?:interface|enum|const\s+enum)\s+\w|type\s+\w+\s*[<=]"
        r"|(?:const|let)\s+\w+\s*(?::[^=]+)?=\s*(?:async\s+)?(?:\(|function\b|\w+\s*=>))"
    ),
    "go": re.compile(r"\s*(?:func|type)\s+[\w(]"),
}
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*))?$")


def clip(text: str) -> str:
    """Trim a declaration and truncate it to MAX_LABEL characters."""
    text = text.strip()
    return text if len(text) <= MAX_LABEL else text[: MAX_LABEL - 1] + "…"


def indent_of(line: str) -> int:
    """Indentation width of a line, with tabs counted as 4 columns."""
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip())


def md_outline(lines: list[str], depth: int) -> list[Entry]:
    """ATX headings outside code fences (and YAML front matter), level <= depth."""
    heads: list[tuple[int, int, str]] = []  # line number, level, label
    fence = ""
    in_front = bool(lines) and lines[0].strip() == "---"
    for no, line in enumerate(lines, 1):
        if in_front:
            in_front = no == 1 or line.strip() != "---"
            continue
        m = FENCE.match(line)
        if fence:
            if (
                m
                and m[1][0] == fence[0]
                and len(m[1]) >= len(fence)
                and not m[2].strip()
            ):
                fence = ""
            continue
        if m:
            fence = m[1]
            continue
        h = HEADING.match(line)
        if h and len(h[1]) <= depth:
            text = re.sub(r"[ \t]+#+[ \t]*$", "", h[2] or "").strip()
            heads.append((no, len(h[1]), clip(f"{h[1]} {text}")))
    out: list[Entry] = []
    stack: list[tuple[int, int]] = []  # (level, index into out) of open sections
    for no, level, label in heads:
        while stack and stack[-1][0] >= level:
            _, i = stack.pop()
            out[i] = (out[i][0], no - 1, out[i][2], out[i][3])
        out.append((no, len(lines), len(stack) + 1, label))
        stack.append((level, len(out) - 1))
    return out


def py_outline(lines: list[str], depth: int) -> list[Entry]:
    """Classes and functions via ast (exact ranges); regex fallback on SyntaxError."""
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError):
        return regex_outline(lines, PATTERNS["py"], depth)
    out: list[Entry] = []
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def walk(node: ast.AST, level: int) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, defs):
                if level <= depth:
                    start = min(
                        [child.lineno] + [d.lineno for d in child.decorator_list]
                    )
                    end = child.end_lineno or child.lineno
                    out.append((start, end, level, clip(lines[child.lineno - 1])))
                    walk(child, level + 1)
            elif isinstance(child, (ast.stmt, ast.ExceptHandler, ast.match_case)):
                walk(child, level)

    walk(tree, 1)
    return sorted(out)


def trim_end(lines: list[str], start: int, end: int, indent: int) -> int:
    """Drop trailing blanks, comments/attributes of the next entry, and a parent's closing brace."""
    while end > start:
        raw = lines[end - 1]
        text = raw.strip()
        if (
            not text
            or text.startswith(LEADING_NOISE)
            or (text in CLOSERS and indent_of(raw) < indent)
        ):
            end -= 1
        else:
            break
    return end


def regex_outline(
    lines: list[str], pattern: re.Pattern[str], depth: int
) -> list[Entry]:
    """Line-based entries; an entry ends before the next one at the same or lower indentation."""
    found = [
        (no, indent_of(ln), ln) for no, ln in enumerate(lines, 1) if pattern.match(ln)
    ]
    ends = [len(lines)] * len(found)
    depths = [1] * len(found)
    stack: list[int] = []  # indexes of open entries
    for k, (no, ind, _) in enumerate(found):
        while stack and found[stack[-1]][1] >= ind:
            ends[stack.pop()] = no - 1
        depths[k] = len(stack) + 1
        stack.append(k)
    out: list[Entry] = []
    for (no, ind, line), end, level in zip(found, ends, depths):
        if level > depth:
            continue
        end = no if line.rstrip().endswith(";") else trim_end(lines, no, end, ind)
        out.append((no, end, level, clip(line)))
    return out


def analyze(path: str, depth: int) -> tuple[str, list[Entry]]:
    """Return the header line for a file and its entries."""
    with open(path, "rb") as fh:
        data = fh.read()
    if b"\0" in data[:8192]:
        return f"{path} ({data.count(10)} lines): binary, skipped", []
    lines = data.decode("utf-8", errors="replace").replace("\r", "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    head = f"{path} ({len(lines)} lines)"
    ext = os.path.splitext(path)[1].lower()
    kind = EXT_KIND.get(ext)
    if kind is None:
        return (
            f"{head}: no outline for {ext or 'files without extension'}; use grep -n",
            [],
        )
    if kind == "md":
        entries = md_outline(lines, depth)
    elif kind == "py":
        entries = py_outline(lines, depth)
    else:
        entries = regex_outline(lines, PATTERNS[kind], depth)
    return (head if entries else f"{head}: no entries"), entries


def collect(paths: list[str]) -> list[str]:
    """Expand directories into supported files; explicit files are kept as given."""
    files: list[str] = []
    for path in paths:
        if not os.path.isdir(path):
            files.append(path)
            continue
        for root, dirs, names in os.walk(path):
            dirs[:] = sorted(
                d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS
            )
            files += [
                os.path.join(root, n)
                for n in sorted(names)
                if os.path.splitext(n)[1].lower() in EXT_KIND
            ]
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print file outlines with line ranges.")
    ap.add_argument("paths", nargs="+", metavar="PATH", help="file or directory")
    ap.add_argument(
        "--depth", type=int, default=3, help="max heading level / nesting (default 3)"
    )
    ap.add_argument(
        "--max-entries",
        type=int,
        default=200,
        help="entry cap over all files (default 200)",
    )
    args = ap.parse_args(argv)
    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        for p in missing:
            print(f"outline.py: no such path: {p}", file=sys.stderr)
        return 2
    budget, more = args.max_entries, 0
    for path in collect(args.paths):
        header, entries = analyze(path, args.depth)
        if budget <= 0 and more:
            more += len(entries)
            continue
        print(header)
        for start, end, level, label in entries[: max(budget, 0)]:
            print(f"  {start}-{end}  {'  ' * (level - 1)}{label}")
        more += max(len(entries) - max(budget, 0), 0)
        budget -= len(entries)
    if more:
        print(f"… +{more} more entries; narrow the path or lower --depth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
