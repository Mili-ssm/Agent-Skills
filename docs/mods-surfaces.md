# Mods on each surface: field notes

What the mods (`tool-fold`, `usage-band`, `plan-progress`) do on the Desktop app, VS Code and the terminal, learned by trying; findings that failed are kept too.

Status labels:

| Label | Meaning |
|---|---|
| **observed** | Seen on the real surface (owner's screenshot) |
| **documented** | Stated in the mods API types or reference (`plugin-authoring` skill) |
| **tested** | Passes in `claude plugin test` only; the test kit does not reproduce the surface |
| **inferred** | Explains what was observed, not confirmed directly |
| **open** | Not working yet, or not understood |
| **diagnostic** | A command that reports what a surface does, to settle an open row |

Add a row whenever a surface surprises us: what was tried, what happened, why (or "unknown"), and the PR.

---

## Where mods run at all

| Finding | Status |
|---|---|
| Mods draw only where the session runs (the local terminal, VS Code or Desktop on that machine). A cloud session, or a Remote Control viewer, shows none of them | observed |
| Desktop needs v2.1.286 or later and carries its own Claude Code: plugins are installed there separately from the CLI | observed |
| Desktop's console has no `claude` command, so `claude plugin update` cannot be run for it | observed |
| A third-party marketplace does not auto-update. On Desktop, updating left the first installed copy in place; uninstall and reinstall loaded the new one | observed |
| After a reinstall, open a new session (or expect the old module state to be gone) | inferred |

---

## Render sites per surface

| Site | Terminal | VS Code | Desktop |
|---|---|---|---|
| `ToolUse` / `ToolResult` rows | yes | yes | yes, `$.ui.log` rows drawn as dim lines prefixed with the plugin name (observed) |
| `Pane` | docked in fullscreen, inline otherwise (documented) | inline, above the prompt, in the narrow panel (observed) | docked in a column right of the chat, titled with the pane `title` (observed) |
| `AbovePrompt` | yes (documented) | **not raised** (documented) | yes: the usage-band card draws (observed, PR #28) |
| Status line (`$.ui.status`) | bottom line | bottom line | a small footer line; usage-band leaves it empty when Desktop is the only surface (PR #28) |
| `CommandOutput` | text | text | text; `Svg` is available (PR #28) |

---

## Layout and text

| Finding | Status | PR |
|---|---|---|
| Desktop and VS Code draw text in a proportional font: about 1.5 characters fit per cell, so clipping uses `bodyColumns × 1.5` there and `bodyColumns` on the terminal | observed (tuned by eye) | #26, #27 |
| VS Code does not shrink a `Box` inside a row: a long child wraps under the prefix, which split lines right after `└`. Fix: one `Text` per line with nested glyph `Text`s, pre-clipped to the width | observed | #27 |
| Desktop's font turns `▇▁` glyph bars into blocks. Fix: draw the bars as `Svg` images on Desktop | observed | #28 |
| Desktop draws `Box` `borderStyle: 'round'` with theme colors (`claude`, `success`), `Text` `weight`, `italic`, `size: 'footnote'` and `tabular` | observed | #28 |
| Desktop sizes a row `Box` to its content: `justifyContent: 'space-between'` did not push the usage-band `Σ` to the right edge | observed | #29 |
| Adding `width: '100%'` on that row and `flexGrow: 1` on its left group was followed by `Σ` not showing at all. Cause not isolated: the reinstall may have reset the session total, which hides `Σ` on a first cycle. Reverted | observed, cause **open** | #30, reverted in #31 |

---

## Panes and the agent band on Desktop

| Finding | Status | PR |
|---|---|---|
| `$.ui.open` unasked opens the pane beside the chat on Desktop | observed | #28 |
| Background agents (`run_in_background`) show no chat row while they run; Desktop lists them natively under "Tareas en segundo plano" | observed | — |
| Closing Desktop's docked pane with its own ✕: the mod's `ui.close` hook seemed not to run (a band gated on a `docked` atom cleared by `ui.close` never showed) | inferred | #28, #29 |
| Gating the band on `$.ui.panes()` (`isShown && isPlaced`) did not show it either after closing: the engine probably still lists the pane as shown | inferred | #29 |
| With no pane opened on Desktop and the band drawn whenever agents run, the agent cards **still did not show** above the prompt, while the usage-band card did. `/agents-dock` opened the pane with the cards, so the runs were tracked as running | observed, **open** | #30 |
| `/agents-debug` (tool-fold) lists the surfaces, the panes the engine records, the runs and the band's latest draws with `next.trace` (what each link beneath answered), to find out whether the band hook runs on Desktop and what happens to its tree | diagnostic | #31 |

Hypotheses still open for the missing agent band, to check with `/agents-debug`:

1. The hook does not run for tool-fold on Desktop (no "band draws" lines).
2. It runs but sees no running agents or a survey (`running=0`, `survey=true`).
3. It draws, but its tree is dropped above it (another link's outcome in the trace, or a failure line).

---

## Engine facts that shaped the mods

| Fact | Status |
|---|---|
| A render hook may not write state; module variables are lost on a hot reload | documented |
| A hook has a 10 s budget per dispatch; a `.catch` handler a 1 s grace | documented |
| `next.trace` lists each link beneath with its plugin, tier and outcome (`returned`, `passed`, `caught`, `skipped`...) | documented |
| Hooks of the same event nest by tier (`prepend`, `user`, `append`, `builtin`, `core`); same-tier order is not documented | documented |
| Reading an atom while drawing subscribes the instance: a later write redraws it | documented |

## Test kit gaps

| Gap | Workaround |
|---|---|
| `session.surfaces` must be stubbed (`on('session.surfaces', …)`) | default `['vscode']` in usage-band tests |
| `ui.render` beneath the plugin must return an element | `on('ui.render', ($, e) => $.ui.resolve(e).Box({}))` |
| No `$.ui.close` | stub `ui.panes` with a mutable list |
| Hooks beneath (`on('ui.panes', …)`, …) must be registered before the test's first `$` call | register every stub at the top of the test |
| No surface reproduces Desktop's or VS Code's layout | screenshots from the owner; this file |
