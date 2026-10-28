import { atom, memberOf, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderNode } from 'claude-code'

import type { GroupCall, ToolRun } from '../types'
import { agentCard, endAgentCall, endAgentTurn, isAgentLive, noticeCard, registerAgents, startAgentCall } from './agents'

// Calls drawn as the engine draws them, which also end a run: a question is the person's turn.
const UNTOUCHED = new Set(['AskUserQuestion'])
// Calls the engine itself folds into a count line (its ToolGroup), where no ToolUse row is drawn:
// they never join a run, or a run's header would sit on a row that never shows.
const ENGINE_FOLDED = new Set(['Read', 'Grep', 'Glob', 'LS'])
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
    case 'SendMessage':
      // The summary says what was sent; the address alone (an agent id) says nothing.
      return clip(text('summary') || (text('message').split('\n')[0] ?? '') || text('to'), 80)
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

/** The name a group line lists a call by: the skill's or the agent type's, without its plugin prefix. */
export function tagOf(tool: string, input: unknown): string {
  const fields = typeof input === 'object' && input !== null ? (input as Record<string, unknown>) : {}
  const named = tool === 'Skill' ? fields.skill : tool === 'Agent' ? fields.subagent_type : undefined
  return typeof named === 'string' && named !== '' ? named.replace(/^[\w-]+:/, '') : toolName(tool)
}

/**
 * `qa-review · implementer · Bash · Edit`: each name once, in order of first use, skills first, then
 * agents, then other tools (the first two say the most). Past MAX_TAGS names, `…`.
 */
export function toolTally(calls: readonly Pick<GroupCall, 'tool' | 'tag'>[]): string {
  const rank = (tool: string): number => (tool === 'Skill' ? 0 : tool === 'Agent' ? 1 : 2)
  const names: string[] = []
  for (const call of [...calls].sort((a, b) => rank(a.tool) - rank(b.tool))) {
    // A group stored before calls carried a tag lists the tool's name.
    const name = call.tag ?? toolName(call.tool)
    if (!names.includes(name)) {
      names.push(name)
    }
  }
  return names.length > MAX_TAGS ? `${names.slice(0, MAX_TAGS).join(' · ')} · …` : names.join(' · ')
}

/** The dot of a row or a group: live, failed, interrupted or fine. */
const dotColor = (status: 'running' | 'done' | 'failed' | 'interrupted'): string =>
  status === 'running' ? 'claude' : status === 'failed' ? 'error' : status === 'interrupted' ? 'warning' : 'success'

/** What one reply row does to the runs, block by block: a call joins, reply text or an Agent call closes. */
export function runSteps(content: readonly unknown[]): ({ close: true } | { join: GroupCall })[] {
  const steps: ({ close: true } | { join: GroupCall })[] = []
  for (const item of content) {
    const block = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    const name = typeof block.name === 'string' ? block.name : ''
    if (block.type === 'text' && typeof block.text === 'string' && block.text.trim() !== '') {
      steps.push({ close: true })
    } else if (block.type === 'tool_use' && typeof block.id === 'string' && !ENGINE_FOLDED.has(name)) {
      steps.push(
        UNTOUCHED.has(name)
          ? { close: true }
          : { join: { id: block.id, tool: name, tag: tagOf(name, block.input), label: foldLabel(name, block.input), status: 'running' } },
      )
    }
  }
  return steps
}

/**
 * Applies a row's steps to the runs. Every read of one dispatch sees one moment, so the open run
 * is read once, changed locally and each value written once. Never throws.
 */
async function applySteps($: EngineInterface, steps: readonly ({ close: true } | { join: GroupCall })[]): Promise<void> {
  if (steps.length === 0) {
    return
  }
  try {
    const openId = await read($, current)
    let open = openId === null ? null : await read($, memberOf(group, { requestId: openId }))
    const changed: ToolRun[] = []
    const joined: GroupCall[] = []
    for (const step of steps) {
      if ('join' in step) {
        open =
          open === null || open.isClosed
            ? { id: `g-${step.join.id}`, calls: [step.join], isClosed: false }
            : { ...open, calls: [...open.calls, step.join] }
        joined.push(step.join)
      } else if (open !== null) {
        changed.push({ ...open, isClosed: true })
        open = null
      }
    }
    if (open !== null) {
      changed.push(open)
    }
    // Several closed runs of one row share no id: the last write per id is the final value.
    for (const run of changed) {
      await update($, memberOf(group, { requestId: run.id }), () => run)
    }
    for (const call of joined) {
      const run = changed.find(item => item.calls.some(member => member.id === call.id))
      if (run !== undefined) {
        await update($, memberOf(groupOf, { requestId: call.id }), () => run.id)
      }
    }
    const nextOpen = open === null ? null : open.id
    if (nextOpen !== openId) {
      await update($, current, () => nextOpen)
    }
    for (const run of changed) {
      if (run.isClosed && run.calls.length >= MIN_GROUP && run.summary === undefined) {
        void writeSummary($, run).catch(error => $.ui.log(`tool-fold: summary: ${String(error)}`, { to: 'debug' }))
      }
    }
  } catch (error) {
    $.ui.log(`tool-fold: ${String(error)}`, { to: 'debug' })
  }
}

/** Sets one call's status inside its group; writes only on a change, as every row of the group reads it. */
async function markCall($: EngineInterface, callId: string, status: GroupCall['status']): Promise<void> {
  const id = await read($, memberOf(groupOf, { requestId: callId }))
  if (id === '') {
    return
  }
  const run = await read($, memberOf(group, { requestId: id }))
  if (run !== null && run.calls.some(call => call.id === callId && call.status !== status)) {
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

/**
 * `↩ implementer · reported back` / `✓ Implement Task 11 · finished · 3m 02s`: what an agent notice
 * says, without the engine's framing. Pure, so it is unit-tested directly.
 */
export function noticeLine(
  text: string,
  from: string | undefined,
  task: { status?: string; durationMs?: number } | undefined,
): string {
  if (from !== undefined) {
    return `↩ ${from.replace(/^@/, '')} · reported back`
  }
  const head = (text.split('\n')[0] ?? '').replace(/^Agent\s+/, '').replace(/\s+(finished|failed|completed)\.?$/i, '')
  const glyph = task?.status === 'failed' ? '✗' : task?.status === 'killed' || task?.status === 'stopped' ? '■' : '✓'
  const took = task?.durationMs === undefined ? '' : ` · ${Math.round(task.durationMs / 1000)}s`
  return `${glyph} ${clip(head, 80)}${task?.status === undefined ? '' : ` · ${task.status}`}${took}`
}

/** A subagent's hand-back without the engine's framing paragraph: the report itself. */
export function handBackBody(text: string): string {
  if (!/^\s*\[Subagent hand-back\]/.test(text)) {
    return text
  }
  const marker = /The report follows:\s*/i.exec(text)
  const body = marker === null ? text.replace(/^\s*\[Subagent hand-back\][^\n]*\n+/, '') : text.slice(marker.index + marker[0].length)
  return body.trim() === '' ? text : `↩ ${body.trim()}`
}

export const register: Register = (on, options) => {
  registerAgents(on, options)

  // The model's reply, block by block in order: tool calls join a run, its text or an Agent call ends it.
  on('session.append', async ($, e, next) => {
    const kept = await next(e)
    if (e.agentId === undefined && e.door === 'prompt') {
      await applySteps($, [{ close: true }])
    } else if (e.agentId === undefined && e.door === 'response') {
      await applySteps($, runSteps(e.message.content))
    }

    return kept
    // A failing hook leaves the row as the engine keeps it.
  }).catch(($, e, next) => next(e))

  // A call's outcome: a main-loop call's for its group's dot, a subagent's for its agent's card.
  on('tool.call', async ($, e, next) => {
    const agentId = e.agentId
    const input = e as Record<string, unknown>
    const step = agentId === undefined ? undefined : await startAgentCall($, agentId, e.tool, e.tool_use_id, input)
    const result = await next(e)
    const status = result.deny !== undefined || result.isError === true ? 'failed' : 'done'
    if (agentId !== undefined && step !== undefined) {
      await endAgentCall($, agentId, step, e.tool, input, status).catch(() => undefined)
    } else if (agentId === undefined && !UNTOUCHED.has(e.tool) && !ENGINE_FOLDED.has(e.tool)) {
      await markCall($, e.tool_use_id, status).catch(() => undefined)
    }

    return result
    // The cards are a view: a failing hook lets the call go on as if the mod were not there.
  }).catch(($, e, next) => next(e))

  // A loop's turn ended: the main loop's last run is complete; a subagent's outcome is stored.
  // The turn's end is not held for it.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined) {
      await applySteps($, [{ close: true }])
    }
    await endAgentTurn($, e.agentId, e.reason, e.durationMs)

    return result
  })

  // A call's row: alone, one folded line; in a group, the first row draws the group and the rest
  // show only while it is unfolded. Each line's arrow unfolds the engine's own row under it.
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    if (UNTOUCHED.has(e.props.tool) || e.props.isExpanded === true) {
      return next(e)
    }
    const { Box, Button, Text } = $.ui.resolve(e)
    const isAgent = e.props.tool === 'Agent'
    const open = memberOf(isOpen, e)
    const [isUnfolded, groupId, isLive] = await Promise.all([
      read($, open),
      read($, memberOf(groupOf, e)),
      isAgent ? isAgentLive($, e.props.tool_use_id) : Promise.resolve(false),
    ])
    const run = groupId === '' ? null : await read($, memberOf(group, { requestId: groupId }))
    const isGrouped = run !== null && run.calls.length >= MIN_GROUP

    const status = e.props.isRunning
      ? 'running'
      : e.props.isErrored
        ? 'failed'
        : e.props.isInterrupted
          ? 'interrupted'
          : 'done'
    // A call's own drawing: an agent's card (the engine's row for one spawned before the mod loaded),
    // else one line whose arrow, the only pressable part, unfolds the engine's row under it.
    const own = isAgent
      ? ((await agentCard($, e.props.tool_use_id, e.surface, { Box, Text })) ?? (await next(e)))
      : (
          <Box key={`own-${e.requestId}`} flexDirection="column">
            <Box key={`row-${e.requestId}`} flexDirection="row" gap={1} alignItems="center">
              <Button
                key={`fold-${e.requestId}`}
                plain
                dimColor
                label={isUnfolded ? '▾' : '▸'}
                onPress={() => update($, open, value => !value)}
              />
              <Text color={dotColor(status)}>●</Text>
              <Text weight="semibold">{toolName(e.props.tool)}</Text>
              <Text dimColor wrap="truncate">
                {foldLabel(e.props.tool, e.props.input)}
              </Text>
            </Box>
            {isUnfolded ? await next(e) : null}
          </Box>
        )
    if (!isGrouped || run === null) {
      return own
    }

    const groupOpen = memberOf(isOpen, { requestId: run.id })
    const isGroupOpen = await read($, groupOpen)
    // A running agent stays in view in a folded group; it folds with the group once it ends.
    const isShown = isGroupOpen || isLive
    // Each row sits in a frame of its own on desktop and VS Code: a tree mark ties a call to its group.
    // An agent's card is several lines wide and tall: beside a mark it wraps badly in a narrow chat.
    const branch = (node: RenderNode) =>
      isAgent ? (
        <Box>{node}</Box>
      ) : (
        <Box flexDirection="row" gap={1}>
          <Text dimColor>└</Text>
          {node}
        </Box>
      )
    if (run.calls[0]?.id !== e.props.tool_use_id) {
      // A later call of the group: shown only while the group is unfolded (or a live agent), under it.
      return isShown ? branch(own) : <Box />
    }

    // The group is live while a call or an agent of it still works. A call still marked running in
    // a closed run never reported its end (interrupted, or its hook failed).
    const agentsLive = await Promise.all(
      run.calls.filter(call => call.tool === 'Agent').map(call => isAgentLive($, call.id)),
    )
    const isRunning = run.calls.some(call => call.status === 'running') && !run.isClosed
    const groupStatus = run.calls.some(call => call.status === 'failed')
      ? 'failed'
      : isRunning || agentsLive.some(Boolean)
        ? 'running'
        : run.calls.some(call => call.status === 'running')
          ? 'interrupted'
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
        <Text weight="semibold">{toolTally(run.calls)}</Text>
        <Text dimColor wrap="truncate">
          {run.summary ?? (run.isClosed ? `${run.calls.length} calls` : 'Working…')}
        </Text>
      </Box>
    )
    return (
      <Box flexDirection="column">
        {header}
        {isShown ? branch(own) : null}
      </Box>
    )
  })

  // A standalone row's result block follows its call (same requestId): shown only while its line is.
  // An agent's result stays as the engine draws it unless its folded group hides the card.
  on('ui.render', { component: 'ToolResult' }, async ($, e, next) => {
    if (UNTOUCHED.has(e.props.tool) || e.props.isExpanded === true) {
      return next(e)
    }
    const isAgent = e.props.tool === 'Agent'
    const [isUnfolded, groupId] = await Promise.all([read($, memberOf(isOpen, e)), read($, memberOf(groupOf, e))])
    const run = groupId === '' ? null : await read($, memberOf(group, { requestId: groupId }))
    const isHiddenByGroup =
      run !== null &&
      run.calls.length >= MIN_GROUP &&
      !(await read($, memberOf(isOpen, { requestId: run.id }))) &&
      !(isAgent && (await isAgentLive($, e.props.tool_use_id)))
    if ((isUnfolded || isAgent) && !isHiddenByGroup) {
      return next(e)
    }
    const { Box } = $.ui.resolve(e)
    return <Box />
  })

  // The engine's notices about agents: "Agent … finished" draws as one short dim line, and a
  // hand-back message keeps the surface's own row (its expander reads the report) without the engine's
  // framing paragraph. The terminal's ctrl+o shows both whole; a surface with no ctrl+o reports every
  // row expanded, so there only the terminal's flag is honoured.
  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const kind = e.props.origin.kind
    if ((e.surface === 'terminal' && e.props.isExpanded) || kind === 'composer') {
      return next(e)
    }
    if (kind === 'task-notification') {
      const { Box, Text } = $.ui.resolve(e)
      // A background agent's notice is where its folded card lands once it stops.
      const card = await noticeCard($, e.props.task?.toolUseId, e.props.text, { Box, Text })
      return card ?? <Text dimColor wrap="truncate">{noticeLine(e.props.text, undefined, e.props.task)}</Text>
    }
    const body = e.props.from === undefined ? e.props.text : handBackBody(e.props.text)
    return body === e.props.text ? next(e) : next({ ...e, props: { ...e.props, text: body } })
  })
}
