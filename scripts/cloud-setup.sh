#!/bin/bash
# Setup script for a Claude Code cloud environment (claude.ai/code → environment → Setup script).
# Cloud sessions don't install plugins declared in a repo, so install at user scope in the VM;
# the environment snapshot caches it for later sessions (~7 days, then the script runs again).
# Every step ends in `|| true`: a non-zero exit would stop the session from starting.

# 1. Add the marketplace from GitHub and install the plugin (user scope).
claude plugin install agent-skills --marketplace Mili-ssm/Agent-Skills || true

# 2. Turn on auto-update for this marketplace, so sessions started from a cached snapshot
#    pull new commits in the background (applied on the next session or /reload-plugins).
python3 - <<'EOF' || true
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
