"""Reading a memory: a Markdown file with YAML frontmatter becomes a Memory, tolerating what a hand edit may leave."""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import replace
from typing import TYPE_CHECKING

from store.memory_model import (
    KINDS,
    ORIGINS,
    REACHES,
    STATUSES,
    TRIAGES,
    WEIGHTS,
    FieldTypeError,
    Memory,
    valid_short,
    valid_topic,
    valid_triage_reason,
)
from store.notes import safe_load
from store.sightings import (
    _version,
    case,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


logger = logging.getLogger(__name__)


def _date(value, name: str) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        raise FieldTypeError(f"{name} must be a date")
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        return datetime.date.fromisoformat(value)
    raise FieldTypeError(f"{name} must be an ISO date")


def _split(text: str) -> tuple[dict, str]:
    m = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
    if not m:
        raise ValueError("no YAML frontmatter")
    meta = safe_load(m.group(1))
    if not isinstance(meta, dict):
        raise FieldTypeError("frontmatter is not a mapping")
    return meta, text[m.end() :]


def _checked_kind(meta: dict) -> str:
    kind = meta.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    return kind


def _checked_claim(meta: dict) -> str:
    claim = meta.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("claim is missing")
    return claim


def _checked_observed(meta: dict) -> int:
    observed = meta.get("observed", 1)
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 1:
        raise ValueError("observed must be an integer of at least 1")
    return observed


def _checked_status(meta: dict) -> str:
    status = meta.get("status", "active")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return status


def _checked_context(meta: dict) -> str | None:
    context = meta.get("context")
    if context is not None and not isinstance(context, str):
        raise ValueError("context must be a string")
    return context


def _checked_sources(meta: dict) -> list[str]:
    sources = meta.get("sources") or []
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise ValueError("sources must be a list of strings")
    return list(sources)


def _required_fields(meta: dict) -> dict:
    """The fields a memory needs, each checked in this order; the first bad one raises ValueError."""
    return {
        "kind": _checked_kind(meta),
        "claim": _checked_claim(meta).strip(),
        "observed": _checked_observed(meta),
        "status": _checked_status(meta),
        "context": _checked_context(meta),
        "sources": _checked_sources(meta),
    }


# a bad value reads as absent: only curation reads these dates, and one must not hide the memory
_LENIENT_DATES = (
    "last_observed",
    "refuted",
    "reviewed",
    "reworded",
    "reword_failed",
    "owner_confirmed",
    "released",
)


def _lenient_date(meta: dict, key: str) -> datetime.date | None:
    try:
        return _date(meta.get(key), key)
    except ValueError:
        return None


_PROMOTE_NO = ("no", False)  # a tuple, not a set: a YAML list or mapping is unhashable


def _promote_of(meta: dict) -> str | None:
    value = meta.get("promote")  # YAML reads a bare no as False
    return "no" if value in _PROMOTE_NO else "done" if value == "done" else None


def _load_of(meta: dict) -> str | None:
    value = meta.get("load")  # YAML reads a bare no as False; 0 is not no
    return "index" if value == "index" else "no" if value == "no" or value is False else None


def _choice(meta: dict, key: str, allowed: Sequence[str]) -> str | None:
    value = meta.get(key)
    return value if value in allowed else None


def _text_fields(meta: dict) -> dict:
    """The optional text fields; a bad value reads as absent."""
    superseded_by = meta.get("superseded_by")
    general = meta.get("general")
    triage = _choice(meta, "triage", TRIAGES)
    reason = meta.get("triage_reason")
    return {
        "superseded_by": str(superseded_by) if superseded_by else None,
        "general": general if isinstance(general, str) and general.strip() else None,
        "short": meta.get("short") if valid_short(meta.get("short")) else None,
        "short_by": "model" if meta.get("short_by") == "model" else None,
        "triage": triage,
        "triage_reason": reason if triage == "pending" and valid_triage_reason(reason) else None,
        "topic": meta.get("topic") if valid_topic(meta.get("topic")) else None,
    }


def _list_fields(meta: dict) -> dict:
    """The optional list fields; a bad value reads as absent."""
    distinct = meta.get("distinct_from")
    raw_log = meta.get("log")
    raw_versions = meta.get("versions")
    return {
        "distinct_from": [str(h) for h in distinct] if isinstance(distinct, list) else [],
        "log": [e for e in raw_log if isinstance(e, str) and case(e)]
        if isinstance(raw_log, list)
        else [],
        "versions": sorted((e for e in raw_versions if _version(e)), key=lambda e: e[:10])
        if isinstance(raw_versions, list)
        else [],
    }


def _optional_fields(meta: dict) -> dict:
    return {
        **{key: _lenient_date(meta, key) for key in _LENIENT_DATES},
        **_text_fields(meta),
        **_list_fields(meta),
        "promote": _promote_of(meta),
        "load": _load_of(meta),
        "origin": _choice(meta, "origin", ORIGINS),
        "reach": _choice(meta, "reach", REACHES),
        "weight": _choice(meta, "weight", WEIGHTS),
    }


def _parse_text(base: Memory, text: str) -> Memory:
    meta, body = _split(text)
    required = _required_fields(meta)
    optional = _optional_fields(meta)
    return replace(
        base,
        **required,
        **optional,
        created=_date(meta.get("created"), "created"),
        valid_until=_date(meta.get("valid_until"), "valid_until"),
        body=body,
    )


def _parse(path: Path, scope: str) -> Memory:
    base = Memory(scope, path, path.stem, "lesson", "", None, 1, "active", None, None, [], "", None)
    try:
        return _parse_text(base, path.read_text(encoding="utf-8"))
    except Exception as e:  # one broken file must not break the rest
        logger.debug("cannot parse %s", path, exc_info=True)
        name = (
            "ValueError" if isinstance(e, FieldTypeError) else type(e).__name__
        )  # the error text predates the subclass
        return replace(base, error=f"{name}: {e}".splitlines()[0])


def load_memories(folder: Path | None, scope: str) -> list[Memory]:
    try:
        if folder is None or not folder.is_dir():
            return []
        if (
            scope == "project" and folder.is_symlink()
        ):  # a cloned repository's planted link; global folders may be synced links
            return []
        return [
            _parse(p, scope)
            for p in sorted(folder.glob("*.md"), key=lambda p: p.stem)
            if p.is_file() and not (scope == "project" and p.is_symlink())
        ]
    except OSError:
        return []
