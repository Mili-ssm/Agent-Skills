# Shared fragments

A fragment is a text repeated across agent, command or skill files, kept once in `shared/fragments/<id>.md`. Each consumer file stays complete (installed plugins read the committed files) and carries a marked block that the tool fills.

## Marker syntax

```
<!-- shared:<id> key="value" ... -->
rendered text
<!-- /shared:<id> -->
```

- Markers sit alone on their line (indented 0 to 3 spaces; a marker line indented 4 or more spaces, or malformed, is an error, because inside a list item it would be read as text; the block content is compared exactly), outside fenced code (CommonMark: a fence closes with the same character and at least the opening length; `~~~` counts; an unclosed fence runs to the end of the file). A `shared:` marker line inside a fence left open to the end of the file is an error (`unclosed code fence opened before a shared marker`), because it would hide every later block.
- `{{key}}` placeholders in the fragment are filled from the opening marker's attributes. Every placeholder needs an attribute and every attribute a placeholder.
- Attributes are `key="value"`; a value is the text up to the next `"`, with no escaping, so it cannot contain `"`.
- A fragment's text is the file without its trailing newlines; a fragment that leaves a code fence open is an error.
- A first line `verbatim-in: <repo-relative path>` (stripped from the text) also requires the text to appear verbatim in that file. Use it for text that lives in `user-config/`, which the tool never renders: markers there are an error, because those files are copied raw into evals, users' CLAUDE.md and the README prompt block. Out of scope as well: `user-agents/` (installed raw at user scope) and the README, whose prompt block `port.py` generates from `user-config/`.
- `README.md` in this folder documents it and is no fragment.
- A marker naming an id without a fragment is an error (`unknown fragment id`), also when the folder is missing or empty; files without markers pass.
- An unmarked copy is the fragment's full text occupying whole lines (a match inside a longer line does not count).
- Rendering keeps a file's newline style: a CRLF file stays CRLF; in a file that mixes CRLF and LF, lines outside blocks keep their endings and block content is written with LF.

## Commands

Run from `scripts/`; add `--root PATH` to target another repository.

| Command | Effect |
|---|---|
| `python3 -m promptkit.fragments` | Rewrites every block of `plugins/*/{agents,commands}/*.md` and `plugins/*/skills/**/*.md` from its fragment |
| `python3 -m promptkit.fragments --check` | Changes nothing; prints `<file>: block '<id>' differs from shared/fragments/<id>.md` per hand edit and `<file>: text of '<id>' outside a block` per unmarked copy of a parameterless fragment; exits 1 on any problem |

`scripts/validate.py` runs the `--check` logic. Never edit inside a block: edit the fragment and render.
