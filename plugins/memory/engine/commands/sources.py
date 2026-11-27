"""The `fetch-sources` and `import` handlers (A5, ADR 0028): downloads, HTML and PDF text extraction, and the store import.

`mem.py` imports it at start-up like every command module (a local import is forbidden by Ruff; ADR 0028), so
`http.client` and `html.parser` load on every run, about 18 ms."""

from __future__ import annotations

import collections
import contextlib
import html.parser
import http.client
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from core import safe_io
from memories import records
from notes import check as check_rules
from notes import index as index_files
from notes import note as note_files
from research import checks as research_checks

from commands import common, edit, import_recovery

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from notes import fields as note_fields


FETCH_TIMEOUT = 30  # seconds per socket operation: slow source servers answer late


FETCH_DEADLINE = 120  # seconds for one download, all redirects together


FETCH_PAUSE = 1.0


FETCH_MAX_BYTES = 50 * 1024 * 1024  # larger sources stay online only (C-14)


_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


_CONTENT_EXT = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/plain": "txt",
}


_SUFFIX_EXT = {".pdf": "pdf", ".html": "html", ".htm": "html", ".txt": "txt"}


def _download(url: str) -> tuple[bytes, str]:
    """(body, Content-Type) of a URL, redirects followed. Goes through the address-checked transport of
    `research_checks`: a host that resolves to a non-public address, at any hop, is refused."""
    try:
        return research_checks.fetch_raw(
            url,
            lambda _: FETCH_MAX_BYTES,
            over="fail",
            headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
            deadline=FETCH_DEADLINE,
            max_redirects=10,
            timeout=FETCH_TIMEOUT,
        )
    except research_checks.FetchError as exc:
        raise ValueError(str(exc)) from exc


def _source_extension(url: str, content_type: str) -> str:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in _CONTENT_EXT:
        return _CONTENT_EXT[mime]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return _SUFFIX_EXT.get(suffix, "html")


_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "svg",
    "title",
    "select",
    "button",
    "option",
}


_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "section",
    "article",
    "blockquote",
    "pre",
}


_CHARSET = re.compile(rb"""charset\s*=\s*["']?([\w.:-]+)""", re.IGNORECASE)


MIN_TEXT_WORDS = (
    200  # a shorter conversion is a shell page (script-rendered, paywalled), not a source text
)


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip: list[str] = []
        self.main = 0  # open article/main elements: a header inside one is part of the text

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.main += tag in {"article", "main"}
        if tag in _SKIP_TAGS and not (tag == "header" and self.main):
            self.skip.append(tag)
        if tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        self.main = max(0, self.main - (tag in {"article", "main"}))
        if tag in self.skip:
            del self.skip[len(self.skip) - 1 - self.skip[::-1].index(tag) :]
        if tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(
                re.sub(r"\s+", " ", data)
            )  # a newline inside the markup is not a line break


def html_to_text(data: bytes) -> str:
    """Plain text of an HTML document: no script, style or page chrome; one line per block, spaces collapsed.

    Charset from a `<meta>` in the first 4,096 bytes, else UTF-8, latin-1 when that fails to decode."""
    match = _CHARSET.search(data[:4096])
    try:
        text = data.decode(match.group(1).decode("ascii") if match else "utf-8")
    except (UnicodeDecodeError, LookupError):
        text = data.decode("latin-1")
    parser = _TextExtractor()
    parser.feed(text)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.out).split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def _literature_notes(
    root: Path, paths: list[str] | None
) -> tuple[list[note_files.Note], list[str]]:
    """The literature notes to work on (all, or the given paths) and a `failed` line per path that is not one."""
    notes = [n for n in note_files.discover_notes(root) if n.type == "literature"]
    if not paths:
        return notes, []
    by_rel = {n.rel: n for n in notes}
    return (
        [by_rel[p] for p in paths if p in by_rel],
        [f"failed {p}: not a literature note" for p in paths if p not in by_rel],
    )


def _txt_files(folder: Path) -> list[Path]:
    """Every `.txt` entry of a source folder (any case, symlinks too): the hub never writes `source.txt` beside one."""
    return [p for p in folder.iterdir() if p.suffix.lower() == ".txt"]


def _largest_copy(folder: Path, *patterns: str) -> Path | None:
    """The largest regular file of the folder matching a pattern (ties by name), symlinks left out."""
    found = [p for pat in patterns for p in folder.glob(pat) if p.is_file() and not p.is_symlink()]
    return max(found, key=lambda p: (p.stat().st_size, p.name), default=None)


def _text_from_page(folder: Path, page: Path) -> str | None:
    """Write `source.txt` from an HTML copy: None when written, else the reason it is too short."""
    text = html_to_text(page.read_bytes())
    if len(text.split()) >= MIN_TEXT_WORDS:
        safe_io.replace_file(folder / "source.txt", text.encode("utf-8"))
        return None
    return f"page has under {MIN_TEXT_WORDS} words of text"


def _text_from_pdf(folder: Path, pdf: Path) -> str | None:
    """Write `source.txt` from a PDF copy with `pdftotext`: None when written, else the reason."""
    if not shutil.which("pdftotext"):
        return "pdftotext is not installed"
    try:
        done = subprocess.run(
            ["pdftotext", str(pdf), str(folder / "source.txt")],
            check=False,
            timeout=60,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"pdftotext failed: {exc}"
    if done.returncode == 0:
        return None
    (folder / "source.txt").unlink(missing_ok=True)
    return f"pdftotext failed with exit {done.returncode}"


def _write_text_copy(folder: Path) -> str | None:
    """Write `source.txt` from the folder's largest HTML copy, else its largest PDF; None when written, else the reason."""
    if _txt_files(folder):
        return "the folder already holds a .txt"
    reason = "no HTML or PDF copy"
    if (page := _largest_copy(folder, "*.html", "*.htm")) is not None:
        reason = _text_from_page(folder, page)
        if reason is None:
            return None
    if (pdf := _largest_copy(folder, "*.pdf")) is None:
        return reason
    return _text_from_pdf(folder, pdf)


def _folder_text_status(folder: Path) -> tuple[str | None, int] | None:
    """(reason it has no text, words of its text) for a source folder after trying to build `source.txt`;
    None when the folder already held a `.txt`."""
    if folder.is_symlink():
        return f"{common.SOURCES_DIR}/{folder.name} is a symlink", 0
    if _txt_files(folder):
        return None
    reason = _write_text_copy(folder)
    if reason is not None:
        return reason, 0
    return None, len((folder / "source.txt").read_text(encoding="utf-8").split())


def build_missing_texts(root: Path, paths: list[str] | None = None) -> tuple[list[str], bool]:
    """`fetch-sources --text-only`: write `source.txt` in each `.sources/<stem>/` folder that holds no `.txt`.

    Never downloads, never touches a folder with any `.txt` (hand-made texts win in `passages`) and skips a
    folder that is a symlink. Returns (output lines, False when a PATH is not a literature note)."""
    notes, lines = _literature_notes(root, paths)
    bad = bool(lines)
    written = without = had = 0
    for note in notes:
        folder = root / common.SOURCES_DIR / note.path.stem
        if not folder.is_dir():
            continue
        try:
            status = _folder_text_status(folder)
        except OSError as exc:
            status = (str(exc), 0)
        if status is None:
            had += 1
            continue
        reason, words = status
        if reason is None:
            lines.append(f"text {note.rel} ({words} words)")
            written += 1
        else:
            lines.append(f"no text {note.rel}: {reason}")
            without += 1
    lines.append(f"text written {written}, without text {without}, already had text {had}")
    return lines, not bad


@dataclass(frozen=True)
class _FetchOutcome:
    """What `fetch_sources` did with one note: the counter to bump, the output line, whether it hit the network."""

    counter: str
    line: str
    requested: bool


def _fetch_refusal(note: note_files.Note, folder: Path, force: bool) -> tuple[str, str] | None:
    """(counter, output line) when a note's folder rules out a download: a symlink or a cached copy."""
    if folder.is_symlink():
        return "failed", f"failed {note.rel}: {common.SOURCES_DIR}/{folder.name} is a symlink"
    if not force and folder.is_dir() and any(not p.is_symlink() for p in folder.iterdir()):
        return "skipped", f"skipped {note.rel} (already cached)"
    return None


def _http_url(note: note_files.Note) -> str | None:
    """The note's `url` when it is a string starting with http:// or https://."""
    url = note.meta.get("url") if isinstance(note.meta, dict) else None
    if isinstance(url, str) and urllib.parse.urlparse(url).scheme in {"http", "https"}:
        return url
    return None


def _download_source(folder: Path, url: str) -> str:
    """Download `url` into `folder` as `source.<ext>`, dropping other copies of `source.*`; the extension."""
    data, content_type = _download(url)
    ext = _source_extension(url, content_type)
    folder.mkdir(parents=True, exist_ok=True)
    if ext == "txt" and any(p.name != "source.txt" for p in _txt_files(folder)):
        raise ValueError("the folder already holds a .txt")
    for old in folder.glob("source.*"):  # --force: drop copies of another type or a stale text
        old.unlink()
    safe_io.replace_file(folder / f"source.{ext}", data)
    return ext


def _fetched_line(note: note_files.Note, folder: Path, ext: str) -> str:
    """The output line of a fetched note; an HTML copy is converted to text, and a failure noted."""
    if ext == "pdf" and shutil.which("pdftotext") and not _txt_files(folder):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["pdftotext", str(folder / "source.pdf"), str(folder / "source.txt")],
                check=False,
                timeout=60,
                capture_output=True,
            )
    line = f"fetched {note.rel}"
    if ext != "html":
        return line
    try:
        reason = _write_text_copy(folder)
    except OSError as exc:
        reason = str(exc)
    return line if reason is None else f"{line} (no text: {reason})"


def _fetch_one(note: note_files.Note, folder: Path, force: bool, pause: bool) -> _FetchOutcome:
    """Download one note's source, sleeping first when `pause` (a request went out before)."""
    if (refusal := _fetch_refusal(note, folder, force)) is not None:
        return _FetchOutcome(*refusal, requested=False)
    url = _http_url(note)
    if url is None:
        line = f"failed {note.rel}: url must start with http:// or https://"
        return _FetchOutcome("failed", line, requested=False)
    if pause:
        time.sleep(FETCH_PAUSE)
    try:
        ext = _download_source(folder, url)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return _FetchOutcome("failed", f"failed {note.rel}: {exc}", requested=True)
    return _FetchOutcome("fetched", _fetched_line(note, folder, ext), requested=True)


def fetch_sources(
    root: Path, paths: list[str] | None = None, *, force: bool = False
) -> tuple[list[str], bool]:
    """Download each literature note's `url` into .sources/<note-stem>/; returns (output lines, all ok)."""
    notes, lines = _literature_notes(root, paths)
    counts = {"fetched": 0, "skipped": 0, "failed": len(lines)}
    requested = False
    for note in notes:
        outcome = _fetch_one(note, root / common.SOURCES_DIR / note.path.stem, force, requested)
        lines.append(outcome.line)
        counts[outcome.counter] += 1
        requested = requested or outcome.requested
    lines.append(
        f"fetched {counts['fetched']}, skipped {counts['skipped']}, failed {counts['failed']}"
    )
    return lines, counts["failed"] == 0


_IMPORT_FOLDERS = ("literature", "knowledge", "research")


# what an investigation's documents are made of: the text and the figures it embeds
_IMPORT_DOCUMENTS = {".md", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}


def _import_refused(src: Path, path: Path, skipped: list[str]) -> bool:
    """Whether the path is a symlink or under one; its source-relative path then goes to `skipped`."""
    try:
        safe_io.refuse_symlink_chain(src, path)
    except safe_io.UnsafePath:
        skipped.append(path.relative_to(src).as_posix())
        return True
    return False


def _import_subdirs(
    src: Path, here: str, dirs: list[str], top: str, skipped: list[str]
) -> list[str]:
    """The folders of `here` an import descends into, sorted: no hidden one (but under `.sources`), no cache, no symlink."""
    kept = sorted(d for d in dirs if d == d.lstrip(".") or top == ".sources")
    return [
        d for d in kept if d != "__pycache__" and not _import_refused(src, Path(here) / d, skipped)
    ]


def _import_keeps(rel: Path, top: str, research_data: bool) -> bool:
    """Whether an import lists the file: not a hidden one (but under `.sources`), not an investigation's data or
    code unless asked, not a generated listing."""
    name = rel.name
    if top != ".sources" and name.startswith("."):
        return False
    # An investigation's data and code stay where the experiments live; its documents are the memory.
    if (
        top == "research"
        and not research_data
        and Path(name).suffix.lower() not in _IMPORT_DOCUMENTS
    ):
        return False
    # the generated listings: folder/README.md and, for literature and knowledge, folder/topic/README.md
    return not (
        name == "README.md"
        and top != ".sources"
        and len(rel.parts) in ((2,) if top == "research" else (2, 3))
    )


def _import_listed(src: Path, top: str, research_data: bool, skipped: list[str]) -> list[str]:
    """The source-relative paths of one top folder an import lists."""
    found: list[str] = []
    for here, dirs, names in os.walk(src / top):
        dirs[:] = _import_subdirs(src, here, dirs, top, skipped)
        for name in names:
            if _import_refused(src, Path(here) / name, skipped):
                continue
            rel = (Path(here) / name).relative_to(src)
            if _import_keeps(rel, top, research_data):
                found.append(rel.as_posix())
    return found


def _import_files(
    src: Path, with_sources: bool, research_data: bool = False, skipped: list[str] | None = None
) -> list[str]:
    """Source-relative paths to import, sorted. The source is only listed and read, never written.
    A symlink, or anything under one, is never listed: its source-relative path goes to `skipped`."""
    skipped = skipped if skipped is not None else []
    found: list[str] = []
    roots = [*_IMPORT_FOLDERS, *([".sources"] if with_sources else [])]
    for top in roots:
        if (src / top).is_symlink():
            _import_refused(src, src / top, skipped)
            continue
        found += _import_listed(src, top, research_data, skipped)
    return sorted(found)


def _note_kind(rel: str) -> str | None:
    parts = rel.split("/")
    if (
        parts[0] in {"literature", "knowledge"}
        and len(parts) == edit._NOTE_PATH_PARTS
        and parts[2].endswith(".md")
        and parts[2] != "README.md"
    ):
        return parts[0]
    if parts[0] == "research" and len(parts) == edit._NOTE_PATH_PARTS and parts[2] == "README.md":
        return "research"
    return None


def _import_text(src: Path, rel: str) -> str | None:
    """The text of an imported file; None when it cannot be read or is binary (a NUL byte)."""
    try:
        raw = (src / rel).read_bytes()
    except OSError:
        return None
    if raw[:2] in {b"\xff\xfe", b"\xfe\xff"}:  # a BOM-marked UTF-16 file holds NULs but is text
        return raw.decode("utf-16", errors="ignore")
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="ignore")


def _import_hard_terms() -> list[records.Term]:
    """The hard terms of the forbidden list; none when it cannot be read."""
    try:
        return [t for t in records.read_terms(os.environ) if not t.soft]
    except records.ForbiddenListError:
        return []


def _flag_import(src: Path, files: Sequence[str]) -> list[str]:
    """Imported text files whose text matches a secret pattern or a hard term (a file with a NUL byte is binary: skipped)."""
    terms = _import_hard_terms()
    flagged = []
    for rel in files:
        text = _import_text(src, rel)
        if text is None:
            continue
        if records.secret_in([text]) is not None or (
            terms and any(not t.soft for t in records.term_hits([text], os.environ))
        ):
            flagged.append(rel)
    return flagged


def _union_topics(src: Path, dest: Path) -> tuple[list[str], list[str], str]:
    """(ids added, ids kept as they were, text to append to the destination's topics.yaml)."""
    path = src / "topics.yaml"
    if path.is_symlink() or not path.is_file():
        return [], [], ""
    try:
        theirs = note_files.load_yaml(note_files._read_text(path))
    except (yaml.YAMLError, note_files.FrontmatterError) as exc:
        raise note_files.FrontmatterError(f"the source's topics.yaml is unusable ({exc})") from exc
    if theirs is None:
        theirs = {}
    if not isinstance(theirs, dict):
        raise note_files.FrontmatterError("the source's topics.yaml must be a mapping of topic ids")
    mine = note_files.load_topics(dest)
    added = [t for t in theirs if t not in mine]
    kept = [t for t in theirs if t in mine and theirs[t] != mine[t]]
    # one `id: {flow entry}` line each: the flow dump of {id: entry} without its outer braces
    lines = "".join(
        yaml.safe_dump(
            {t: theirs[t]}, default_flow_style=True, width=10**6, allow_unicode=True
        ).strip()[1:-1]
        + "\n"
        for t in added
    )
    return [str(t) for t in added], [str(t) for t in kept], lines


@dataclass(frozen=True)
class _ImportPlan:
    """What an import does: the files it lists, those it copies, finds identical, finds in conflict and skips, the
    notes by kind, and the topics it adds and keeps (with the text it appends to the destination's topics.yaml)."""

    src: Path
    dest: Path
    files: list[str]
    todo: list[str]
    same: list[str]
    conflicts: list[str]
    skipped: list[str]
    kinds: collections.Counter[str]
    added: list[str]
    kept: list[str]
    topic_text: str


def _import_source(args: argparse.Namespace, dest: Path) -> Path | int:
    """The resolved source folder; 2 after a message on stderr when it is no folder or overlaps the store."""
    src = Path(args.source).expanduser()
    if not src.is_dir():
        print(f"mem: the source is not a folder: {src}", file=sys.stderr)
        return 2
    src = src.resolve()
    if records.inside(src, dest) or records.inside(dest, src):
        print(
            "mem: the source and the store must be separate folders, neither inside the other.",
            file=sys.stderr,
        )
        return 2
    return src


def _import_verdict(src: Path, dest: Path, rel: str, overwrite: bool) -> str:
    """What an import does with one file: `skipped` (a symlink in the store), `same`, `conflict` or `copy`."""
    target = dest / rel
    try:
        safe_io.refuse_symlink_chain(dest, target)
    except safe_io.UnsafePath:
        return "skipped"
    data = (src / rel).read_bytes()
    if target.is_file():
        if target.read_bytes() == data:
            return "same"
        if not overwrite:
            return "conflict"
    return "copy"


def _import_plan(
    args: argparse.Namespace, src: Path, dest: Path, topics: tuple[list[str], list[str], str]
) -> _ImportPlan:
    """List the source and sort its files by what an import does with them."""
    skipped: list[str] = []
    if (src / "topics.yaml").is_symlink():
        skipped.append("topics.yaml")
    files = _import_files(src, args.with_sources, args.research_data, skipped)
    groups: dict[str, list[str]] = {"copy": [], "same": [], "conflict": [], "skipped": skipped}
    for rel in files:
        groups[_import_verdict(src, dest, rel, args.overwrite)].append(rel)
    kinds = collections.Counter(k for k in map(_note_kind, files) if k)
    added, kept, topic_text = topics
    return _ImportPlan(
        src,
        dest,
        files,
        groups["copy"],
        groups["same"],
        groups["conflict"],
        skipped,
        kinds,
        added,
        kept,
        topic_text,
    )


def _import_topics_bytes(root: Path, topic_text: str) -> bytes:
    path = root / "topics.yaml"
    safe_io.refuse_symlink_chain(root, path)
    current = path.read_text(encoding="utf-8")
    return (current + ("" if current.endswith("\n") or not current else "\n") + topic_text).encode()


def _import_log_bytes(root: Path, planned: dict[Path, bytes]) -> bytes | None:
    changes = {}
    for path, replacement in planned.items():
        try:
            before = path.read_bytes()
            before.decode("utf-8")
        except (FileNotFoundError, UnicodeDecodeError):
            continue
        changes[path] = (before, common._sha(replacement))
    if not changes:
        return None
    log = root / records.CURATION_LOG
    safe_io.refuse_symlink_chain(root, log)
    current = log.read_bytes() if log.exists() else b""
    if current and not current.endswith(b"\n"):
        current += b"\n"
    return current + common._group_entries(root, changes, "import").encode()


def _import_payloads(plan: _ImportPlan, root: Path, log: bool) -> dict[Path, bytes]:
    planned = {}
    for rel in plan.todo:
        if rel.startswith(".sources/") and not log:
            continue
        target = root / rel
        source = plan.src / rel
        safe_io.refuse_symlink_chain(root, target)
        safe_io.refuse_symlink_chain(plan.src, source)
        planned[target] = source.read_bytes()
    if log and (history := _import_log_bytes(root, planned)) is not None:
        planned[root / records.CURATION_LOG] = history
    if plan.topic_text:
        planned[root / "topics.yaml"] = _import_topics_bytes(root, plan.topic_text)
    return planned


def _import_apply(plan: _ImportPlan, root: Path, log: bool) -> None:
    """Publish rollback data before writing a real import. The index is reconstructible from the store."""
    planned = _import_payloads(plan, root, log)
    if log and planned:
        import_recovery.publish(root, planned)
    for target, replacement in planned.items():
        safe_io.refuse_symlink_chain(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        safe_io.replace_file(target, replacement)
    index_files.apply_index(root)
    if log and planned:
        import_recovery.clear(root)


def _import_run(plan: _ImportPlan, dry_run: bool) -> list[note_fields.Problem]:
    """Apply the plan, or a dry run of it on a scratch copy of the store; returns the check problems afterwards."""
    if dry_run:
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "store"
            shutil.copytree(plan.dest, scratch, ignore=shutil.ignore_patterns(".*"))
            _import_apply(plan, scratch, False)
            return check_rules.check(scratch)
    _import_apply(plan, plan.dest, True)
    return check_rules.check(plan.dest)


def _import_report(
    plan: _ImportPlan, problems: list[note_fields.Problem], flagged: list[str]
) -> None:
    print(f"source: {plan.src}")
    print(f"destination: {plan.dest}")
    print(
        f"notes: {plan.kinds['literature']} literature, {plan.kinds['knowledge']} knowledge, {plan.kinds['research']} research"
    )
    print(
        f"files: {len(plan.todo)} copied, {len(plan.same)} identical, {len(plan.conflicts)} conflicts"
    )
    print(f"topics: {len(plan.added)} added, {len(plan.kept)} kept as they were")
    print(f"check: {len(problems)} problems")
    print(f"flagged: {len(flagged)} files")
    for header, items in (
        ("skipped symlinks:", sorted(plan.skipped)),
        ("conflicts:", plan.conflicts),
        ("topics kept:", plan.kept),
        ("check problems (first 20):", [str(p) for p in problems[:20]]),
        ("flagged:", flagged),
    ):
        if items:
            print(header)
            for item in items:
                print(f"  {item}")


def _run_import(args: argparse.Namespace, src: Path, dest: Path) -> int:
    if import_recovery.pending(dest):
        raise OSError("an import was interrupted. Run mem import-recover before retrying")
    plan = _import_plan(args, src, dest, _union_topics(src, dest))
    flagged = _flag_import(src, plan.files)
    problems = _import_run(plan, args.dry_run)
    _import_report(plan, problems, flagged)
    common.log_usage(
        dest, {"cmd": "import", "copied": len(plan.todo), "conflicts": len(plan.conflicts)}
    )
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    dest = args.root.resolve()
    src = _import_source(args, dest)
    if isinstance(src, int):
        return src
    try:
        with contextlib.nullcontext() if args.dry_run else import_recovery.locked(dest):
            return _run_import(args, src, dest)
    except (note_files.FrontmatterError, OSError) as exc:
        print(f"mem: import failed: {exc}", file=sys.stderr)
        return 2


def _recover_import(root: Path) -> bool:
    if not import_recovery.pending(root):
        return False
    import_recovery.rollback(root)
    index_files.apply_index(root)
    import_recovery.clear(root)
    return True


def cmd_import_recover(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    try:
        with import_recovery.locked(root):
            recovered = _recover_import(root)
    except (OSError, TypeError, ValueError, note_files.FrontmatterError) as exc:
        print(f"mem: import recovery failed: {exc}", file=sys.stderr)
        return 2
    print("Interrupted import rolled back." if recovered else "No interrupted import.")
    return 0


def cmd_fetch_sources(args: argparse.Namespace) -> int:
    if args.text_only:
        lines, ok = build_missing_texts(args.root, args.paths)
    else:
        lines, ok = fetch_sources(args.root, args.paths, force=args.force)
    print("\n".join(lines))
    return 0 if ok else 1
