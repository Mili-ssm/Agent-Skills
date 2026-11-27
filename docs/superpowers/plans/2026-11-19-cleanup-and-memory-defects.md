# Cleanup and memory defects

Status: done · merged in #144, 2026-11-19

Goal (owner, 2026-11-19): tidy the repository after the public release and fix the small open defects of the memory plugin. CI stays out until the plugins have a reasonable number of users (owner); public repositories run GitHub Actions on standard runners without consuming minutes, noted for when it is reopened.

- [x] 1. Branches: 24 local and 35 remote branches merged into `dev` deleted (owner approved the remote ones); GitHub keeps `main` and `dev`. Check: `git branch -a`.
- [x] 2. Plans whose work merged but whose boxes stay open get a status line naming the merge, instead of boxes ticked without evidence. Check: each named PR merged (`git log --merges`).
- [x] 3. `docs/requirements.md`: the license row leaves the open questions (ADR 0027); N5's revisit trigger records the owner's condition; the two questions never put to the owner are asked. Check: `python3 scripts/validate.py`.
- [x] 4. Memory defects, one branch (`fix/memory-small-defects`), tests first: the curation-log date test after local midnight; an unclosed `<script>` hiding the rest of a fetched page; non-Markdown files of `mem import --research-data` not scanned for secrets; the forbidden-terms check skipped without `HOME` and `XDG_CONFIG_HOME`; `mem memories --project` silent when the project's folder moved; the stage 6 check naming a missing `## Measurement` section. Left out: trusting the web session's `official` label, which needs a design decision. Check: memory suite, `validate.py`.
- [x] 5. Changelog lines under `[Unreleased]`; review; PR into `dev` (#144). Released the same day as memory 0.2.0 and plan-progress 0.1.1 (#145, #146; tags pushed).
