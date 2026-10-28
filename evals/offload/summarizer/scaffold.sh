#!/bin/bash
# ~3000-line log with one real root cause buried in the middle.
set -e
python3 - <<'PY'
lines = []
for i in range(1500):
    lines.append(f"2026-10-28T10:{i//60:02d}:{i%60:02d}Z INFO step={i} compiling module_{i%40} ok")
lines.append("2026-10-28T10:25:00Z ERROR migrate: relation \"orders\" already exists (migration 0042_add_orders)")
lines.append("2026-10-28T10:25:01Z ERROR deploy aborted: database migration failed")
for i in range(1500):
    lines.append(f"2026-10-28T10:26:{i%60:02d}Z INFO cleanup step={i} ok")
open("build.log", "w").write("\n".join(lines) + "\n")
PY
