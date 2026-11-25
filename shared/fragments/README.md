# Shared fragments

A fragment is a text repeated across agent, command or skill files, kept once in `shared/fragments/<id>.md`. Each consumer file stays complete (installed plugins read the committed files) and carries a marked block that the tool fills.

## Marker syntax

```
<!-- shared:<id> key="value" ... -->
rendered text
<!-- /shared:<id> -->
```

- Markers sit alone on their line, outside fenced code (CommonMark: a fence closes with the same character and at least the opening length; `~~~` counts; an unclosed fence runs to the end of the file).
- `{{key}}` placeholders in the fragment are filled from the opening marker's attributes. Every placeholder needs an attribute and every attribute a placeholder.
- Attributes are `key="value"`; a value is the text up to the next `"`, with no escaping, so it cannot contain `"`.
- A fragment's text is the file without its trailing newline.
- A first line `verbatim-in: <repo-relative path>` (stripped from the text) also requires the text to appear verbatim in that file. Use it for text that lives in `user-config/`, which the tool never scans.
- A missing `shared/fragments/` folder means no fragments.

## Commands

Run from `scripts/`; add `--root PATH` to target another repository.

| Command | Effect |
|---|---|
| `python3 -m promptkit.fragments` | Rewrites every block of `plugins/*/{agents,commands}/*.md` and `plugins/*/skills/**/*.md` from its fragment |
| `python3 -m promptkit.fragments --check` | Changes nothing; prints `<file>: block '<id>' differs from shared/fragments/<id>.md` per hand edit and `<file>: text of '<id>' outside a block` per unmarked copy of a parameterless fragment; exits 1 on any problem |

`scripts/validate.py` runs the `--check` logic. Never edit inside a block: edit the fragment and render.
