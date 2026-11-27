"""Joining a note to a part of a synthesis: the rows that say which note goes where, and the checks on the claim.

`rows`: the row format, its parser (`parse_rows`, `row_of`), the row as a line (`row_line`) and the claim check
`answers`: the lines of a session's answer, or None when any line is malformed
`plan`: the placement rows of an answer, kept only when the note, part and fingerprint were offered and the unit is in the part's range; what a candidate offered (`offered_of`) and the rows the check agreed (`agreed`)
`log`: the curation log as a stack, the one reader of it for an integration and its undo (`log_entries`)
`state`: the done list and the run record kept in the state folder
`undo`: undoing a run's groups, each only while it is still the newest change of every file it wrote (`newest_is_group`)
"""
