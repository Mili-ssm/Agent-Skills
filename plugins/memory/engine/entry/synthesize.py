"""mem-synthesize: write syntheses for topics that have none, quietly, one headless session per step.

Per topic: writer (the `memory-synthesizer` agent) -> checker -> one fixer round -> scoped check -> delete-only step
when claims remain -> `mem synthesis attach` for the writer's attach list. The store changes only through `mem`
(`mem restore` undoes a step). Stdout: one line at the start and one table at the end; everything else goes to a log
file whose path is printed. On demand only: it spends model usage (about 0.5 USD per topic, unmeasured at high effort).
Its last step adds inline references (the `--backfill` step below, about 0.05 USD per synthesis); a failure there leaves
the synthesis as the loop left it and does not fail the topic; only a `mem check` that no longer exits 0 after the
references were written does. `--no-references` skips the step.

`--backfill [s:<handle> ...]` adds inline references to existing syntheses instead: one read-only Haiku session per
synthesis proposes which source note supports each sentence, and code applies them (`mem synthesis refs`).

Usage: mem-synthesize [--topic T]... [--budget USD (3)] [--no-references] [--dry-run] [--store PATH] [--claude PATH] | --self-check
       mem-synthesize --backfill [s:<handle> ...] [--budget USD] [--dry-run] [--store PATH] [--claude PATH]
"""

from synthesize import cli


def main() -> int:
    return cli.main(__doc__ or "")
