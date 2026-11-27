"""The corroboration pass: matches lessons by meaning and keeps one general record of each (`bin/mem-corroborate`).

`cli`: commands that need the whole engine, self-check
`decide`: what the pass reads and does with the groups a model returns; pure
`digest`: heading per topic and line per lesson for session start
`fill`: short form and topic of lessons that lack them
`reword`: new short form for loaded lessons that got worse
`run`: model sessions, briefs, applier, `execute` (one run)
`state`: state folder, journal and undo, commands needing nothing else
"""
