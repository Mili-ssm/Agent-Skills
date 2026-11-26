"""`mem` keeps serving the names that moved out of it: callers and tests read them as `mem.<name>`."""

import mem
import pytest


@pytest.mark.parametrize("name", sorted(mem._MOVED))
def test_moved_name_resolves_through_mem(name):
    assert getattr(mem, name) is not None
