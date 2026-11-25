"""promptkit.models: catalog validation and cross-vendor pair derivation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from promptkit.models import Catalog, Model, Policy, allowed_targets, derive_pairs, grade, load_catalog

ROOT = Path(__file__).resolve().parent.parent.parent
EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def toml(a_levels=(1, 2, 3, 4), b_levels=(1.25, 2.25, 3.25, 4.25), b_costs=(1, 10, 20, 80), overrides: str = "") -> str:
    a = "".join(f'[[vendors.a.models]]\nalias = "a{i}"\nlevel = {lv}\ncost = {10**i}\n' for i, lv in enumerate(a_levels))
    b = "".join(
        f'[[vendors.b.models]]\nid = "b{i}"\nlevel = {lv}\ncost = {c}\n' for i, (lv, c) in enumerate(zip(b_levels, b_costs))
    )
    head = (
        '[policy]\nefforts = ["low", "medium", "high", "xhigh", "max"]\neffort_step = 0.25\n'
        'never = ["max"]\nxhigh_only_on_top = true\n'
    )
    return head + a + b + overrides


def cat(tmp_path: Path, **kw) -> Catalog:
    path = tmp_path / "models.toml"
    path.write_text(toml(**kw), encoding="utf-8")
    return load_catalog(path)


def test_next_model_low_beats_previous_xhigh(tmp_path: Path) -> None:
    c = cat(tmp_path)
    for vendor in ("a", "b"):
        ms = c.models(vendor)
        for prev, nxt in zip(ms, ms[1:]):
            assert grade(nxt, "low", c) > grade(prev, "xhigh", c)


def test_max_never_chosen(tmp_path: Path) -> None:
    c = cat(tmp_path)
    assert all(e != "max" for _, e in allowed_targets("b", c))
    assert all(e != "max" for e, in [(v[1],) for v in derive_pairs(c, "a", "b").values()])


def test_xhigh_only_on_top(tmp_path: Path) -> None:
    c = cat(tmp_path)
    top = c.models("b")[-1]
    xhigh = [m for m, e in allowed_targets("b", c) if e == "xhigh"]
    assert xhigh == [top]


def test_above_all_maps_to_top_allowed(tmp_path: Path) -> None:
    c = cat(tmp_path, b_levels=(0.5, 1.5, 2.5, 3.5))
    assert derive_pairs(c, "a", "b")[("a3", "max")] == ("b3", "xhigh")


def test_tie_goes_to_cheaper() -> None:
    # load_catalog's spacing rule makes real ties impossible, so build the catalog directly.
    policy = Policy(tuple(EFFORTS), 0.25, frozenset({"max"}), True)
    src = [Model("a", "a0", 1.0, 1)]
    for costs in ((5, 3), (3, 5)):
        tgt = [Model("b", "cheap-or-not0", 1.0, costs[0]), Model("b", "cheap-or-not1", 1.0, costs[1])]
        c = Catalog(policy, {"a": src, "b": tgt}, [])
        # a0 at low (1.0) is met exactly by both targets at low; the cheaper one wins.
        want = min(tgt, key=lambda m: m.cost)
        assert derive_pairs(c, "a", "b")[("a0", "low")] == (want.key, "low")


def test_override_wins(tmp_path: Path) -> None:
    ov = '[[overrides]]\nfrom = ["a0", "low"]\nto = ["b3", "high"]\nreason = "test"\n'
    c = cat(tmp_path, overrides=ov)
    assert derive_pairs(c, "a", "b")[("a0", "low")] == ("b3", "high")


def test_every_source_pair_mapped(tmp_path: Path) -> None:
    pairs = derive_pairs(cat(tmp_path), "a", "b")
    assert len(pairs) == 20
    assert set(pairs) == {(f"a{i}", e) for i in range(4) for e in EFFORTS}


def test_catalog_rejects_falling_levels(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="level"):
        cat(tmp_path, a_levels=(1, 3, 2, 4))


def test_catalog_rejects_spacing_that_breaks_next_low(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="xhigh"):
        cat(tmp_path, b_levels=(1.0, 1.5, 3.0, 4.0))


# --- real catalog -----------------------------------------------------------------------------------


def agent_cells() -> set[tuple[str, str]]:
    cells = set()
    for path in (ROOT / "plugins").glob("*/agents/*.md"):
        head = path.read_text(encoding="utf-8").split("---")[1]
        model = re.search(r"^model:\s*(\S+)", head, re.M)
        effort = re.search(r"^effort:\s*(\S+)", head, re.M)
        if model and effort:
            cells.add((model.group(1), effort.group(1)))
    return cells


def test_agent_cells_keep_todays_pairs() -> None:
    import port

    cells = agent_cells()
    assert cells
    derived = derive_pairs(load_catalog(ROOT / "shared" / "models.toml"), "claude", "codex")
    for cell in sorted(cells):
        assert derived[cell] == port.CODEX_PAIRS[cell], cell
        # literal pins: a catalog edit that moves an agent's Codex pair must change this table on purpose
        assert cell in AGENT_PAIRS, f"new agent cell {cell}: add its Codex pair to AGENT_PAIRS"
        assert derived[cell] == AGENT_PAIRS[cell], cell


AGENT_PAIRS = {
    ("haiku", "low"): ("gpt-6-luna", "low"),
    ("haiku", "medium"): ("gpt-6-luna", "low"),
    ("haiku", "high"): ("gpt-6-luna", "medium"),
    ("sonnet", "medium"): ("gpt-6.1-terra", "low"),
    ("sonnet", "high"): ("gpt-6.1-terra", "medium"),
    ("opus", "high"): ("gpt-6.2-sol", "medium"),
}


@pytest.mark.parametrize(
    "ov",
    [
        '[[overrides]]\nfrom = ["a9", "low"]\nto = ["b0", "low"]\nreason = "typo"\n',
        '[[overrides]]\nfrom = ["a0", "low"]\nto = ["b0", "max"]\nreason = "never-chosen effort"\n',
        '[[overrides]]\nfrom = ["a0", "low"]\nto = ["b9", "low"]\nreason = "unknown target"\n',
    ],
)
def test_catalog_rejects_bad_override(tmp_path: Path, ov: str) -> None:
    with pytest.raises(ValueError, match="override"):
        cat(tmp_path, overrides=ov)


def test_default_catalog_path_is_independent_of_cwd(monkeypatch, tmp_path: Path) -> None:
    from promptkit import models

    monkeypatch.chdir(tmp_path)
    assert models.CATALOG.is_file()
