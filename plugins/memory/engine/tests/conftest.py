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
    return root
