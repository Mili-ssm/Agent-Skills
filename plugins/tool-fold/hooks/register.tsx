import { atom, memberOf, read, update } from 'claude-code'
import type { Register } from 'claude-code'

// Calls drawn as the engine draws them: an Agent call is agents-pane's card.
const UNTOUCHED = new Set(['Agent'])
// One value per call: a press redraws that row alone, not every row in the chat.
const isOpen = atom({ plugin: 'tool-fold', key: 'isOpen' } as const, false)

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

export const register: Register = on => {
  // The call's row: one line while folded; the engine's row under it once unfolded.
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    if (UNTOUCHED.has(e.props.tool) || e.props.isExpanded === true) {
      return next(e)
    }
    const open = memberOf(isOpen, e)
    const isUnfolded = await read($, open)
    const { Box, Button, Text } = $.ui.resolve(e)
    const dot = e.props.isRunning
      ? 'claude'
      : e.props.isErrored
        ? 'error'
        : e.props.isInterrupted
          ? 'warning'
          : 'success'
    // Only the arrow is pressable: a one-glyph Button is a control by itself.
    const row = (
      <Box key={`row-${e.requestId}`} flexDirection="row" gap={1} alignItems="center">
        <Button
          key={`fold-${e.requestId}`}
          plain
          dimColor
          label={isUnfolded ? '▾' : '▸'}
          onPress={() => update($, open, value => !value)}
        />
        <Text color={dot}>●</Text>
        <Text backgroundColor="inactive" color="inverseText">
          {` ${toolName(e.props.tool)} `}
        </Text>
        <Text dimColor wrap="truncate">
          {foldLabel(e.props.tool, e.props.input)}
        </Text>
      </Box>
    )
    if (!isUnfolded) {
      return row
    }
    return (
      <Box flexDirection="column">
        {row}
        {await next(e)}
      </Box>
    )
  })

  // A standalone row's result block follows its call (same requestId): hidden while folded.
  on('ui.render', { component: 'ToolResult' }, async ($, e, next) => {
    if (UNTOUCHED.has(e.props.tool) || (await read($, memberOf(isOpen, e)))) {
      return next(e)
    }
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
}
