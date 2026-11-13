import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Plan, PlanTask } from '../types'

// Slash command name.
const COMMAND = 'plan-progress'
// Folders where plans are written: Superpowers (current and older layouts), then a generic one.
const PLAN_DIRS = ['docs/superpowers/plans', 'docs/plans', 'plans']
// Bump the shape tag when Plan's fields change: an older stored plan is then read as absent.
const plan = atom({ plugin: 'plan-progress', key: 'plan' } as const, null, { shape: 'plan-2' })
const pinned = atom({ plugin: 'plan-progress', key: 'pinned' } as const, null)
// Haiku's words on what remains of the plan, for the plan state named by `key`.
const remaining = atom({ plugin: 'plan-progress', key: 'remaining' } as const, null)
// Haiku's instruction for the remaining-work line; it answers in the plan's own language.
const remainingPrompt = (unit: Plan['unit']): string =>
  `Below is a plan and its unfinished tasks (${unit === 'steps' ? 'done/total steps' : 'done/total subtasks, absent when none'}; the first one is the current task). In at most 16 ` +
  "words, in the same language as the plan, say what remains to be done. Reply with the phrase only, without " +
  'quotes or a final period.\n\n'

// `- [ ] step` / `* [x] step`, at any indentation.
const CHECKBOX = /^\s*[-*] \[([ xX])\]/
// `## Task 3: Title` / `### Step group`: a heading level 2-4 opens a task.
const HEADING = /^#{2,4}\s+(.+?)\s*#*\s*$/

/** The checkbox's text: the line without its list marker, on one line. */
const BOX_TEXT = /^\s*[-*] \[[ xX]\]\s*/

// Any list item, checkbox or not: `- text`, `* text`, `1. text`.
const LIST_ITEM = /^\s*(?:[-*+]|\d+[.)])\s/
// Opening or closing line of a fenced code block.
const FENCE = /^\s*(?:```|~~~)/

/** Indentation width of a line, a tab counting as 4. */
function indentOf(line: string): number {
  return (/^\s*/.exec(line)?.[0] ?? '').replace(/\t/g, '    ').length
}

/** True when a task is complete: a ticked top-level checkbox (task list) or all its steps. */
export function isTaskDone(task: PlanTask): boolean {
  return task.ticked ?? task.done >= task.total
}

/**
 * Task-list shape: each top-level checkbox (the smallest indentation among all checkboxes) is a task; the deeper
 * checkboxes after it are its subtasks. The plan counts tasks, not subtasks, so its total ignores subtask edits.
 */
function parseTaskList(path: string, title: string, lines: string[]): Plan {
  // Checkboxes inside fenced code are examples, not tasks.
  let fenced = false
  const body = lines.filter(line => {
    if (FENCE.test(line)) {
      fenced = !fenced
      return false
    }
    return !fenced
  })
  const boxes = body.filter(line => CHECKBOX.test(line))
  if (boxes.length === 0) {
    return { path, title, tasks: [], done: 0, total: 0, unit: 'tasks' }
  }
  const top = Math.min(...boxes.map(indentOf))
  const tasks: PlanTask[] = []
  let current: { task: PlanTask; level: number; subtasks: number; subtasksDone: number } | undefined
  const close = (): void => {
    if (current === undefined) {
      return
    }
    const { task, subtasks, subtasksDone } = current
    if (subtasks === 0) {
      tasks.push({ ...task, done: task.ticked === true ? 1 : 0, total: 1, solo: true })
    } else {
      tasks.push({ ...task, done: task.ticked === true ? subtasks : subtasksDone, total: subtasks })
    }
  }
  for (const line of body) {
    const box = CHECKBOX.exec(line)
    if (box === null) {
      // A plain list item no deeper than the task above it ends that task: checkboxes nested under it are tasks of their own.
      if (LIST_ITEM.test(line) && indentOf(line) <= (current?.level ?? top)) {
        close()
        current = undefined
      }
      continue
    }
    const ticked = box[1] !== ' '
    const indent = indentOf(line)
    // A checkbox no deeper than the task above it is a task too (its level is `top`, or deeper under a plain bullet).
    if (current === undefined || indent <= current.level) {
      close()
      current = { task: { title: line.replace(BOX_TEXT, '').trim(), done: 0, total: 0, ticked }, level: indent, subtasks: 0, subtasksDone: 0 }
    } else {
      current.subtasks += 1
      current.subtasksDone += ticked ? 1 : 0
    }
  }
  close()
  const done = tasks.filter(isTaskDone).length
  return { path, title, tasks, done, total: tasks.length, unit: 'tasks' }
}

/**
 * Parses a plan's Markdown. Two shapes: when two or more level 2-4 headings own checkboxes, each such heading is a
 * task and every checkbox a step (Superpowers); otherwise each top-level checkbox is a task (task list).
 * Checkboxes before any heading go to an unnamed task in the first shape. Pure, so it is unit-tested directly.
 */
export function parsePlan(path: string, text: string): Plan {
  const title = /^#\s+(.+)$/m.exec(text)?.[1]?.trim() ?? path.split('/').pop() ?? path
  const tasks: PlanTask[] = []
  let current: PlanTask = { title: '(no heading)', done: 0, total: 0 }
  let headed = 0
  const lines = text.split('\n')

  for (const line of lines) {
    const heading = HEADING.exec(line)
    if (heading?.[1] !== undefined) {
      if (current.total > 0) {
        tasks.push(current)
        headed += current.title === '(no heading)' ? 0 : 1
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
    headed += current.title === '(no heading)' ? 0 : 1
  }
  if (headed < 2 && tasks.length > 0) {
    return parseTaskList(path, title, lines)
  }

  const done = tasks.reduce((sum, task) => sum + task.done, 0)
  const total = tasks.reduce((sum, task) => sum + task.total, 0)
  return { path, title, tasks, done, total, unit: 'steps' }
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
  return plan.tasks.find(task => !isTaskDone(task))
}

/** True when every step of a plan with steps is done. */
export function isFinished(plan: Plan): boolean {
  return plan.total > 0 && plan.done === plan.total
}

/** The progress line as SVG, 2px high: a 1px track in the same color, faded, centred under a 2px fill for done/total, left to right. */
export function progressSvg(done: number, total: number, width: number, color: string): string {
  const fill = total === 0 ? 0 : (width * done) / total
  const bar = fill > 0 ? `<rect class="done" x="0" y="0" width="${fill.toFixed(2)}" height="2" rx="1" fill="${color}"/>` : ''
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="2" viewBox="0 0 ${width} 2" preserveAspectRatio="none">` +
    `<rect class="track" x="0" y="0.5" width="${width}" height="1" fill="${color}" fill-opacity="0.45"/>${bar}</svg>`
  )
}

/**
 * Haiku's reply cut to one usable phrase: its first non-empty line without quotes or a final period, or '' when
 * that line is the model thinking aloud ("Let me count…") or runs past 24 words, so the card never shows it.
 */
export function cleanPhrase(reply: string): string {
  const line = reply.split('\n').map(part => part.trim()).find(part => part !== '') ?? ''
  const phrase = line.replace(/^["'«“]+|["'»”.]+$/g, '')
  const isMeta =
    /^(let me|let's|wait\b|i (will|need|should|think)|okay|ok,|hmm|actually|word count|counting)/i.test(phrase) ||
    /\b(the instruction|the request says|reply with the phrase)\b/i.test(phrase)
  return isMeta || phrase.split(/\s+/).length > 24 ? '' : phrase
}

/** Tokens a phrase reply may use; a reply that used them all was probably cut and is dropped. */
export const PHRASE_TOKENS = 80

/** The usable phrase of a Haiku reply: '' when it is unanswered, cut by `maxTokens` or thinking aloud. */
export function phraseOf(reply: { isAnswered: boolean; text: string; usage?: { output_tokens?: number } }, maxTokens = PHRASE_TOKENS): string {
  const isCut = (reply.usage?.output_tokens ?? 0) >= maxTokens
  return reply.isAnswered && !isCut ? cleanPhrase(reply.text) : ''
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
    return isTaskDone(task) && before !== undefined && !isTaskDone(before)
  })
}

/**
 * Stores the plan (or null) and clears the status line that older versions set.
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
  $.ui.status(undefined)
  return finished
}

/** The key of a plan state: Haiku's description is asked again only when it changes. */
function remainingKey(plan: Plan): string {
  // A task list's plan count ignores subtasks, so the active task's own count joins the key.
  const active = plan.unit === 'tasks' ? activeTask(plan) : undefined
  return `${plan.path}:${plan.done}/${plan.total}${active === undefined ? '' : `:${active.done}/${active.total}`}`
}

// The key last asked about, so a refresh without change does not ask Haiku again.
let asked: string | undefined

/** Asks Haiku what remains and stores it; keeps the fallback line on a miss. Never throws. */
async function describeRemaining($: EngineInterface, plan: Plan, key: string): Promise<void> {
  try {
    const open = plan.tasks.filter(task => !isTaskDone(task))
    // A task without subtasks has no count of its own to show.
    const tasks = open.map(
      (task, index) => `- ${index === 0 ? '(current) ' : ''}${task.title}${task.solo === true ? '' : ` ${task.done}/${task.total}`}`,
    )
    const reply = await $.model.complete({
      model: 'haiku',
      prompt: `<plan>${plan.title}</plan>\n<unfinished_tasks>(done/total; the first is current)\n${tasks.join('\n')}</unfinished_tasks>\n\n${remainingPrompt(plan.unit)}`,
      maxTokens: PHRASE_TOKENS,
      timeoutMs: 15000,
    })
    const text = phraseOf(reply)
    // A newer plan state took over while Haiku answered: drop this text.
    if (text !== '' && asked === key) {
      await update($, remaining, () => ({ key, text }))
    }
  } catch (error) {
    $.ui.log(`plan-progress: ${String(error)}`, { to: 'debug' })
  }
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
  // Fire and forget: the card shows the fallback line until Haiku answers.
  const key = remainingKey(next)
  if (key !== asked) {
    asked = key
    if (!isFinished(next)) {
      void describeRemaining($, next, key)
    }
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
          : `Plan: ${current.path} (${current.done}/${current.total} ${current.unit}).`,
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

  // The card next to the prompt (no border). The band is shared:
  // other mods' cards (tool-fold's agents) stack below this one, from `next(e)`.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await read($, plan)
    const described = await read($, remaining)
    if (e.props.hasSurvey || current === null || current.total === 0) {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)
    const finished = isFinished(current)
    const color = finished ? 'success' : 'claude'
    const active = activeTask(current)
    const percent = `${Math.round((current.done / current.total) * 100)}%`
    const title = truncate(current.title, Math.max(16, e.props.bodyColumns - 26))
    const counts = (
      <>
        <Text color={color}>
          {finished ? '✓ ' : ''}
          {current.done}/{current.total} <Text dimColor>· {percent}</Text>
        </Text>
      </>
    )
    // Room left for the task title after the glyphs and counts.
    const room = Math.max(12, Math.min(60, e.props.bodyColumns - 12))
    const text = described !== null && described.key === remainingKey(current) ? described.text : undefined
    const taskLine =
      text !== undefined ? (
        <Text dimColor>▶ {truncate(text, room)}</Text>
      ) : active === undefined ? undefined : (
        <Text dimColor>
          ▶ {truncate(active.title, room)}
          {active.solo === true ? '' : ` · ${active.done}/${active.total}`}
        </Text>
      )

    const rest = await next(e)
    // The terminal has no Svg: it gets the glyph bar.
    if (e.surface !== 'terminal') {
      const { Svg } = $.ui.resolve(e)
      const hex = finished ? '#3fb950' : '#d97757'
      // A wider markup than any slot, stretched (preserveAspectRatio none) with no width prop: the line fills the card.
      const lineText = text !== undefined ? text : active === undefined ? undefined : `${active.title}${active.solo === true ? '' : ` · ${active.done}/${active.total}`}`
      // The band is one tree shared by every mod: cards from the mods beneath (tool-fold's agents) go first, the plan
      // after them, so what is running reads before what is planned.
      return (
        <Box flexDirection="column" gap={1}>
          {rest}
          <Box flexDirection="column">
          <Box gap={1}>
            <Text weight="bold" wrap="truncate-end">
              {current.title}
            </Text>
            {counts}
          </Box>
          <Svg
            source={progressSvg(current.done, current.total, 4000, hex)}
            alt={`${current.done} of ${current.total} ${current.unit} done`}
            height={2}
          />
          {lineText === undefined ? undefined : (
            <Text dimColor wrap="truncate-end">
              ▶ {lineText}
            </Text>
          )}
          </Box>
        </Box>
      )
    }

    return (
      <Box flexDirection="column" gap={1}>
        {rest}
        <Box flexDirection="column">
          <Box gap={1}>
            <Text color={color}>{glyphBar(current.done, current.total, 10)}</Text>
            <Text weight="bold">{title}</Text>
            {counts}
          </Box>
          {taskLine}
        </Box>
      </Box>
    )
  })
}
