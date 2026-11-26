"""The synthesis job: topic pipeline, reference backfill and the brief files.

`backfill`: the `--backfill` driver: runs the reference sessions over the syntheses (one, the batch, a dry run) and prints the table
`cli`: command line of `mem-synthesize`, `main`, self-check
`pipeline`: the lean pipeline shared with `evals/synthesis/run_trials.py`
`references`: the steps of one reference session: select the parts, write the input, build and run the command, parse the answer
`run`: shared constants, session environment, table helpers
`topics`: topics without a synthesis: pipeline per topic, then references
"""
