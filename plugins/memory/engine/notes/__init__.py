"""Notes: frontmatter and the `Note` model, the index and the validators.

`check`: check rule catalog and `check()`; pure
`due`: requirement rows and due queries; pure
`fields`: field rules of a note's frontmatter; pure
`index`: generated index READMEs and `apply_index`
`links`: link rules: relative links resolve, `orphan_notes`; pure
`note`: frontmatter, YAML loaders, `Note`, topics, handles

A base layer like `core`: imports stdlib, `core`, `memories`, `syntheses` and `notes` only.
"""
