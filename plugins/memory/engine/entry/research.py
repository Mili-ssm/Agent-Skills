"""Entry of `bin/mem-research`: the command line lives in `research.pipeline`."""

import sys

from research import pipeline


def main() -> int:
    return pipeline.main(sys.argv[1:])
