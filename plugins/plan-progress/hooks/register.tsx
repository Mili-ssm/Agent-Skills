import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Plan, PlanTask } from '../types'

// Slash command name.
const COMMAND = 'plan-progress'
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

/** `▰▰▰▰▰▱▱▱▱▱` for done/total over `width` cells: the compact glyph bar. */
export function glyphBar(done: number, total: number, width: number): string {
  const filled = total === 0 ? 0 : Math.round((done / total) * width)
  return '▰'.repeat(filled) + '▱'.repeat(width - filled)
}

/** Cuts a title to `max` characters, ending it with an ellipsis. */
export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`
}

/** The first unfinished task is the one in progress. */
export function activeTask(plan: Plan): PlanTask | undefined {
  return plan.tasks.find(task => task.done < task.total)
}

/** True when every step of a plan with steps is done. */
export function isFinished(plan: Plan): boolean {
  return plan.total > 0 && plan.done === plan.total
}

/** The one-line status: `▰▰▰▰▰▱▱▱▱▱ 5/10 · ▶ Task 3: Auth middleware 2/4`, or `✓ title 10/10` when finished. */
export function statusLine(plan: Plan): string {
  if (isFinished(plan)) {
    return `✓ ${truncate(plan.title, 40)} ${plan.done}/${plan.total}`
  }
  const active = activeTask(plan)
  const task = active === undefined ? '' : ` · ▶ ${truncate(active.title, 40)} ${active.done}/${active.total}`
  return `${glyphBar(plan.done, plan.total, 10)} ${plan.done}/${plan.total}${task}`
}

/** The ring as SVG: a track circle and an arc for done/total, starting at 12 o'clock. */
export function ringSvg(done: number, total: number, size: number, color: string): string {
  const stroke = 3
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const arc = total === 0 ? 0 : (done / total) * circumference
  const center = size / 2
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
    `<circle cx="${center}" cy="${center}" r="${radius}" fill="none" stroke="#888" stroke-opacity="0.3" stroke-width="${stroke}"/>` +
    `<circle cx="${center}" cy="${center}" r="${radius}" fill="none" stroke="${color}" stroke-width="${stroke}" ` +
    `stroke-linecap="round" stroke-dasharray="${arc.toFixed(2)} ${circumference.toFixed(2)}" ` +
    `transform="rotate(-90 ${center} ${center})"/></svg>`
  )
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

/** Tasks that reached their total between two reads of the same plan. */
function justFinished(previous: Plan | null, next: Plan | null): PlanTask[] {
  if (previous === null || next === null || previous.path !== next.path || next.done <= previous.done) {
    return []
  }
  return next.tasks.filter(task => {
    const before = previous.tasks.find(old => old.title === task.title)
    return task.done === task.total && before !== undefined && before.done < before.total
  })
}

/**
 * Stores the plan (or null) and mirrors it on the status line, the VS Code display.
 * Returns the tasks this write completed: judged against the value the update replaces, so two
 * overlapping refreshes never both see the same task as new.
 */
async function publish($: EngineInterface, next: Plan | null): Promise<PlanTask[]> {
  let finished: PlanTask[] = []
  // The updater may run again on a version miss: it only assigns, so the last run wins.
  await update($, plan, previous => {
    finished = justFinished(previous, next)
    return next
  })
  $.ui.status(next === null || next.total === 0 ? undefined : statusLine(next))
  return finished
}

/** Re-reads the active plan into state; toasts when a task has just been completed. */
async function refresh($: EngineInterface): Promise<void> {
  const path = (await read($, pinned)) ?? (await newestPlan($))
  const text = path === undefined ? undefined : await $.fs.read(path).catch(() => undefined)
  if (path === undefined || text === undefined) {
    await publish($, null)
    return
  }
  const next = parsePlan(path, text)
  // Same plan, more steps done: name the tasks that just reached their total.
  for (const task of await publish($, next)) {
    $.ui.toast(`✓ ${task.title} (${next.done}/${next.total})`)
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.command.register({
      name: COMMAND,
      description: 'Show plan progress; pass a path to pin a plan, or "auto" to follow the newest',
    })
    await refresh($)

    return started
  })

  // `/plan-progress` summarizes and refreshes; `/plan-progress <path>` pins a plan; `auto` unpins.
  on('command.run', { command: 'plan-progress' }, async ($, e) => {
    const arg = e.args.trim()
    if (arg !== '') {
      await update($, pinned, () => (arg === 'auto' ? null : arg))
    }
    await refresh($)
    const current = await read($, plan)

    return {
      text:
        current === null
          ? `No plan found (looked in ${PLAN_DIRS.join(', ')}).`
          : `Plan: ${current.path} (${current.done}/${current.total} steps).`,
    }
  }).catch(($, e, next) => next(e))

  // A plan file written or edited (by the main loop or a subagent): re-read it after the write.
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if ((e.tool === 'Edit' || e.tool === 'Write') && isPlanPath(e.file_path)) {
      await refresh($)
    }

    return ran
  }).catch(($, e, next) => next(e))

  // Catch edits made by other means (Bash, the person): re-read at the end of each main turn.
  on('turn.complete', async ($, e, next) => {
    const completed = await next(e)
    if (e.agentId === undefined) {
      await refresh($)
    }

    return completed
  })

  // The card next to the prompt (terminal and desktop); vscode shows the status line alone.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await read($, plan)
    if (e.props.hasSurvey || current === null || current.total === 0) {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)
    const finished = isFinished(current)
    const color = finished ? 'success' : 'claude'
    const active = activeTask(current)
    // Room left for the task title after the bar, counts and glyphs.
    const room = Math.max(12, Math.min(40, e.props.bodyColumns - 28))
    const taskLine =
      active === undefined ? undefined : (
        <Text dimColor>
          ▶ {truncate(active.title, room)} {glyphBar(active.done, active.total, 6)} {active.done}/{active.total}
        </Text>
      )

    // The terminal has no Svg: it gets the glyph card.
    if (e.surface !== 'terminal') {
      const { Svg } = $.ui.resolve(e)
      const hex = finished ? '#3fb950' : '#d97757'
      return (
        <Box borderStyle="round" borderColor={color} paddingX={1} gap={1}>
          <Svg
            source={ringSvg(current.done, current.total, 18, hex)}
            alt={`${current.done} of ${current.total} steps done`}
            width={18}
            height={18}
          />
          <Box flexDirection="column">
            <Box gap={1}>
              <Text weight="bold">{truncate(current.title, Math.max(16, e.props.bodyColumns - 24))}</Text>
              <Text color={color}>
                {current.done}/{current.total}
              </Text>
            </Box>
            {taskLine}
          </Box>
        </Box>
      )
    }

    return (
      <Box borderStyle="round" borderColor={color} paddingX={1} flexDirection="column">
        <Box gap={1}>
          <Text color={color}>{glyphBar(current.done, current.total, 10)}</Text>
          <Text weight="bold">{truncate(current.title, Math.max(16, e.props.bodyColumns - 26))}</Text>
          <Text color={color}>
            {current.done}/{current.total}
          </Text>
        </Box>
        {taskLine}
      </Box>
    )
  })
}
