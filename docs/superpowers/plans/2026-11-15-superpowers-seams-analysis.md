# Superpowers and agent-skills seams analysis

Status: done · merged in #113, 2026-11-15

Goal: document where Superpowers 7.0.2 and the `agent-skills` plugin overlap in intent and in action, so the owner can decide seam by seam later. This work changes no agent, skill, command or policy text.

Deliverable: `docs/superpowers-seams.md`.

Amendments from the pre-mortem (2026-11-15): the doc pins the Superpowers version and gives a recheck command; `docs/requirements.md` § Superpowers boundary stays the home of the decided state, and each seam says whether it agrees with it; a banner says no decision is taken; each claim is marked `text`, `observed` or `inferred`; usage counts carry their window and versions; the fact-check covers every row; `validate.py` does not scan `docs/`, so line numbers and names are checked with grep.

- [x] Pre-mortem run and amendments folded in.
- [x] Evidence gathered per area: planning, execution, review and verification, debugging and testing, activation and authoring. Check: every claim in each area report names a file and quotes it.
- [x] Claims that define a seam verified at the source. Check: both sides of each seam row confirmed by grep or a range read.
- [x] `docs/superpowers-seams.md` written. Check: `python3 scripts/validate.py` still passes for the repository; grep finds no line numbers and no project or business names in the doc.
- [x] Fact-check and reviews done and triaged. Check: `fact-checker` verdicts applied; `skeptical-reviewer` stops at round 2.
- [x] Owner report with the open decisions. Check: `git status` shows only the new doc, this plan and the link line in `docs/requirements.md`; nothing committed or pushed.
