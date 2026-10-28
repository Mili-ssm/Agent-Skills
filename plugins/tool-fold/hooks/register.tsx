import { atom, memberOf, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { GroupCall, ToolRun } from '../types'

// Calls drawn as the engine draws them: an Agent call is agents-pane's card.
const UNTOUCHED = new Set(['Agent'])
// One value per call: a press redraws that row alone, not every row in the chat.
const isOpen = atom({ plugin: 'tool-fold', key: 'isOpen' } as const, false)
// Which group a call is in ('' for none), and each group: read per row, so a change redraws its own rows.
const groupOf = atom({ plugin: 'tool-fold', key: 'groupOf' } as const, '')
const group = atom({ plugin: 'tool-fold', key: 'group' } as const, null)
const current = atom({ plugin: 'tool-fold', key: 'current' } as const, null)
// A run shorter than this stays as single folded rows.
const MIN_GROUP = 2

// Asks Haiku for the line that names a whole run of calls.
const SUMMARY_PROMPT =
  'Estas son las herramientas que un asistente de programación acaba de ejecutar seguidas. ' +
  'Resume en una sola frase corta (máximo 12 palabras), en español llano, qué estaba haciendo con ellas. ' +
  'Responde solo con la frase, sin comillas ni punto final.\n\n'

/** Cuts `text` to `max` characters with an ellipsis. */
const clip = (text: string, max: number): string =>
  text.length <= max ? text : `${text.slice(0, max - 1)}…`

/** Last path segment: `src/app/main.py` → `main.py`. */
const base = (path: string): string => path.split('/').filter(Boolean).pop() ?? path

/** What a folded row says a call does: the model's own description where it gave one. */
export function foldLabel(tool: string, input: unknown): string {
  const fields = typeof input === 'object' && input !== null ? (input as Record<string, unknown>) : {}
  const text = (key: string): string => (typeof fields[key] === 'string' ? (fields[key] as string) : '')
  if (text('description') !== '') {
    return clip(text('description'), 80)
  }
  switch (tool) {
    case 'Read':
    case 'Edit':
    case 'Write':
      return base(text('file_path'))
    case 'NotebookEdit':
      return base(text('notebook_path'))
    case 'Grep':
    case 'Glob':
      return clip(text('pattern'), 60)
    case 'Bash':
      return clip(text('command').split('\n')[0] ?? '', 80)
    case 'WebSearch':
      return clip(text('query'), 60)
    case 'WebFetch':
      return clip(text('url').replace(/^https?:\/\//, ''), 60)
    case 'Skill':
      // Which skill, and with what it was asked to work.
      return clip([text('skill'), text('args')].filter(Boolean).join(' · '), 80)
    default: {
      // Any other tool: its first short text field says the most.
      const first = Object.values(fields).find(value => typeof value === 'string' && value.trim() !== '')
      return typeof first === 'string' ? clip(first.split('\n')[0] ?? '', 60) : ''
    }
  }
}

/** `mcp__github__get_file` → `github get_file`. */
const toolName = (tool: string): string => tool.replace(/^mcp__/, '').replace(/__/g, ' ')

// Distinct names a group line shows before `…`.
const MAX_TAGS = 5

/**
 * `qa-review · ux-review · Bash · Read`: each skill by its name, then each other tool, once,
 * in order of first use; skills first, as they say more. Past MAX_TAGS names, `…`.
 */
export function toolTally(calls: readonly Pick<GroupCall, 'tool' | 'label'>[]): string {
  const skills = new Set<string>()
  const tools = new Set<string>()
  for (const call of calls) {
    if (call.tool === 'Skill') {
      // The label starts with the skill's name: `agent-skills:qa-review · explorer page`.
      skills.add((call.label.split(' · ')[0] ?? '').replace(/^[\w-]+:/, '') || 'Skill')
    } else {
      tools.add(toolName(call.tool))
    }
  }
  const names = [...skills, ...tools]
  return names.length > MAX_TAGS ? `${names.slice(0, MAX_TAGS).join(' · ')} · …` : names.join(' · ')
}

/** The dot of a row or a group: live, failed, interrupted or fine. */
const dotColor = (status: 'running' | 'done' | 'failed' | 'interrupted'): string =>
  status === 'running' ? 'claude' : status === 'failed' ? 'error' : status === 'interrupted' ? 'warning' : 'success'

/** Closes the run new calls join; a run long enough gets its Haiku line. Never throws. */
async function closeRun($: EngineInterface): Promise<void> {
  try {
    const id = await read($, current)
    if (id === null) {
      return
    }
    await update($, current, () => null)
    const run = await update($, memberOf(group, { requestId: id }), value => (value === null ? null : { ...value, isClosed: true }))
    if (run !== null && run.calls.length >= MIN_GROUP) {
      void writeSummary($, run).catch(error => $.ui.log(`tool-fold: summary: ${String(error)}`, { to: 'debug' }))
    }
  } catch (error) {
    $.ui.log(`tool-fold: ${String(error)}`, { to: 'debug' })
  }
}

/** What one reply row does to the runs, block by block: a call joins, reply text or an Agent call closes. */
export function runSteps(content: readonly unknown[]): ({ close: true } | { join: GroupCall })[] {
  const steps: ({ close: true } | { join: GroupCall })[] = []
  for (const item of content) {
    const block = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    const name = typeof block.name === 'string' ? block.name : ''
    if (block.type === 'text' && typeof block.text === 'string' && block.text.trim() !== '') {
      steps.push({ close: true })
    } else if (block.type === 'tool_use' && typeof block.id === 'string') {
      steps.push(
        UNTOUCHED.has(name)
          ? { close: true }
          : { join: { id: block.id, tool: name, label: foldLabel(name, block.input), status: 'running' } },
      )
    }
  }
  return steps
}

/** Adds a call to the open run, or starts one with it. */
async function joinRun($: EngineInterface, call: GroupCall): Promise<void> {
  const open = await read($, current)
  const id = open ?? `g-${call.id}`
  if (open === null) {
    await update($, current, () => id)
  }
  await update($, memberOf(group, { requestId: id }), value =>
    value === null ? { id, calls: [call], isClosed: false } : { ...value, calls: [...value.calls, call] },
  )
  await update($, memberOf(groupOf, { requestId: call.id }), () => id)
}

/** Sets one call's status inside its group. */
async function markCall($: EngineInterface, callId: string, status: GroupCall['status']): Promise<void> {
  const id = await read($, memberOf(groupOf, { requestId: callId }))
  if (id !== '') {
    await update($, memberOf(group, { requestId: id }), value =>
      value === null ? null : { ...value, calls: value.calls.map(call => (call.id === callId ? { ...call, status } : call)) },
    )
  }
}

/** Asks Haiku for one sentence naming what a run of calls did. */
async function writeSummary($: EngineInterface, run: ToolRun): Promise<void> {
  const list = run.calls.map(call => `- ${toolName(call.tool)}: ${call.label}`).join('\n')
  const reply = await $.model.complete({
    model: 'haiku',
    prompt: SUMMARY_PROMPT + list.slice(0, 4000),
    maxTokens: 60,
    timeoutMs: 20000,
  })
  if (reply.isAnswered && reply.text.trim() !== '') {
    const summary = clip(reply.text.trim().replace(/^["'«“]+|["'»”.]+$/g, ''), 100)
    await update($, memberOf(group, { requestId: run.id }), value => (value === null ? null : { ...value, summary }))
  }
}

export const register: Register = on => {
  // The model's reply, block by block in order: tool calls join a run, its text or an Agent call ends it.
  on('session.append', async ($, e, next) => {
    const kept = await next(e)
    if (e.agentId !== undefined) {
      return kept
    }
    if (e.door === 'prompt') {
      await closeRun($)
    }
    if (e.door === 'response') {
      for (const step of runSteps(e.message.content)) {
        await ('join' in step ? joinRun($, step.join) : closeRun($))
      }
    }

    return kept
    // A failing hook leaves the row as the engine keeps it.
  }).catch(($, e, next) => next(e))

  // Each main-loop call's outcome, for the group's dot.
  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined && !UNTOUCHED.has(e.tool)) {
      const status = result.deny !== undefined || result.isError === true ? 'failed' : 'done'
      await markCall($, e.tool_use_id, status).catch(() => undefined)
    }

    return result
  }).catch(($, e, next) => next(e))

  // The main loop's turn ended: its last run is complete.
  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) {
      await closeRun($)
    }

    return next(e)
  })

  // A call's row: alone, one folded line; in a group, the first row draws the group and the rest
  // show only while it is unfolded. Each line's arrow unfolds the engine's own row under it.
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    if (UNTOUCHED.has(e.props.tool) || e.props.isExpanded === true) {
      return next(e)
    }
    const { Box, Button, Text } = $.ui.resolve(e)
    const open = memberOf(isOpen, e)
    const isUnfolded = await read($, open)
    const groupId = await read($, memberOf(groupOf, e))
    const run = groupId === '' ? null : await read($, memberOf(group, { requestId: groupId }))
    const isGrouped = run !== null && run.calls.length >= MIN_GROUP

    const status = e.props.isRunning
      ? 'running'
      : e.props.isErrored
        ? 'failed'
        : e.props.isInterrupted
          ? 'interrupted'
          : 'done'
    // Only the arrow is pressable: a one-glyph Button is a control by itself.
    const line = (
      <Box key={`row-${e.requestId}`} flexDirection="row" gap={1} alignItems="center">
        <Button
          key={`fold-${e.requestId}`}
          plain
          dimColor
          label={isUnfolded ? '▾' : '▸'}
          onPress={() => update($, open, value => !value)}
        />
        <Text color={dotColor(status)}>●</Text>
        <Text backgroundColor="inactive" color="inverseText">
          {` ${toolName(e.props.tool)} `}
        </Text>
        <Text dimColor wrap="truncate">
          {foldLabel(e.props.tool, e.props.input)}
        </Text>
      </Box>
    )
    const own = isUnfolded ? (
      <Box key={`own-${e.requestId}`} flexDirection="column">
        {line}
        {await next(e)}
      </Box>
    ) : (
      line
    )
    if (!isGrouped || run === null) {
      return own
    }

    const groupOpen = memberOf(isOpen, { requestId: run.id })
    const isGroupOpen = await read($, groupOpen)
    if (run.calls[0]?.id !== e.props.tool_use_id) {
      // A later call of the group: shown only while the group is unfolded, indented under it.
      return isGroupOpen ? <Box paddingLeft={2}>{own}</Box> : <Box />
    }

    const groupStatus = run.calls.some(call => call.status === 'running')
      ? 'running'
      : run.calls.some(call => call.status === 'failed')
        ? 'failed'
        : 'done'
    const header = (
      <Box key={`group-${run.id}`} flexDirection="row" gap={1} alignItems="center">
        <Button
          key={`fold-${run.id}`}
          plain
          dimColor
          label={isGroupOpen ? '▾' : '▸'}
          onPress={() => update($, groupOpen, value => !value)}
        />
        <Text color={dotColor(groupStatus)}>●</Text>
        <Text backgroundColor="inactive" color="inverseText">
          {` ${toolTally(run.calls)} `}
        </Text>
        <Text dimColor wrap="truncate">
          {run.summary ?? (run.isClosed ? `${run.calls.length} calls` : 'Working…')}
        </Text>
      </Box>
    )
    return (
      <Box flexDirection="column">
        {header}
        {isGroupOpen ? <Box paddingLeft={2}>{own}</Box> : null}
      </Box>
    )
  })

  // A standalone row's result block follows its call (same requestId): shown only while its line is.
  on('ui.render', { component: 'ToolResult' }, async ($, e, next) => {
    if (UNTOUCHED.has(e.props.tool)) {
      return next(e)
    }
    const isUnfolded = await read($, memberOf(isOpen, e))
    const groupId = await read($, memberOf(groupOf, e))
    const run = groupId === '' ? null : await read($, memberOf(group, { requestId: groupId }))
    const isHiddenByGroup =
      run !== null && run.calls.length >= MIN_GROUP && !(await read($, memberOf(isOpen, { requestId: run.id })))
    if (isUnfolded && !isHiddenByGroup) {
      return next(e)
    }
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
}
