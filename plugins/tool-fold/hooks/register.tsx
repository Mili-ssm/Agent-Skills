import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

// Calls drawn as the engine draws them: an Agent call is agents-pane's card.
const UNTOUCHED = new Set(['Agent'])
// Keep the list bounded: a long session makes thousands of calls.
const MAX_UNFOLDED = 200
const unfolded = atom({ plugin: 'tool-fold', key: 'unfolded' } as const, [], { shape: 'unfolded-1' })

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
    default:
      return ''
  }
}

/** `mcp__github__get_file` → `github get_file`. */
const toolName = (tool: string): string => tool.replace(/^mcp__/, '').replace(/__/g, ' ')

export const register: Register = on => {
  // The call's row: one pressable line while folded; the engine's row under it once unfolded.
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    if (UNTOUCHED.has(e.props.tool) || e.props.isExpanded === true) {
      return next(e)
    }
    const id = e.props.tool_use_id
    const isUnfolded = (await read($, unfolded)).includes(id)
    const { Box, Button, Text } = $.ui.resolve(e)
    const dot = e.props.isRunning
      ? 'claude'
      : e.props.isErrored
        ? 'error'
        : e.props.isInterrupted
          ? 'warning'
          : 'success'
    const toggle = () =>
      update($, unfolded, list =>
        list.includes(id) ? list.filter(item => item !== id) : [...list, id].slice(-MAX_UNFOLDED),
      )
    const row = (
      <Button key={`fold-${id}`} plain onPress={toggle}>
        <Text color={dot}>●</Text> <Text bold>{toolName(e.props.tool)}</Text>{' '}
        <Text dimColor>{foldLabel(e.props.tool, e.props.input)}</Text> <Text dimColor>{isUnfolded ? '▾' : '▸'}</Text>
      </Button>
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

  // A standalone row's result block follows its call: hidden while the call is folded.
  on('ui.render', { component: 'ToolResult' }, async ($, e, next) => {
    if (UNTOUCHED.has(e.props.tool) || (await read($, unfolded)).includes(e.props.tool_use_id)) {
      return next(e)
    }
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
}
