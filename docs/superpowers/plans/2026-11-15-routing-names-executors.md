# Routing names the skill or agent

Goal: make `user-config/routing.md` say who the model can use for each need, so skills and agents are used without the owner naming them (owner, 2026-11-15). `user-config/offload-policy.md`, agents, skills and commands do not change.

- [x] `routing.md`: opening rule on unasked use; rows name skills and agents, not commands; the three rules ported from the owner's file; `fixer` covers tests broken by a rename. Check: `python3 scripts/port.py --check` and `python3 scripts/validate.py` pass; `git diff --stat main -- user-config/offload-policy.md` is empty.
- [x] ADR 0022, requirement R6, the commands as an open question, status line and review note on ADR 0007. Check: `grep -n '^Status' docs/adr/0007* docs/adr/0022*` shows the amendment on both.
- [x] Pre-mortem, prompt review, coverage of the old rows, fact-check of ADR 0022; findings triaged. Check: round 2 at most. Outcome: fact-check 22 claims, 3 corrected; prompt review 7 findings applied; coverage 3 findings applied, no route lost; pre-mortem 6 amendments applied, 1 rejected (`ui-verifier` keeps its trigger in the offload policy).
- [x] Commit, push, pull request. Check: `gh pr view --json files` matches `git diff --stat main...HEAD`.
- [x] After the merge: the owner's user-level file re-pasted from `main`, its personal "Skills and routes" text reduced to what routing does not say. Check: both pasted blocks equal `origin/main`.
