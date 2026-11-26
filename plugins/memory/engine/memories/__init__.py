"""Memories: the record model, parsing and writing, matching, terms, locations, sightings, rules and fingerprints.

`fingerprints`: lookups of the digest: fingerprints, stored heading or line of a lesson
`journal`: curation log: record text before an action, and undo
`locations`: git roots, project registry, memories folders, project key
`matching`: term matching, containment, related records, duplicate and refuting pairs
`model`: the `Memory` record, its vocabularies, one-line checks, `short_problems`
`parse`: a Markdown file with YAML frontmatter becomes a `Memory`
`records`: facade re-exporting names as `records.<name>`; no logic
`rules`: which lessons load as rules at session start, order, text
`sightings`: sightings, cases and versions of a memory
`terms`: forbidden terms, secret patterns, global-scope checks
`write`: render a memory file, new memories, field updates

A base layer like `core`: imports stdlib, `core` and `memories` only (never `notes`).
"""
