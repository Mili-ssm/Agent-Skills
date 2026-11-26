# Brief: judge look-alike pairs of memories

Read `{PAIRS_FILE}`: a JSON list of pairs of short memories, each with `pair`, `a`, `b`, `claim_a`, `claim_b`, `newer` (the handle of the newer memory, or null) and `flagged_words` (words in which the two claims differ). For every pair decide whether the two claims are the same fact, a correction, or different facts, and write the decisions to `{VERDICTS_FILE}` with the Write tool.

## The four decisions

| decision | meaning |
|---|---|
| `merge` | the same fact in other words: nothing is lost if one record stays |
| `supersede` | the newer claim corrects or replaces the older one: the older is no longer true |
| `distinct` | different facts that only look alike, for example two versions, two systems, or two cases that are both valid |
| `nothing` | you cannot tell from the two claims |

## How to choose

- **When unsure, choose `nothing`.** A wrong merge or supersede loses a fact, and a wrong `distinct` hides the pair from every later check; a duplicate that stays costs only a little reading, and the pair is offered again.
- **A pair whose `newer` is null cannot be merged or superseded**, because the code cannot tell which record to keep; choose `distinct` or `nothing`.
- **A pair whose `flagged_words` is not empty cannot be merged**: those words may make the claims opposites or versions. Choose `supersede` (only when `newer` is not null), `distinct` or `nothing`.
- Judge only the two claims in the file. Do not look for other files and do not guess what a claim leaves out.

## Output

Write only `{VERDICTS_FILE}`: a JSON list with one object per pair, in this form (the handles are copied from the pair; a row that names a handle not in the file is refused):

```json
[
  {"a": "handle-one", "b": "handle-two", "decision": "distinct", "reason": "two versions of the tool, both documented"}
]
```

- `reason`: one short sentence, in English, saying why. A reason is needed for every decision but `nothing`. Include no secret, key, address or person's name, because the reason is stored in a log the owner reads and a refused reason drops the row.
- Write no other file and do not reply with the verdicts: your reply is one line, the number of pairs you judged.
