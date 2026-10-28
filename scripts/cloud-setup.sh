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

# 1b. Opt-in mods (ADR 0011): list them in the environment variable AGENT_SKILLS_MODS,
#     e.g. AGENT_SKILLS_MODS="agents-pane status-model". Unset → no mods.
for mod in ${AGENT_SKILLS_MODS:-}; do
  claude plugin install "$mod" --marketplace Mili-ssm/Agent-Skills \
    || warn "mod $mod install failed"
done

# 2. Python Playwright for ux-principles/scripts/ux_audit.py. No browser download: the script
#    falls back to the image's pre-installed Chromium (/opt/pw-browsers/chromium).
python3 -m pip install --quiet --user playwright \
  || warn "python playwright install failed (ux_audit.py unavailable)"

# 3. Offload defaults (ADR 0010):
#    - Explore on Haiku: a user-scope agent named Explore overrides the built-in one, which
#      otherwise runs on the main conversation's model. Copied from the marketplace clone.
#    - CLAUDE_CODE_SUBAGENT_MODEL=sonnet: subagents without their own model (general-purpose,
#      Superpowers implementers) run on Sonnet; plugin agents keep their frontmatter model.
mkdir -p ~/.claude/agents
cp ~/.claude/plugins/marketplaces/mili-ssm/user-agents/Explore.md ~/.claude/agents/Explore.md \
  || warn "could not install the Haiku Explore override"

# 4. Turn on auto-update for this marketplace, so sessions started from a cached snapshot
#    pull new commits in the background (applied on the next session or /reload-plugins).
python3 - <<'EOF' || warn "could not update ~/.claude/settings.json (auto-update, subagent model)"
import json, pathlib
path = pathlib.Path.home() / ".claude" / "settings.json"
settings = json.loads(path.read_text()) if path.exists() else {}
entry = settings.setdefault("extraKnownMarketplaces", {}).setdefault(
    "mili-ssm", {"source": {"source": "github", "repo": "Mili-ssm/Agent-Skills"}}
)
entry["autoUpdate"] = True
settings.setdefault("env", {}).setdefault("CLAUDE_CODE_SUBAGENT_MODEL", "sonnet")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(settings, indent=2) + "\n")
EOF

exit 0
