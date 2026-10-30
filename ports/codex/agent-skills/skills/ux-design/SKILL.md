---
name: "ux-design"
description: "Plans and designs a UI, page or user flow with the ux-principles design workflow and turns acceptance criteria into Playwright checks."
---

Arguments hint: <feature, screen or flow to design>

Load the `agent-skills:ux-principles` skill and run its **design workflow** for: <the arguments the user gave with this command; empty if none>

If no feature, screen or flow was given, ask for it in one question first.

Interview the owner with your tool for asking the user questions (or a direct question in chat) wherever users, tasks, constraints or content are unclear. Run steps 1–6 of the design workflow, deliver the design spec and the Playwright acceptance checks, then stop; run step 7 only when the owner says the UI is built. Write no application code unless asked.
