"""Joining a note to a part of a synthesis: the rows that say which note goes where, and the checks on the claim.

`rows`: the row format, its parser and the claim check
`answers`: the lines of a session's answer, or None when any line is malformed
`plan`: the placement rows of an answer, kept only when the note, part, fingerprint and unit were offered
"""
