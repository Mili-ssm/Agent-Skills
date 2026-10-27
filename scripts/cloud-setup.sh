#!/bin/bash
# Setup script for a Claude Code cloud environment (claude.ai/code → environment → Setup script).
# Cloud sessions ignore plugins declared in a repo, so install at user scope in the VM; the
# environment snapshot caches it for later sessions (~7 days, then this script runs again).
# The script always exits 0 (a non-zero exit would stop the session from starting), but every
# failed step prints a WARN line so it shows up in the setup log instead of failing silently.

warn() { echo "WARN [cloud-setup]: $*" >&2; }

# 1. Add the marketplace from GitHub and install the plugin (user scope).
claude plugin install agent-skills --marketplace Mili-ssm/Agent-Skills \
  || warn "agent-skills plugin install failed"

# 2. Python Playwright for ux-principles/scripts/ux_audit.py. No browser download: the script
#    falls back to the image's pre-installed Chromium (/opt/pw-browsers/chromium).
python3 -m pip install --quiet --user playwright \
  || warn "python playwright install failed (ux_audit.py unavailable)"

# 3. Turn on auto-update for this marketplace, so sessions started from a cached snapshot
#    pull new commits in the background (applied on the next session or /reload-plugins).
python3 - <<'EOF' || warn "could not enable marketplace auto-update"
import json, pathlib
path = pathlib.Path.home() / ".claude" / "settings.json"
settings = json.loads(path.read_text()) if path.exists() else {}
entry = settings.setdefault("extraKnownMarketplaces", {}).setdefault(
    "mili-ssm", {"source": {"source": "github", "repo": "Mili-ssm/Agent-Skills"}}
)
entry["autoUpdate"] = True
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(settings, indent=2) + "\n")
EOF

exit 0
