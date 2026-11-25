from conftest import run_checks


def test_mini_repo_is_valid(mini_repo):
    assert run_checks(mini_repo) == []
