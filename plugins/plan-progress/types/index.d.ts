// State contract of the plan-progress mod: what it keeps in `$.state` (survives hot reloads).

/** One task of a plan: a heading with checkbox steps under it, or a top-level checkbox with its subtasks. */
export type PlanTask = {
  title: string
  /** Steps (or subtasks) ticked. */
  done: number
  total: number
  /** Task-list shape only: the top-level checkbox itself is ticked. */
  ticked?: boolean
  /** Task-list shape only: the task has no subtasks, so `done/total` is not its own progress. */
  solo?: boolean
}

/** The active plan as parsed from its Markdown file. */
export type Plan = {
  /** Path relative to the working directory. */
  path: string
  /** The file's first `# ` heading, else its file name. */
  title: string
  tasks: PlanTask[]
  /** What `done` and `total` count: steps under headings, or top-level tasks of a task list. */
  unit: 'steps' | 'tasks'
  done: number
  total: number
}

declare module 'claude-code' {
  interface PluginState {
    'plan-progress': {
      plan: Shaped<Plan | null>
      /** Path set with `/plan-progress <path>`; null follows the newest plan. */
      pinned: string | null
      /** Haiku's description of what remains, for the plan state `key` (`path:done/total`). */
      remaining: { key: string; text: string } | null
    }
  }
}
