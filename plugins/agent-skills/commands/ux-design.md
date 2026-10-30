---
description: Plans and designs a UI, page or user flow with the ux-principles design workflow and turns acceptance criteria into Playwright checks.
argument-hint: <feature, screen or flow to design>
disable-model-invocation: true
---

Load the `agent-skills:ux-principles` skill and run its **design workflow** for: $ARGUMENTS

If no feature, screen or flow was given, ask for it in one question first.

Interview the owner with `AskUserQuestion` wherever users, tasks, constraints or content are unclear. Run steps 1–6 of the design workflow, deliver the design spec and the Playwright acceptance checks, then stop; run step 7 only when the owner says the UI is built. Write no application code unless asked.
