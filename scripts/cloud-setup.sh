#!/bin/bash
# Setup script for a Claude Code cloud environment (claude.ai/code → environment → Setup script).
# Cloud sessions ignore plugins declared in a repo, so install at user scope in the VM; the
# environment snapshot caches it for later sessions (~7 days, then this script runs again).
# The script always exits 0 (a non-zero exit would stop the session from starting), but every
# failed step prints a WARN line so it shows up in the setup log instead of failing silently.
#
# Environment variables (all optional):
#   AGENT_SKILLS_MODS            mods to install, space-separated (ADR 0011), e.g. "tool-fold usage-band"
#   AGENT_SKILLS_OFFLOAD_POLICY  1 → write user-config/offload-policy.md into ~/.claude/CLAUDE.md (step 3b)

warn() { echo "WARN [cloud-setup]: $*" >&2; }

# Path of a file this repo ships, as the marketplace clone holds it ($1 is relative to the repo
# root): the known clone folder first, else the first match under ~/.claude/plugins, because the
# clone's folder name is Claude Code's choice. Prints nothing when the file is not there.
shipped_file() {
  local known="$HOME/.claude/plugins/marketplaces/mili-ssm/$1"
  if [ -f "$known" ]; then
    echo "$known"
  else
    find "$HOME/.claude/plugins" -path "*/$1" 2>/dev/null | head -1
  fi
}

# 1. Add the marketplace from GitHub and install the plugin (user scope).
claude plugin install agent-skills --marketplace Mili-ssm/Agent-Skills \
  || warn "agent-skills plugin install failed"

# 1b. Opt-in mods (ADR 0011): list them in the environment variable AGENT_SKILLS_MODS,
#     e.g. AGENT_SKILLS_MODS="tool-fold usage-band". Unset → no mods.
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
mkdir -p ~/.claude/agents || warn "could not create ~/.claude/agents"
explore=$(shipped_file user-agents/Explore.md)
if [ -n "$explore" ]; then
  cp "$explore" ~/.claude/agents/Explore.md || warn "could not install the Haiku Explore override"
else
  warn "user-agents/Explore.md not found under ~/.claude/plugins (Haiku Explore override not installed)"
fi

# 3b. Opt-in offload table (ADR 0010, 0012): AGENT_SKILLS_OFFLOAD_POLICY=1 writes
#     user-config/offload-policy.md into ~/.claude/CLAUDE.md between two marker lines. A later
#     run replaces that block, so edits to the table reach the environment; text outside the
#     markers is kept as it is. Off by default: the owner's account preferences already carry
#     the table, and a second copy would cost context twice.
if [ "${AGENT_SKILLS_OFFLOAD_POLICY:-}" = "1" ]; then
  policy=$(shipped_file user-config/offload-policy.md)
  if [ -n "$policy" ]; then
    python3 - "$policy" <<'EOF' || warn "could not write the offload policy into ~/.claude/CLAUDE.md"
import pathlib, re, sys

# The markers delimit the block this script owns; the begin line carries a note for readers.
BEGIN = "<!-- agent-skills:offload-policy:begin (written by scripts/cloud-setup.sh; the next run replaces everything up to the end marker) -->"
END = "<!-- agent-skills:offload-policy:end -->"
BEGIN_RE = r"<!-- agent-skills:offload-policy:begin\b[^\n]*?-->"

policy = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").strip()
if not policy:
    sys.exit("the offload policy file is empty")
path = pathlib.Path.home() / ".claude" / "CLAUDE.md"
text = path.read_text(encoding="utf-8") if path.exists() else ""
block = f"{BEGIN}\n{policy}\n{END}\n"

block_re = re.compile(BEGIN_RE + r".*?" + re.escape(END) + r"\n?", re.DOTALL)
blocks = len(block_re.findall(text))
if len(re.findall(BEGIN_RE, text)) != blocks or text.count(END) != blocks:
    sys.exit(f"unbalanced offload-policy markers in {path}; file left untouched")

first = block_re.search(text)
if first:  # replace the first block in place and drop any repeats
    text = text[: first.start()] + block + block_re.sub("", text[first.end():])
else:  # append after a blank line
    if text.strip():
        text += "\n" * max(0, 2 - (len(text) - len(text.rstrip("\n"))))
    else:
        text = ""
    text += block
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(text, encoding="utf-8")
EOF
  else
    warn "user-config/offload-policy.md not found under ~/.claude/plugins (offload policy not written)"
  fi
fi

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
