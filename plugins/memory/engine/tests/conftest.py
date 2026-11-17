import os
import shutil
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "valid"


@pytest.fixture
def hub_root(tmp_path: Path) -> Path:
    root = tmp_path / "hub"
    shutil.copytree(FIXTURE, root)
    shutil.copytree(Path(__file__).resolve().parent / "fixtures" / "templates", root / "templates")
    (root / "mem-store.yaml").write_text("format: 1\n", encoding="utf-8")  # the marker that makes a store writable
    return root


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "mem-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "mem-config"))
    monkeypatch.delenv("MEM_STORE", raising=False)
    monkeypatch.delenv("MEM_PROJECT", raising=False)
    monkeypatch.delenv("MEM_MEMORIES", raising=False)


def usage_log_path() -> Path:
    return Path(os.environ["MEM_DATA"]) / "usage" / "log.jsonl"
