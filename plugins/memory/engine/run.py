#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.15"  # keep in step with mem.py
# dependencies = ["pyyaml"]
# ///
"""Launcher of bin/mem: imports mem, so Python caches mem.pyc (a script run as __main__ is recompiled every time)."""

import sys

import mem

if __name__ == "__main__":
    sys.exit(mem.main())
