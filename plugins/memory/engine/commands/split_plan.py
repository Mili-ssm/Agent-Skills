"""Prepare an inspectable synthesis split without changing the store."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core import safe_io
from memories import terms
from notes import note as note_files
from notes import split_candidates
from syntheses import document, units
from syntheses import edit as syn_edit
from syntheses.split_conservation import check_conservation

from commands import common, edit, synthesis

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date
    from pathlib import Path


@dataclass(frozen=True)
class SplitProposal:
    part: str
    topic: str
    parent_text: str
    child_heading: str
    child_text: str
    expected: Mapping[str, str | None]


@dataclass(frozen=True)
class SplitPlan:
    original: str
    parent_text: str
    child_text: str
    destination: str
    moves: tuple[str, ...]
    conflicts: tuple[str, ...]
    changes: dict[Path, tuple[bytes | None, bytes | None]]


def _safe(root: Path, path: Path) -> Path:
    safe_io.refuse_symlink_chain(root, path)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"path outside store: {path}") from None
    return path


def _resolve(root: Path, part: str, topic: str):  # ruff: ignore[complex-structure]
    syn, sec = common._section_ref(root, part)
    if sec.handle == document.SUMMARY or sum(s.handle == sec.handle for s in syn.sections) != 1:
        raise ValueError("part must name a unique non-summary section")
    topics = note_files.load_topics(root)
    notes = note_files.discover_notes(root)
    syntheses = document.load(root / document.SYNTHESES_DIR)
    if any(s.error for s in syntheses):
        raise ValueError("cannot resolve destinations with an invalid synthesis")
    candidates = split_candidates.find_candidates(notes, syntheses, topics)
    name = f"{syn.handle}#{sec.handle}"
    candidate = next((c for c in candidates if c.part == name and c.topic == topic), None)
    if candidate is None:
        raise ValueError("no such split candidate")
    conflicts = tuple(
        sorted(
            c.topic
            for c in candidates
            if c.part == name and c.topic != topic and set(c.notes) & set(candidate.notes)
        )
    )
    destinations = [s for s in syntheses if topic in s.topics]
    if len(destinations) > 1:
        raise ValueError("multiple syntheses declare the destination topic")
    path = (
        destinations[0].path
        if destinations
        else document.path_of(root / document.SYNTHESES_DIR, topic)
    )
    if path is None or path == syn.path or (not destinations and path.exists()):
        raise ValueError("invalid or occupied destination")
    for p in (syn.path, path, root / "topics.yaml"):
        _safe(root, p)
    return syn, sec, candidate, conflicts, destinations[0] if destinations else None, path


def _snapshot(root: Path, path: Path, syn, sec) -> dict[str, str | None]:
    # Recompute membership and destination before comparing this bounded snapshot.
    members = synthesis._part_of_notes(root, f"{syn.handle}#{sec.handle}")
    paths = {root / "topics.yaml", syn.path, path, *(p for p, _ in members)}
    for p in paths:
        _safe(root, p)
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        if p.exists()
        else None
        for p in sorted(paths)
    }


def candidate_input(root: Path, part: str, topic: str) -> dict[str, object]:
    safe_io.refuse_symlink_chain(root, root)
    root = root.resolve()
    syn, sec, candidate, conflicts, dest, path = _resolve(root, part, topic)
    expected = _snapshot(root, path, syn, sec)
    return {
        "proposal": {
            "part": part,
            "topic": topic,
            "parent_text": sec.text,
            "child_heading": topic,
            "child_text": "",
            "expected": expected,
        },
        "original": sec.text,
        "destination": dest.handle if dest else topic,
        "moves": list(candidate.notes),
        "conflicts": list(conflicts),
    }


def _link(text: str, label: str, target: str) -> str:
    line = document._sources_line(text)
    link = f"See also: [{label}]({target})"
    if line:
        index = text.rfind(line)
        return text[:index].rstrip() + "\n\n" + link + "\n\n" + text[index:]
    return text.rstrip() + "\n\n" + link


def prepare_split(  # ruff: ignore[complex-structure, too-many-locals]
    root: Path, proposal: SplitProposal, today: date, env: Mapping[str, str]
) -> SplitPlan:
    safe_io.refuse_symlink_chain(root, root)
    root = root.resolve()
    syn, sec, candidate, conflicts, dest, path = _resolve(root, proposal.part, proposal.topic)
    if dict(proposal.expected) != _snapshot(root, path, syn, sec):
        raise ValueError("split snapshot changed")
    heading = " ".join(proposal.child_heading.split())
    handle = document.section_handle(heading)
    if (
        not handle
        or handle == document.SUMMARY
        or (dest and any(s.handle == handle for s in dest.sections))
    ):
        raise ValueError("invalid or colliding child section")
    parent, child = proposal.parent_text.strip("\n"), proposal.child_text.strip("\n")
    if not parent.strip() or not child.strip():
        raise ValueError("both part bodies are required")
    syn_edit._check_body(parent)
    syn_edit._check_body(child)
    if problems := document.validate_section(sec.text, root):
        raise ValueError("invalid original part: " + "; ".join(problems))
    texts = [heading, parent, child]
    if terms.secret_in(texts) or terms.term_hits(texts, env, "synthesis"):
        raise ValueError("secret or forbidden term in proposal")
    if problems := check_conservation(root, sec.text, parent, child):
        raise ValueError("; ".join(problems))
    base = root / document.SYNTHESES_DIR
    sources = {
        document._resolved(base, t) for t in (document._links(document._sources_line(child) or ""))
    }
    if any((root / rel).resolve() not in sources for rel in candidate.notes):
        raise ValueError("child sources must support every moved note")
    destination = f"{path.stem}#{handle}"
    parent = _link(parent, heading, f"{path.name}#{handle}")
    child = _link(child, sec.heading, f"{syn.path.name}#{sec.handle}")
    for body in (parent, child):
        if problems := document.validate_section(body, root):
            raise ValueError("; ".join(problems))
    parent_old = syn.path.read_bytes()
    parent_file = edit._lf(parent_old.decode("utf-8"), syn.path.name)
    parent_new = syn_edit.bumped(syn_edit.apply_part_text(parent_file, sec.handle, parent), today)
    if dest:
        old = path.read_bytes()
        edit._lf(old.decode("utf-8"), path.name)
        _, child_new, _ = syn_edit.prepare_add(path, heading, child, today)
    else:
        old = None
        template = (common._TEMPLATES / "synthesis.md").read_text(encoding="utf-8")
        child_new = syn_edit.render_new(
            template, title=heading, topics=[proposal.topic], summary=heading, today=today
        )
        child_new = child_new.rstrip() + f"\n\n## {heading}\n\n{child}\n"
    changes = {syn.path: (parent_old, parent_new.encode()), path: (old, child_new.encode())}
    changes.update(synthesis._refs_note_edits(root, syn.handle, sec.handle, (sec.text, parent)))
    for rel in candidate.notes:
        note_path = _safe(root, root / rel)
        original = note_path.read_bytes()
        text = edit._lf(original.decode("utf-8"), rel)
        stamp = units.note_fingerprint(child, common._note_target(rel))
        changes[note_path] = (original, edit._set_part_of(text, destination, stamp).encode())
    return SplitPlan(sec.text, parent, child, destination, candidate.notes, conflicts, changes)
