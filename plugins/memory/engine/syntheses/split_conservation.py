"""Check that a split keeps the original section's references and figures."""

import re
from collections import Counter
from pathlib import Path

from syntheses.document import _resolved, _sources_line, references
from syntheses.units import _REF_LINK, _inline, _is_ref, _parse, _relative, _remove

_FIGURE = re.compile(r"(?<![\w.])[+-]?\d+(?:[.,]\d+)*%?(?!\w)")
_URL = re.compile(r"https?://[^\s<>]+")


def _references(base: Path, text: str) -> set[Path]:
    sources = _sources_line(text) or ""
    targets = references(text) + [
        m.group(2)
        for m in _REF_LINK.finditer(sources)
        if _relative(m.group(2)) and _is_ref(m.group(2))
    ]
    return {_resolved(base, target) for target in targets}


def _figures(text: str) -> Counter[str]:
    _, refs, _, body_end = _parse(text)
    body = _remove(text, 0, body_end, refs)
    lines = []
    for line in body.splitlines():
        pieces, pos = [], 0
        for start, end, kind, match in _inline(line):
            if kind == "link" and match is not None:
                pieces.extend((line[pos:start], match.group(1)))
                pos = end
        pieces.append(line[pos:])
        lines.append(_URL.sub("", "".join(pieces)))
    return Counter(_FIGURE.findall("\n".join(lines)))


def check_conservation(root: Path, original: str, retained: str, moved: str) -> list[str]:
    """Return one problem per missing resolved note and missing figure occurrence."""
    base = root / "syntheses"
    missing_refs = (
        _references(base, original) - _references(base, retained) - _references(base, moved)
    )
    missing_figures = _figures(original) - (_figures(retained) + _figures(moved))
    return [f"missing reference: {path}" for path in sorted(missing_refs)] + [
        f"missing figure: {figure}"
        for figure, count in sorted(missing_figures.items())
        for _ in range(count)
    ]
