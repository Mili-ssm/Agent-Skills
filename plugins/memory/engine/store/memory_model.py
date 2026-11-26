"""The memory record as data: its fields, the vocabularies of its fields, and the checks on one-line text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime
    from pathlib import Path

KINDS = ("decision", "constraint", "pitfall", "lesson", "finding", "document", "state")
ORIGINS = ("web", "pipeline", "transcript")
REACHES = ("project", "general")
WEIGHTS = ("light", "medium", "strong")
# Distinct sessions that establish a transcript memory, by weight; a memory with no weight counts as medium.
SIGHTINGS_NEEDED = {"light": 1, "medium": 2, "strong": 3}
UNCONFIRMED_DAYS = 30
SESSION_PREFIX = "session "
OUTCOMES = ("worked", "failed", "seen")
TRIAGES = ("pending",)
PROJECT_KEY_LEN = 12
SHORT_DATE_LEN = 10  # characters of an ISO date
GLOBAL_MIN_PROJECTS = 2  # distinct projects that establish a global memory
SHORT_LIMIT = 120  # characters of the one-line form a lesson loads as at session start
TOPIC_LIMIT = 24
_TOPIC = re.compile(r"[a-z0-9][a-z0-9-]*( [a-z0-9][a-z0-9-]*)?")
STATUSES = ("active", "refuted", "superseded", "forgotten")
PROJECT_DIR = ".memory"
GLOBAL_DIR = "memories"
STORE_MARKER = "mem-store.yaml"


@dataclass
class Memory:
    scope: str
    path: Path
    handle: str
    kind: str
    claim: str
    created: datetime.date | None
    observed: int
    status: str
    context: str | None
    valid_until: datetime.date | None
    sources: list[str]
    body: str
    error: str | None
    last_observed: datetime.date | None = None
    distinct_from: list[str] = field(default_factory=list)
    promote: str | None = None
    refuted: datetime.date | None = None
    superseded_by: str | None = None
    origin: str | None = None  # "web", "pipeline" or "transcript"; None: written in a session
    reach: str | None = None  # "project" or "general": how far the lesson reaches
    weight: str | None = None  # "light", "medium" or "strong": how much it weighs
    owner_confirmed: datetime.date | None = (
        None  # the owner vouched for the lesson: it is established
    )
    triage: str | None = None  # "pending": a global record that left quarantine and awaits triage
    triage_reason: str | None = (
        None  # why a lesson is held at triage; meaningful only while triage is "pending"
    )
    released: datetime.date | None = None  # the day a global record left quarantine
    general: str | None = None  # handle of the global record a project record was generalized into
    short: str | None = (
        None  # the claim in one line of at most SHORT_LIMIT characters, as it loads at session start
    )
    short_by: str | None = (
        None  # "model": the short form was written by a model and the owner has not read it
    )
    topic: str | None = None  # one or two lowercase words that group rules
    from_repository: bool = False  # a repository commits the file: its owner_confirmed is not the reader's (mark_repository)
    load: str | None = (
        None  # "no": the owner turned this lesson's rule off; "index": only counted by topic
    )
    log: list[str] = field(
        default_factory=list
    )  # valid case entries "<date> session <id> <outcome>", in file order
    versions: list[str] = field(
        default_factory=list
    )  # valid entries "<date> <short form>", sorted by date
    reviewed: datetime.date | None = None  # the day the owner looked at a lesson that got worse
    reworded: datetime.date | None = (
        None  # the day the automatic step reworded the short form (once, for good)
    )
    reword_failed: datetime.date | None = (
        None  # the date of the version the automatic step gave up on
    )


class FieldTypeError(ValueError):
    """A frontmatter value of the wrong type; a ValueError so every caller that catches one still catches it."""


def valid_short(text) -> bool:
    return (
        isinstance(text, str)
        and bool(text.strip())
        and text == text.strip()
        and len(text) <= SHORT_LIMIT
        and len(text.splitlines()) == 1
    )


TRIAGE_REASON_LIMIT = 200


def valid_triage_reason(text) -> bool:
    return (
        isinstance(text, str)
        and bool(text.strip())
        and text == text.strip()
        and len(text) <= TRIAGE_REASON_LIMIT
        and len(text.splitlines()) == 1
    )


def valid_topic(text) -> bool:
    return (
        isinstance(text, str)
        and len(text) <= TOPIC_LIMIT
        and text != "other"
        and _TOPIC.fullmatch(text) is not None
    )


def slug_of(claim: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", claim).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", ascii_text.lower())[:8]
    slug = "-".join(words)[:60].strip("-")
    return slug or "memory"


def is_live(memory: Memory, today: datetime.date) -> bool:
    return (
        memory.error is None
        and memory.status == "active"
        and (memory.valid_until is None or memory.valid_until >= today)
    )
