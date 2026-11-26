"""Characterization of store resolution: what every entry point answers today for the same situation.

The entry points disagree on purpose-less historical reasons; each row records today's answer, and a comment
marks the rows the store-resolution refactor flips (ruling 1: a config file is honoured everywhere; ruling 2: an
unmarked default folder is not a store; HOME-less: no passwd fallback). Paths are relative to `tmp_path`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import mem
import pytest
from research import pipeline as research_pipeline
from store import records
from synthesize import run as sr

GLOBAL = records.GLOBAL_DIR
SHARE = "share/agent-memory/store"  # XDG_DATA_HOME=share
HOME_SHARE = "home/.local/share/agent-memory/store"  # HOME=home, no XDG_DATA_HOME
ENV_KEYS = ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "MEM_STORE", "MEM_MEMORIES")


@dataclass
class Case:
    """A situation and today's answer of each entry point (None: no store)."""

    env: dict[str, str]  # values may contain `{p}`, replaced by tmp_path
    files: dict[str, str] = field(
        default_factory=dict
    )  # relative path -> text; a trailing "/" makes a folder
    cli_root: str | None = None  # relative to tmp_path
    source: str | None = None  # mem.store_source
    root: str | None = None  # mem.resolve_root with cli_root
    root_no_cli: str | None = (
        None  # mem.resolve_root without --root (only read when cli_root is set)
    )
    global_root: str | None = None  # records.global_memories_root
    research: str | None = None  # research_pipeline.default_store
    synth: str | None = None  # synthesize.run.default_store


STD = {"HOME": "{p}/home", "XDG_DATA_HOME": "{p}/share", "XDG_CONFIG_HOME": "{p}/cfg"}
MARKED = {f"{SHARE}/mem-store.yaml": "format: 1\n"}
CFG = "cfg/agent-memory/store"

CASES: dict[str, Case] = {
    "root-only": Case(
        STD,
        MARKED,
        cli_root="r",
        source="--root",
        root="r",
        root_no_cli="share/agent-memory/store",
        global_root=f"{SHARE}/{GLOBAL}",
        research=SHARE,
        synth=SHARE,
    ),
    "mem-store-marked": Case(
        {**STD, "MEM_STORE": "{p}/ms"},
        {"ms/mem-store.yaml": "format: 1\n"},
        source="MEM_STORE",
        root="ms",
        root_no_cli="ms",
        global_root=f"ms/{GLOBAL}",
        research="ms",
        synth="ms",
    ),
    "mem-store-missing-folder": Case(
        {**STD, "MEM_STORE": "{p}/ms"},
        {},
        source="MEM_STORE",
        root="ms",
        root_no_cli="ms",
        global_root=None,
        research="ms",
        synth="ms",
    ),
    "mem-store-empty-with-marked-default": Case(
        {**STD, "MEM_STORE": ""},
        MARKED,
        source="default",
        root=SHARE,
        root_no_cli=SHARE,
        global_root=f"{SHARE}/{GLOBAL}",
        research=SHARE,
        synth=SHARE,
    ),
    "mem-store-empty-with-config": Case(
        {**STD, "MEM_STORE": ""},
        {CFG: "{p}/cs\n", "cs/mem-store.yaml": "format: 1\n"},
        source="config file",
        root="cs",
        root_no_cli="cs",
        # ruling 1: global_root, research and synth honour the config file
        global_root=f"cs/{GLOBAL}",
        research="cs",
        synth="cs",
    ),
    "config-only": Case(
        STD,
        {CFG: "{p}/cs\n", "cs/mem-store.yaml": "format: 1\n"},
        source="config file",
        root="cs",
        root_no_cli="cs",
        # ruling 1: global_root, research and synth honour the config file
        global_root=f"cs/{GLOBAL}",
        research="cs",
        synth="cs",
    ),
    "config-first-line-blank-with-marked-default": Case(
        STD,
        {**MARKED, CFG: "\n{p}/cs\n", "cs/mem-store.yaml": "format: 1\n"},
        # mem reads the first line only: a blank one means no config; unchanged by the rulings
        source="default",
        root=SHARE,
        root_no_cli=SHARE,
        global_root=f"{SHARE}/{GLOBAL}",
        research=SHARE,
        synth=SHARE,
    ),
    "config-first-line-blank-alone": Case(
        STD,
        {CFG: "\n{p}/cs\n", "cs/mem-store.yaml": "format: 1\n"},
        source=None,
        root=None,
        root_no_cli=None,
        global_root=None,
        research=None,
        synth=None,
    ),
    "config-beats-marked-default": Case(
        STD,
        {**MARKED, CFG: "{p}/cs\n", "cs/mem-store.yaml": "format: 1\n"},
        source="config file",
        root="cs",
        root_no_cli="cs",
        # ruling 1: global_root, research and synth honour the config file
        global_root=f"cs/{GLOBAL}",
        research="cs",
        synth="cs",
    ),
    "default-marked": Case(
        STD,
        MARKED,
        source="default",
        root=SHARE,
        root_no_cli=SHARE,
        global_root=f"{SHARE}/{GLOBAL}",
        research=SHARE,
        synth=SHARE,
    ),
    "default-folder-without-marker": Case(
        STD,
        {f"{SHARE}/": ""},
        # ruling 2: no entry point uses an unmarked default folder
        source=None,
        root=None,
        root_no_cli=None,
        global_root=None,
        research=None,
        synth=None,
    ),
    "nothing": Case(STD, {}),
    "mem-store-tilde": Case(
        {**STD, "MEM_STORE": "~/ms"},
        {"home/ms/mem-store.yaml": "format: 1\n"},
        source="MEM_STORE",
        root="home/ms",
        root_no_cli="home/ms",
        global_root=f"home/ms/{GLOBAL}",
        research="home/ms",
        synth="home/ms",
    ),
    "home-only-marked-default": Case(
        {"HOME": "{p}/home"},
        {f"{HOME_SHARE}/mem-store.yaml": "format: 1\n"},
        source="default",
        root=HOME_SHARE,
        root_no_cli=HOME_SHARE,
        global_root=f"{HOME_SHARE}/{GLOBAL}",
        research=HOME_SHARE,
        synth=HOME_SHARE,
    ),
    "home-only-config": Case(
        {"HOME": "{p}/home"},
        {"home/.config/agent-memory/store": "{p}/cs\n", "cs/mem-store.yaml": "format: 1\n"},
        source="config file",
        root="cs",
        root_no_cli="cs",
        # ruling 1: global_root, research and synth honour the config file
        global_root=f"cs/{GLOBAL}",
        research="cs",
        synth="cs",
    ),
    "no-home-no-xdg": Case(
        {"HOME": ""},
        {f"{HOME_SHARE}/mem-store.yaml": "format: 1\n"},
        # HOME-less ruling: research and synth lose their Path.home() fallback and answer None
        source=None,
        root=None,
        root_no_cli=None,
        global_root=None,
        research=None,
        synth=None,
    ),
    "no-home-no-xdg-with-mem-store": Case(
        {"HOME": "", "MEM_STORE": "{p}/ms"},
        {"ms/mem-store.yaml": "format: 1\n"},
        source="MEM_STORE",
        root="ms",
        root_no_cli="ms",
        global_root=f"ms/{GLOBAL}",
        research="ms",
        synth="ms",
    ),
    "mem-store-beats-config": Case(
        {**STD, "MEM_STORE": "{p}/ms"},
        {"ms/mem-store.yaml": "format: 1\n", CFG: "{p}/cs\n", "cs/mem-store.yaml": "format: 1\n"},
        source="MEM_STORE",
        root="ms",
        root_no_cli="ms",
        global_root=f"ms/{GLOBAL}",
        research="ms",
        synth="ms",
    ),
    "mem-store-beats-config-and-marked-default": Case(
        {**STD, "MEM_STORE": "{p}/ms"},
        {
            **MARKED,
            "ms/mem-store.yaml": "format: 1\n",
            CFG: "{p}/cs\n",
            "cs/mem-store.yaml": "format: 1\n",
        },
        source="MEM_STORE",
        root="ms",
        root_no_cli="ms",
        global_root=f"ms/{GLOBAL}",
        research="ms",
        synth="ms",
    ),
    "root-beats-mem-store-and-config": Case(
        {**STD, "MEM_STORE": "{p}/ms"},
        {"ms/mem-store.yaml": "format: 1\n", CFG: "{p}/cs\n", "cs/mem-store.yaml": "format: 1\n"},
        cli_root="r",
        source="--root",
        root="r",
        root_no_cli="ms",
        global_root=f"ms/{GLOBAL}",
        research="ms",
        synth="ms",
    ),
    "config-with-tilde": Case(
        {"HOME": "{p}/home"},
        {"home/.config/agent-memory/store": "~/cs\n", "home/cs/mem-store.yaml": "format: 1\n"},
        source="config file",
        root="home/cs",
        root_no_cli="home/cs",
        # ruling 1: global_root, research and synth honour the config file
        global_root=f"home/cs/{GLOBAL}",
        research="home/cs",
        synth="home/cs",
    ),
    "home-unset-no-xdg": Case(
        {},
        {f"{HOME_SHARE}/mem-store.yaml": "format: 1\n"},
        # HOME-less ruling: research and synth lose their Path.home() fallback (patched to tmp/home) and answer None
        source=None,
        root=None,
        root_no_cli=None,
        global_root=None,
        research=None,
        synth=None,
    ),
}


@pytest.fixture
def world(request, tmp_path, monkeypatch):
    """Build the case's files and environment; return (case, env, at) with `at(rel)` -> Path | None."""
    case = CASES[request.param]
    for rel, text in case.files.items():
        target = tmp_path / rel
        if rel.endswith("/"):
            target.mkdir(parents=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text.replace("{p}", str(tmp_path)), encoding="utf-8")
    env = {k: v.replace("{p}", str(tmp_path)) for k, v in case.env.items()}
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # no row depends on the machine: the passwd fallback lands in a folder of the test
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    return case, env, lambda rel: None if rel is None else tmp_path / rel


def with_cases(test: Callable) -> Callable:
    return pytest.mark.parametrize("world", list(CASES), indirect=True, ids=list(CASES))(test)


@with_cases
def test_store_source(world):
    case, env, at = world
    assert mem.store_source(str(at(case.cli_root)) if case.cli_root else None, env) == case.source


@with_cases
def test_resolve_root(world):
    case, env, at = world
    assert mem.resolve_root(str(at(case.cli_root)) if case.cli_root else None, env) == at(case.root)


@pytest.mark.parametrize(
    "world",
    [name for name, case in CASES.items() if case.cli_root],
    indirect=True,
)
def test_resolve_root_without_cli_root(world):
    case, env, at = world
    assert mem.resolve_root(None, env) == at(case.root_no_cli)


@with_cases
def test_global_memories_root(world):
    case, env, at = world
    assert records.global_memories_root(env) == at(case.global_root)


@with_cases
def test_research_pipeline_default_store(world):
    case, _, at = world
    assert research_pipeline.default_store() == at(case.research)


@with_cases
def test_mem_synthesize_default_store(world):
    case, _, at = world
    assert sr.default_store() == at(case.synth)


DEFAULT_PATHS: dict[str, tuple[dict[str, str], str | None]] = {
    "xdg-data-home": ({"HOME": "{p}/home", "XDG_DATA_HOME": "{p}/share"}, SHARE),
    "only-home": ({"HOME": "{p}/home"}, HOME_SHARE),
    "neither": ({}, None),
}


@pytest.mark.parametrize("name", list(DEFAULT_PATHS))
def test_records_default_store(name, tmp_path):
    """`mem init` relies on it: the default folder path with no marker check, whatever exists on disk."""
    env_template, rel = DEFAULT_PATHS[name]
    env = {k: v.replace("{p}", str(tmp_path)) for k, v in env_template.items()}
    assert records.default_store(env) == (tmp_path / rel if rel else None)
