// State contract of the plan-progress mod: what it keeps in `$.state` (survives hot reloads).

/** One task of a plan: a heading with checkbox steps under it. */
export type PlanTask = {
  title: string
  done: number
  total: number
}

/** The active plan as parsed from its Markdown file. */
export type Plan = {
  /** Path relative to the working directory. */
  path: string
  /** The file's first `# ` heading, else its file name. */
  title: string
  tasks: PlanTask[]
  done: number
  total: number
}

declare module 'claude-code' {
  interface PluginState {
    'plan-progress': {
      plan: Shaped<Plan | null>
      /** Path set with `/plan-progress <path>`; null follows the newest plan. */
      pinned: string | null
    }
  }
}
