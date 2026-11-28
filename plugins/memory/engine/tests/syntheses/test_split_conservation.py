from syntheses.split_conservation import check_conservation


def test_canonical_references_in_body_and_sources(tmp_path):
    original = "A claim. [a](../knowledge/d/a.md)\n\nSources: [b](../research/d/b.md)"
    retained = "A claim. [a](../knowledge/d/./a.md)\n\nSources: [b](../research/d/../d/b.md)"
    assert check_conservation(tmp_path, original, retained, "") == []
    problems = check_conservation(tmp_path, original, "", "")
    assert any("a.md" in problem for problem in problems)
    assert any("b.md" in problem for problem in problems)


def test_repeated_figures_are_counted_across_both_parts(tmp_path):
    original = "There were 42 cases and 42 controls."
    assert check_conservation(tmp_path, original, "There were 42 cases.", "42 controls.") == []
    problems = check_conservation(tmp_path, original, "There were 42 cases.", "")
    assert len(problems) == 1 and "42" in problems[0]


def test_metadata_urls_and_trailing_labels_do_not_mask_figures(tmp_path):
    original = (
        "There were 2024 cases. [123](../knowledge/d/a.md)\n\nSources: [123](../knowledge/d/a.md)"
    )
    retained = "See [123](../knowledge/d/a.md) and https://example.org/2024.\n\nSources: [2024](../knowledge/d/a.md)"
    problems = check_conservation(tmp_path, original, retained, "")
    assert len(problems) == 1 and "2024" in problems[0]


def test_visible_link_text_is_a_figure(tmp_path):
    original = "There were [42 cases](https://example.org/99)."
    assert check_conservation(tmp_path, original, "There were 42 cases.", "") == []
    assert len(check_conservation(tmp_path, original, "There were 99 cases.", "")) == 1


def test_figure_before_sentence_punctuation_is_counted(tmp_path):
    assert len(check_conservation(tmp_path, "The total is 42.", "The total is gone.", "")) == 1


def test_sign_and_percent_are_part_of_figures(tmp_path):
    assert check_conservation(tmp_path, "A change of -5 and 5%.", "A change of 5 and 5.", "")
    assert check_conservation(tmp_path, "A change of -5.", "A change of 5.", "")
    assert check_conservation(tmp_path, "A rate of 5%.", "A rate of 5.", "")
    assert check_conservation(tmp_path, "- 5 items.", "5 items.", "") == []
