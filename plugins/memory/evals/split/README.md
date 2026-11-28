# Split synthetic trial

Run `python3 plugins/memory/evals/split/run_trial.py` from the repository root. It copies the valid engine fixture into disposable `target/mem-trials/` stores, applies the seeded proposal through `bin/mem`, and removes the stores afterward. It checks new and existing children, reference and figure preservation, routing, `mem check`, and byte-for-byte undo excluding split operation history. Invalid references, missing figures, and a colliding destination must be refused without store changes.

The trial supplements the engine tests: `test_split_command.py::test_interrupted_write_and_recovery` covers interrupted apply and undo, recovery, and retry; `test_split_command.py::test_refuses_undo_after_edit` covers later edits. Run these with the engine suite. The synthetic trial does not establish semantic quality of a model proposal or validate a real copied store.
