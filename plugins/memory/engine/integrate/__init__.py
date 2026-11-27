"""Joining a note to a part of a synthesis: the rows that say which note goes where, and the checks on the claim.

`rows`: the row format, its parser (`parse_rows`, `row_of`) and the claim check
`answers`: the lines of a session's answer, or None when any line is malformed
`plan`: the placement rows of an answer, kept only when the note, part and fingerprint were offered and the unit is in the part's range
`state`: the done list and the run record kept in the state folder
"""
