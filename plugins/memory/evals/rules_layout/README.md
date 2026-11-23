# Trial: flat or grouped loaded rules

Asks whether the grouped layout (`mem rules --layout grouped`) keeps three checkable rules followed, compared with the flat one.

## Run

`python3 plugins/memory/evals/rules_layout/run_trial.py --out <folder outside the repository> [--runs 3] [--max-cost-usd 1.00]`

`--dry-run` builds everything and prints the two blocks without calling a model (no cost). A real run takes about 7 headless Sonnet sessions (one canary, then F and G alternating) and is estimated at about 0.5 USD from the cost of a run in the measure of 2026-11-22 (the two attempts of 2026-11-23, which stopped early, cost 0.12 and 0.26 USD); each run is capped at 0.25 USD and the whole trial at the cap given.

## What it does

| Step | Detail |
| --- | --- |
| Setup | Everything lives in a `mktemp` folder outside the repository: 16 lessons written and accepted through `mem` (seven topics; three rules that leave a trace, none first), then `mem rules --layout flat` and `--layout grouped` produce the two rules files |
| Isolation | Environment from `trial_env.make_env` minus every owner `MEM_*` variable; asserted before any write and any model call. The session loads only project settings and the run's settings file, whose session start hook prints the rules file; it must report no installed plugin and no knowledge of the repository's instructions (canary with a random token) |
| Guard | A checksum list of the owner's global memories folder, this repository's `.memory/` and the plugin's state folder before the first model call and after the last |
| Task | `greet.py` prints a misspelled greeting; "Fix it and commit the change." Tools: `Read`, `Edit`, `Write` and bounded Bash patterns (`./check.sh*`, `git *`, `python3 greet.py*`, `echo`, `printf`, `cat`, `ls`, `tail`, `head`, `chmod +x check.sh`; see `TOOLS`) |
| Score, by code, per rule | `check.sh` run and its last line quoted in the reply; last commit message starts with `fix:`, `feat:`, `docs:` or `chore:` (scope allowed); `NOTES.md` has a new line |
| Stops | Canary fails; a run with a permission denial is void and rerun once in its condition, and more than two void runs stop the trial; real memory folders change; cost over the cap or 0.60 USD after four runs; flat below 3 of 3 on a rule (the setup then differs from the measure of 2026-11-22) |

## What it can say

Three runs on one easy task, where every rule applies, can show a collapse of the grouped block. It cannot show a benefit or equivalence. Both layouts following all rules is worded "no collapse seen on an easy task; a benefit was not measured".

## Result

None recorded. Two attempts stopped on void runs: the model chains edit, `NOTES.md` line, `./check.sh` and commit in one Bash call (with `sed -i` or a redirect), and the permission match denies a chain when any part falls outside `TOOLS`. First attempt: the narrow list, one void run. Second attempt: the bounded list above, three void runs (one rerun included). Before a third attempt decide how to let a chain pass (for example `Bash(*)` inside the throwaway project) or to ask for one command per call.
