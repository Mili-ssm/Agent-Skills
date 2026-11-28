"""Find synthesis parts with enough notes on a more specific topic to split."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from notes.note import ancestors

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syntheses.document import Synthesis

    from notes.note import Note


MIN_NOTES = 5


@dataclass(frozen=True)
class SplitCandidate:
    part: str
    topic: str
    notes: tuple[str, ...]


def find_candidates(
    notes: Iterable[Note], syntheses: Iterable[Synthesis], topics: Mapping[str, dict]
) -> list[SplitCandidate]:
    """Report strict descendant topics named by five distinct live notes on an existing part."""
    parts = {
        f"{syn.handle}#{section.handle}": syn
        for syn in syntheses
        if syn.error is None
        for section in syn.parts
    }
    known = dict(topics)
    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for note in notes:
        part = _attached_part(note, parts)
        if part is None:
            continue
        tags = note.meta["topics"]
        declared = set(parts[part].topics)
        for topic in tags:
            if (
                isinstance(topic, str)
                and topic in topics
                and topic not in declared
                and declared.intersection(ancestors(known, topic))
            ):
                groups[part, topic].add(note.rel)
    return [
        SplitCandidate(part, topic, tuple(sorted(paths)))
        for (part, topic), paths in sorted(groups.items())
        if len(paths) >= MIN_NOTES
    ]


def _attached_part(note: Note, parts: dict[str, Synthesis]) -> str | None:
    if note.type != "knowledge" or note.error is not None or not isinstance(note.meta, dict):
        return None
    part = note.meta.get("part_of")
    if (
        note.meta.get("superseded_by") is not None
        or not isinstance(part, str)
        or part not in parts
        or not isinstance(note.meta.get("topics"), list)
    ):
        return None
    return part
