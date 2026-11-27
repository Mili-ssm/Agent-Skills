#!/usr/bin/env bash
# SessionStart hook: prints the memory plugin's offload table (../user-config/offload-policy.md, read in place) as
# plain standard output, which Claude Code adds to the context.
# Silent, and always exit 0, whatever happens: a failing hook would disturb every session.
# Silent when (one line each):
#  1. the option offload_table is exactly "false" (an untouched option leaves the variable unset, so the default is on);
#  2. inside `claude plugin eval` (CLAUDE_CODE_EVAL_CONFINED set, even empty) unless EVAL_OFFLOAD_HOOK is exactly "on";
#  3. $CLAUDE_CONFIG_DIR/CLAUDE.md (else $HOME/.claude/CLAUDE.md) holds the table heading as an exact line.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || exit 0
if [ "${MEM_HOST:-}" = codex ]; then
  . "$here/codex-options.sh" 2>/dev/null
  type codex_options >/dev/null 2>&1 && codex_options
  [ "${CLAUDE_PLUGIN_OPTION_OFFLOAD_TABLE:-}" = "true" ] || exit 0
  config="${CODEX_HOME:-${HOME:+$HOME/.codex}}"
  if [ -n "$config" ] && grep -qxF '### Offload policy: memory plugin (main conversation only)' "$config/AGENTS.md" 2>/dev/null; then
    exit 0
  fi
  [ -r "$here/../user-config/offload-policy.md" ] || exit 0
  sed \
    -e 's/memory:memory-/memory-/g' \
    -e 's/, in the background (when the owner asked, wait for its card before answering); ask it follow-up questions with `SendMessage`/ (when the owner asked, wait for its card before answering)/' \
    -e 's/, in the background, without asking first/, without asking first/' \
    "$here/../user-config/offload-policy.md" 2>/dev/null
  printf '\nUse a listed role when available. If it is unavailable, do that work inline with mem.\n'
  exit 0
fi
[ "${CLAUDE_PLUGIN_OPTION_OFFLOAD_TABLE:-}" = "false" ] && exit 0
[ -n "${CLAUDE_CODE_EVAL_CONFINED+x}" ] && [ "${EVAL_OFFLOAD_HOOK:-}" != "on" ] && exit 0
config="${CLAUDE_CONFIG_DIR:-${HOME:+$HOME/.claude}}"
if [ -n "$config" ] && grep -qxF '### Offload policy: memory plugin (main conversation only)' "$config/CLAUDE.md" 2>/dev/null; then
  exit 0
fi
[ -r "$here/../user-config/offload-policy.md" ] && cat "$here/../user-config/offload-policy.md" 2>/dev/null
exit 0
