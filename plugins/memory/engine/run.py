#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.15"  # keep in step with mem.py
# dependencies = ["pyyaml"]
# ///
"""Launcher of the `bin/` commands: `run.py --bin NAME ...` runs the entry of one launcher; anything else runs `mem`.

`mem` is imported only for the default path, so Python caches mem.pyc (a script run as __main__ is recompiled every time).
"""

import sys

if __name__ == "__main__":
    # One static import per name, so the import graph sees each edge; the other entries stay unloaded.
    name = sys.argv[2] if sys.argv[1:2] == ["--bin"] and sys.argv[2:3] else ""
    if name == "mem-auto":
        from entry import auto

        main = auto.main
    elif name == "mem-capture":
        from entry import capture

        main = capture.main
    elif name == "mem-corroborate":
        from entry import corroborate

        main = corroborate.main
    elif name == "mem-research":
        from entry import research

        main = research.main
    elif name == "mem-settle":
        from entry import settle

        main = settle.main
    elif name == "mem-synthesize":
        from entry import synthesize

        main = synthesize.main
    elif sys.argv[1:2] == ["--bin"]:
        print(f"run.py: unknown --bin name: {name!r}", file=sys.stderr)
        sys.exit(2)
    else:
        import mem

        main = mem.main
    if name:
        sys.argv = [name, *sys.argv[3:]]
    sys.exit(main())
