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

// args: { task: "<path to a committed task brief or plan file>", heading?: "<task heading in that file>",
//         checks: "<commands that prove the task>", files?: "<paths the task owns>", rules?: "<owner rules not in CLAUDE.md>" }
// The workers start without the main conversation, so every prompt names files instead of pasting them (ADR 0039).
// Every return has the same shape; `status` is DONE, BLOCKED, NO_COMMIT, IMPLEMENT_FAILED, REVIEW_FAILED or FIX_FAILED.

if (!args || !args.task || !args.checks) {
  throw new Error('plan-task needs args {task, checks}: the task file and the commands that prove it')
}
const where = args.heading ? `the task "${args.heading}" in ${args.task}` : `the task in ${args.task}`
const extra = (args.files ? ` Owned files: ${args.files}.` : '') + (args.rules ? ` Rules not in CLAUDE.md: ${args.rules}.` : '')

const IMPLEMENT = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['DONE', 'BLOCKED'] },
    base: { type: 'string', description: 'commit hash before the task' },
    head: { type: 'string', description: 'commit hash after the task; equal to base when nothing was committed' },
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
          confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
          where: { type: 'string' },
          evidence: { type: 'string', description: 'the Evidence cell; empty for a low line' },
          doubt: { type: 'string', description: 'the Suspicion cell, or the doubt of a low line' },
          check: { type: 'string', description: 'the Check cell; empty for a low line' },
        },
        required: ['severity', 'confidence', 'where', 'evidence', 'doubt', 'check'],
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
    fixed: { type: 'array', items: { type: 'string' }, description: 'the number of each finding fixed' },
    refuted: {
      type: 'array',
      items: {
        type: 'object',
        properties: { number: { type: 'string' }, refutingLine: { type: 'string' } },
        required: ['number', 'refutingLine'],
      },
    },
    checks: { type: 'string' },
  },
  required: ['head', 'fixed', 'refuted', 'checks'],
}

const result = (status, fields) => ({
  status,
  range: null,
  checks: null,
  note: null,
  findings: [],
  fixed: [],
  refuted: [],
  unresolved: [],
  lowDeferred: [],
  notChecked: null,
  ...fields,
})

phase('Implement')
const impl = await agent(
  `Implement ${where}. Follow the task's test-then-code steps and commit this task locally (no push).` +
    ` Checks that prove it: ${args.checks}.${extra}` +
    ' Return the commit hash before your first commit as base and your last commit as head.',
  { agentType: 'agent-skills:implementer', schema: IMPLEMENT, label: 'implement' },
)
if (!impl) return result('IMPLEMENT_FAILED', { note: 'the implementer returned nothing' })
if (impl.status !== 'DONE') return result('BLOCKED', { checks: impl.checks, note: impl.note })
if (impl.base === impl.head) return result('NO_COMMIT', { checks: impl.checks, note: impl.note })
const range = `${impl.base}..${impl.head}`

phase('Review')
const review = await agent(
  `Round 1. Review the commit range ${range} against ${where}: what is missing, extra or misunderstood,` +
    ` plus your usual findings. Already verified: ${impl.checks}. Rejected findings: none.${extra}` +
    ' Map your report to the fields: each table row and each low line is one finding (Suspicion or the low doubt → doubt).',
  { agentType: 'agent-skills:skeptical-reviewer', schema: FINDINGS, label: 'review' },
)
if (!review) return result('REVIEW_FAILED', { range, checks: impl.checks, note: impl.note })

const numbered = review.findings.map((f, i) => ({ number: String(i + 1), ...f }))
const actionable = numbered.filter((f) => f.severity !== 'low')
const lowDeferred = numbered.filter((f) => f.severity === 'low').map((f) => `${f.where} — ${f.doubt}`)
if (!actionable.length) {
  return result('DONE', { range, checks: impl.checks, note: impl.note, lowDeferred, notChecked: review.notChecked })
}

phase('Fix')
const list = actionable
  .map((f) => `${f.number}. [${f.severity}, confidence ${f.confidence}] ${f.where}: ${f.doubt} (evidence: ${f.evidence}; check: ${f.check})`)
  .join('\n')
const fix = await agent(
  `Fix round for ${where}, commits ${range}. Verify each finding against the code before fixing it;` +
    ' fix the ones that hold and list the ones that do not, each with the line that refutes it. Commit locally (no push).' +
    ` Checks: ${args.checks}.${extra} Report findings by their number.\nFindings:\n${list}`,
  { agentType: 'agent-skills:implementer', schema: FIX, label: 'fix' },
)
if (!fix) {
  return result('FIX_FAILED', {
    range: `${impl.base}..HEAD (the fix worker may have committed before it failed)`,
    checks: impl.checks,
    note: impl.note,
    findings: actionable,
    unresolved: actionable.map((f) => f.number),
    lowDeferred,
    notChecked: review.notChecked,
  })
}

// Round 2 is not run here: the caller rules on refuted findings and decides it (offload policy, reviewer row).
const settled = new Set([...fix.fixed, ...fix.refuted.map((r) => r.number)])
return result('DONE', {
  range: `${impl.base}..${fix.head}`,
  checks: fix.checks,
  note: impl.note,
  findings: actionable,
  fixed: fix.fixed,
  refuted: fix.refuted,
  unresolved: actionable.filter((f) => !settled.has(f.number)).map((f) => f.number),
  lowDeferred,
  notChecked: review.notChecked,
})
