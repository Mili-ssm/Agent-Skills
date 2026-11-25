"""Vendor model catalog (shared/models.toml) and the cross-vendor (model, effort) pairs derived from it.

Run from scripts/: python3 -m promptkit.models [--catalog PATH] [SOURCE TARGET]   print the derived pairs
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[2] / "shared" / "models.toml"  # repo root, whatever the cwd
Pair = tuple[str, str]


@dataclass(frozen=True)
class Model:
    vendor: str
    key: str  # the agent alias (Claude) or the model id (others)
    level: float
    cost: float
    copilot: str | None = None


@dataclass(frozen=True)
class Policy:
    efforts: tuple[str, ...]
    effort_step: float
    never: frozenset[str]
    xhigh_only_on_top: bool


@dataclass(frozen=True)
class Override:
    source: Pair
    target: Pair
    reason: str


@dataclass(frozen=True)
class Catalog:
    policy: Policy
    by_vendor: dict[str, list[Model]]
    overrides: list[Override]

    def models(self, vendor: str) -> list[Model]:
        return list(self.by_vendor[vendor])


def grade(model: Model, effort: str, catalog: Catalog) -> float:
    return model.level + catalog.policy.effort_step * catalog.policy.efforts.index(effort)


def load_catalog(path: Path) -> Catalog:
    try:
        return _load_catalog(path)
    except (KeyError, TypeError, AttributeError, ValueError, tomllib.TOMLDecodeError) as err:  # one readable line, not a bare KeyError
        raise ValueError(f"{path}: malformed catalog ({type(err).__name__}: {err})") from err


def _load_catalog(path: Path) -> Catalog:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    p = data["policy"]
    policy = Policy(tuple(p["efforts"]), float(p["effort_step"]), frozenset(p["never"]), bool(p["xhigh_only_on_top"]))
    by_vendor: dict[str, list[Model]] = {}
    for vendor, body in data["vendors"].items():
        by_vendor[vendor] = [
            Model(vendor, m.get("alias") or m["id"], float(m["level"]), float(m["cost"]), m.get("copilot"))
            for m in body["models"]
        ]
    overrides = [Override(tuple(o["from"]), tuple(o["to"]), o["reason"]) for o in data.get("overrides", [])]
    catalog = Catalog(policy, by_vendor, overrides)
    for vendor, models in by_vendor.items():
        for prev, nxt in zip(models, models[1:]):
            if nxt.level <= prev.level:
                raise ValueError(f"{vendor}: level of {nxt.key} ({nxt.level}) must exceed {prev.key} ({prev.level})")
            if grade(nxt, "low", catalog) <= grade(prev, "xhigh", catalog):
                raise ValueError(
                    f"{vendor}: {nxt.key} at low ({grade(nxt, 'low', catalog)}) must beat {prev.key} at xhigh "
                    f"({grade(prev, 'xhigh', catalog)})"
                )
    keys = {m.key for models in by_vendor.values() for m in models}
    for o in overrides:  # a typo would otherwise be ignored, and a forbidden effort accepted
        if o.source[0] not in keys or o.source[1] not in policy.efforts:
            raise ValueError(f"override from {list(o.source)}: unknown model or effort")
        if o.target[0] not in keys or o.target[1] not in policy.efforts or o.target[1] in policy.never:
            raise ValueError(f"override to {list(o.target)}: unknown model, or an effort the policy never chooses")
    return catalog


def allowed_targets(vendor: str, catalog: Catalog) -> list[tuple[Model, str]]:
    models = catalog.models(vendor)
    out = []
    for model in models:
        for effort in catalog.policy.efforts:
            if effort in catalog.policy.never:
                continue
            if effort == "xhigh" and catalog.policy.xhigh_only_on_top and model is not models[-1]:
                continue
            out.append((model, effort))
    return out


def derive_pairs(catalog: Catalog, source: str, target: str) -> dict[Pair, Pair]:
    """Per source (model, effort): the allowed target pair with the smallest grade >= the source's, ties to the cheaper."""
    targets = allowed_targets(target, catalog)
    result: dict[Pair, Pair] = {}
    for model in catalog.models(source):
        for effort in catalog.policy.efforts:
            want = grade(model, effort, catalog)
            fit = [(grade(m, e, catalog), m.cost, m, e) for m, e in targets if grade(m, e, catalog) >= want]
            if fit:
                _, _, best, best_effort = min(fit, key=lambda t: (t[0], t[1]))
            else:
                best, best_effort = max(((m, e) for m, e in targets), key=lambda t: (grade(t[0], t[1], catalog), -t[0].cost))
            result[(model.key, effort)] = (best.key, best_effort)
    for o in catalog.overrides:
        if o.source in result:
            result[o.source] = o.target
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the pairs derived from the model catalog.")
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("source", nargs="?", default="claude")
    parser.add_argument("target", nargs="?", default="codex")
    args = parser.parse_args(argv)
    for (model, effort), (tm, te) in derive_pairs(load_catalog(args.catalog), args.source, args.target).items():
        print(f"{model}/{effort}: {tm} {te}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
