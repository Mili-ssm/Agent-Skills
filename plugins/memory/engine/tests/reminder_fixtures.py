"""Fixtures the reminder test files share: a git project and a global memories folder, both under tmp_path."""
import subprocess

import pytest


@pytest.fixture
def project(tmp_path, monkeypatch):
    """The root of a real git repository, never the one the tests run in; MEM_PROJECT points at it."""
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return root


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder
