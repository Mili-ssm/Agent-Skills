import pytest

import shortcheck

HEDGED = "the claim is hedged and the short form is not"


@pytest.mark.parametrize("claim,short,expected", [
    ("Smaller briefs may avoid the turn limit (untested).", "Smaller briefs may avoid a subagent's turn limit.", []),
    ("Smaller briefs may avoid the turn limit.", "Use smaller briefs to avoid the turn limit.", [HEDGED]),
    ("Check the count in the run log before calling a backfill complete.", "Always check the run log.",
     ['the short form says "always" and the claim does not']),
    ("Never push without asking.", "Never push without asking.", []),
    ("Read the docs.", "Read https://example.org first.", ["the short form holds a link"]),
    ("It may be so.", "Maybe do it.", [HEDGED]),
    ("It can't be undone.", "It can't be undone.", []),  # `can't` is not the hedge `can`
    ("Ask the owner first.", "Ask the owner first.", ['the short form says "owner": say "the user"']),
    ("It can't be undone.", "Undo it.", []),                                 # an inner apostrophe keeps `can't` whole
    ("It may fail.", "It can\u2019t fail.", ["the claim is hedged and the short form is not", 'the short form says "can\'t" and the claim does not']),
    ("It can\u2019t be undone.", "Undo it.", []),                            # a typographic apostrophe is the plain one
    ("Say it to the team.", "Say 'always' to the team.", ['the short form says "always" and the claim does not']),
    ("Ask the owner.", "Ask the owner's team.", ['the short form says "owner": say "the user"']),
])
def test_problems(claim, short, expected):
    assert shortcheck.problems(claim, short) == expected


def test_two_problems_are_both_reported_hedge_first():
    claim = "Smaller briefs might avoid the turn limit."
    short = "Smaller briefs must avoid the turn limit."
    assert shortcheck.problems(claim, short) == [HEDGED, 'the short form says "must" and the claim does not']


def test_case_and_punctuation_do_not_hide_a_word():
    assert shortcheck.problems("MAY, perhaps, help.", "Never. Help.") == [
        HEDGED, 'the short form says "never" and the claim does not']
