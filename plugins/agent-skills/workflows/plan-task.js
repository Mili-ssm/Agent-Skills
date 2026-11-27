export const meta = {
  name: 'plan-task',
  description: 'Run one plan task: implementer, then skeptical-reviewer on its commits, then one verified fix round',
  whenToUse: 'Pilot (ADR 0039, plan stage 8): one task of a committed plan, started by the owner, so the main conversation receives only the final result instead of three reports.',
  phases: [
    { title: 'Implement', detail: 'agent-skills:implementer on the task' },
    { title: 'Review', detail: 'agent-skills:skeptical-reviewer on the task commits' },
    { title: 'Fix', detail: 'one fix round when a medium or high finding exists' },
  ],
}

// args: { task: "<path to a committed task brief or plan file>#<task heading>", checks: "<commands that prove the task>",
//         rules?: "<owner rules not in CLAUDE.md>" }
// The workers start without the main conversation, so every prompt names files instead of pasting them (ADR 0039).

if (!args || !args.task || !args.checks) {
  throw new Error('plan-task needs args {task, checks}: the task file (and heading) and the commands that prove it')
}
const rules = args.rules ? `\nRules not in CLAUDE.md: ${args.rules}` : ''

const IMPLEMENT = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['DONE', 'BLOCKED'] },
    base: { type: 'string', description: 'commit hash before the task' },
    head: { type: 'string', description: 'commit hash after the task' },
    checks: { type: 'string', description: 'each check command with its summary line' },
    note: { type: 'string', description: 'open questions, risks or the blocking reason, one or two lines' },
  },
  required: ['status', 'base', 'head', 'checks', 'note'],
}

const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['low', 'medium', 'high'] },
          where: { type: 'string' },
          evidence: { type: 'string' },
          doubt: { type: 'string' },
        },
        required: ['severity', 'where', 'evidence', 'doubt'],
      },
    },
    notChecked: { type: 'string' },
  },
  required: ['findings', 'notChecked'],
}

const FIX = {
  type: 'object',
  properties: {
    head: { type: 'string' },
    fixed: { type: 'array', items: { type: 'string' }, description: 'where of each finding fixed' },
    refuted: {
      type: 'array',
      items: {
        type: 'object',
        properties: { where: { type: 'string' }, refutingLine: { type: 'string' } },
        required: ['where', 'refutingLine'],
      },
    },
    checks: { type: 'string' },
  },
  required: ['head', 'fixed', 'refuted', 'checks'],
}

phase('Implement')
const impl = await agent(
  `Implement the plan task at ${args.task}. Follow the task's test-then-code steps and commit this task locally (no push).` +
    ` Checks that prove it: ${args.checks}.${rules}` +
    ' Return the commit hash before your first commit as base and your last commit as head.',
  { agentType: 'agent-skills:implementer', schema: IMPLEMENT, label: 'implement' },
)
if (!impl || impl.status !== 'DONE') {
  return { status: impl ? 'BLOCKED' : 'FAILED', implement: impl }
}
const range = `${impl.base}..${impl.head}`

phase('Review')
const review = await agent(
  `Round 1. Review the commit range ${range} against the task at ${args.task}: what is missing, extra or misunderstood,` +
    ` plus your usual findings. Already verified: ${impl.checks}. Rejected findings: none.${rules}`,
  { agentType: 'agent-skills:skeptical-reviewer', schema: FINDINGS, label: 'review' },
)
const findings = review ? review.findings : []
const actionable = findings.filter((f) => f.severity !== 'low')
const low = findings.filter((f) => f.severity === 'low')

let fix = null
if (actionable.length) {
  phase('Fix')
  const list = actionable.map((f, i) => `${i + 1}. [${f.severity}] ${f.where}: ${f.doubt} (evidence: ${f.evidence})`).join('\n')
  fix = await agent(
    `Fix round for the task at ${args.task}, commits ${range}. Verify each finding against the code before fixing it;` +
      ' fix the ones that hold and list the ones that do not, each with the line that refutes it. Commit locally (no push).' +
      ` Checks: ${args.checks}.${rules}\nFindings:\n${list}`,
    { agentType: 'agent-skills:implementer', schema: FIX, label: 'fix' },
  )
}

// Round 2 is not run here: the caller rules on refuted findings and decides it (offload policy, reviewer row).
return {
  status: 'DONE',
  range: `${impl.base}..${fix ? fix.head : impl.head}`,
  checks: fix ? fix.checks : impl.checks,
  implementNote: impl.note,
  fixed: fix ? fix.fixed : [],
  refuted: fix ? fix.refuted : [],
  fixRoundFailed: Boolean(actionable.length && !fix),
  lowDeferred: low.map((f) => `${f.where} — ${f.doubt}`),
  notChecked: review ? review.notChecked : 'review failed',
}
