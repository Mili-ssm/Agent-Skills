import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Plan, PlanTask } from '../types'

// Pane id, also the slash command that opens it.
const PANE = 'plan-progress'
// Folders where plans are written: Superpowers (current and older layouts), then a generic one.
const PLAN_DIRS = ['docs/superpowers/plans', 'docs/plans', 'plans']
// Bump the shape tag when Plan's fields change: an older stored plan is then read as absent.
const plan = atom({ plugin: 'plan-progress', key: 'plan' } as const, null, { shape: 'plan-1' })
const pinned = atom({ plugin: 'plan-progress', key: 'pinned' } as const, null)

// `- [ ] step` / `* [x] step`, at any indentation.
const CHECKBOX = /^\s*[-*] \[([ xX])\]/
// `## Task 3: Title` / `### Step group`: a heading level 2-4 opens a task.
const HEADING = /^#{2,4}\s+(.+?)\s*#*\s*$/

/**
 * Parses a plan's Markdown: each level 2-4 heading that has checkbox steps under it is a task.
 * Checkboxes before any heading go to an unnamed task. Pure, so it is unit-tested directly.
 */
export function parsePlan(path: string, text: string): Plan {
  const title = /^#\s+(.+)$/m.exec(text)?.[1]?.trim() ?? path.split('/').pop() ?? path
  const tasks: PlanTask[] = []
  let current: PlanTask = { title: '(no heading)', done: 0, total: 0 }

  for (const line of text.split('\n')) {
    const heading = HEADING.exec(line)
    if (heading?.[1] !== undefined) {
      if (current.total > 0) {
        tasks.push(current)
      }
      current = { title: heading[1], done: 0, total: 0 }
      continue
    }
    const box = CHECKBOX.exec(line)
    if (box !== null) {
      current.total += 1
      current.done += box[1] === ' ' ? 0 : 1
    }
  }
  if (current.total > 0) {
    tasks.push(current)
  }

  const done = tasks.reduce((sum, task) => sum + task.done, 0)
  const total = tasks.reduce((sum, task) => sum + task.total, 0)
  return { path, title, tasks, done, total }
}

/** `███████░░░░░░░` for done/total over `width` cells. */
export function bar(done: number, total: number, width: number): string {
  const filled = total === 0 ? 0 : Math.round((done / total) * width)
  return '█'.repeat(filled) + '░'.repeat(width - filled)
}

/** True when the path is inside one of the plan folders. */
export function isPlanPath(path: string): boolean {
  return PLAN_DIRS.some(dir => path.includes(`${dir}/`)) && path.endsWith('.md')
}

/** Newest `.md` across the plan folders, or undefined when there is none. */
async function newestPlan($: EngineInterface): Promise<string | undefined> {
  let best: { path: string; mtimeMs: number } | undefined
  for (const dir of PLAN_DIRS) {
    // A missing folder rejects: treat it as empty.
    const entries = await $.fs.list(dir).catch(() => [])
    for (const entry of entries) {
      if (entry.kind === 'file' && entry.name.endsWith('.md')) {
        if (best === undefined || entry.mtimeMs > best.mtimeMs) {
          best = { path: `${dir}/${entry.name}`, mtimeMs: entry.mtimeMs }
        }
      }
    }
  }
  return best?.path
}

/** Re-reads the active plan into state; toasts when a task has just been completed. */
async function refresh($: EngineInterface): Promise<void> {
  const path = (await read($, pinned)) ?? (await newestPlan($))
  if (path === undefined) {
    await update($, plan, () => null)
    return
  }
  const text = await $.fs.read(path).catch(() => undefined)
  if (text === undefined) {
    await update($, plan, () => null)
    return
  }
  const next = parsePlan(path, text)
  const previous = await read($, plan)

  // Same plan, more steps done: name the tasks that just reached their total.
  if (previous !== null && previous.path === next.path && next.done > previous.done) {
    const finished = next.tasks.filter(task => {
      const before = previous.tasks.find(old => old.title === task.title)
      return task.done === task.total && before !== undefined && before.done < before.total
    })
    for (const task of finished) {
      $.ui.toast(`✓ ${task.title} (${next.done}/${next.total})`)
    }
  }
  await update($, plan, () => next)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.command.register({
      name: PANE,
      description: 'Show plan progress; pass a path to pin a plan, or "auto" to follow the newest',
    })
    await refresh($)
    // Open the pane only when there is a plan to show.
    if ((await read($, plan)) !== null) {
      void $.ui.open({ id: PANE, title: 'Plan' })
    }

    return started
  })

  // `/plan-progress` opens the pane; `/plan-progress <path>` pins a plan; `auto` unpins.
  on('command.run', { command: PANE }, async ($, e) => {
    const arg = e.args.trim()
    if (arg !== '') {
      await update($, pinned, () => (arg === 'auto' ? null : arg))
    }
    await refresh($)
    await $.ui.open({ id: PANE, title: 'Plan' })
    const current = await read($, plan)

    return {
      text:
        current === null
          ? `No plan found (looked in ${PLAN_DIRS.join(', ')}).`
          : `Plan: ${current.path} (${current.done}/${current.total} steps).`,
    }
  })

  // A plan file written or edited (by the main loop or a subagent): re-read it after the write.
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if ((e.tool === 'Edit' || e.tool === 'Write') && isPlanPath(e.file_path)) {
      await refresh($)
    }

    return ran
  })

  // Catch edits made by other means (Bash, the person): re-read at the end of each main turn.
  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) {
      await refresh($)
    }

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const current = await read($, plan)

    if (current === null) {
      return <Text dimColor>No plan yet. Plans are read from {PLAN_DIRS.join(', ')}.</Text>
    }

    const percent = current.total === 0 ? 0 : Math.round((current.done / current.total) * 100)
    const width = Math.max(10, Math.min(30, e.props.bodyColumns - 12))
    // The first unfinished task is the one in progress.
    const active = current.tasks.findIndex(task => task.done < task.total)

    return (
      <Box flexDirection="column">
        <Text weight="bold">{current.title}</Text>
        <Text>
          {bar(current.done, current.total, width)} {current.done}/{current.total} ({percent}%)
        </Text>
        <Text dimColor>{current.path}</Text>
        {current.tasks.map((task, index) => (
          <Text key={`task-${index}`} dimColor={index !== active}>
            {task.done === task.total ? '✓' : index === active ? '▶' : '·'} {task.title}
            {task.done === task.total ? '' : ` ${task.done}/${task.total}`}
          </Text>
        ))}
      </Box>
    )
  })
}
