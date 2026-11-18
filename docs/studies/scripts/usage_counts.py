#!/usr/bin/env python3
"""Aggregate one week of Claude Code transcripts. Figures only, no content dumps."""
import json, os, re, sys, glob, time, collections
from datetime import datetime, timedelta, timezone

ROOT = os.path.expanduser('~/.claude/projects')
SINCE = datetime.now(timezone.utc) - timedelta(days=7)
C = collections.Counter
SELF = sys.argv[1] if len(sys.argv) > 1 else '\0'  # id of the session running the study, to exclude it

def short(p):
    return p.rsplit('-Private-', 1)[-1].rsplit('-WORK-', 1)[-1][:28]

def wtok(u):
    return (u.get('input_tokens', 0) + 1.25 * u.get('cache_creation_input_tokens', 0)
            + 0.1 * u.get('cache_read_input_tokens', 0) + 5 * u.get('output_tokens', 0))

def mshort(m):
    m = m or '?'
    for k in ('fable', 'opus', 'sonnet', 'haiku'):
        if k in m: return k
    return m[:14]

disp = C(); disp_model = C(); disp_proj = C(); skills = C(); skills_proj = C()
main_tools = C(); sub_tools = C()
tok = collections.defaultdict(float)          # (scope, model) -> weighted tokens
tok_agent = collections.defaultdict(float)    # agentType -> weighted
agent_runs = C(); agent_model = C(); agent_out = collections.defaultdict(list)
agent_turns = collections.defaultdict(list)
proj_tok = collections.defaultdict(float)
errs = C(); err_msgs = C(); interrupts = C(); denied = C(); api_err = C()
mem_cmd = C(); mem_cmd_sub = C(); compactions = C(); sessions = C()
main_read_big = 0; main_bash_checks = C(); agent_result_flags = C()
agent_err = C(); unfinished = C(); gp_desc = C(); user_prompts = C()
hook_msgs = C(); bg = C()

files = [f for f in glob.glob(ROOT + '/**/*.jsonl', recursive=True)
         if os.path.getmtime(f) > SINCE.timestamp() and SELF not in f]

for f in files:
    rel = os.path.relpath(f, ROOT)
    proj = short(rel.split('/')[0])
    is_sub = '/subagents/' in f
    atype = None
    if is_sub:
        mp = f[:-6] + '.meta.json'
        try:
            meta = json.load(open(mp)); atype = meta.get('agentType') or '?'
            if not meta.get('finished', True): unfinished[atype] += 1
            if atype in ('general-purpose', 'claude'):
                gp_desc[' '.join((meta.get('description') or '').split()[:2]).lower()] += 1
        except Exception:
            atype = 'workflow/?'
    else:
        sessions[proj] += 1
    seen_msg = set(); id2tool = {}; nturn = 0; out_tok = 0; amodel = None; in_window = False
    try:
        fh = open(f, errors='replace')
    except Exception:
        continue
    for line in fh:
        if '"type":"api-request' in line[:400] or '"api-request-blob"' in line[:200]:
            continue
        try: r = json.loads(line)
        except Exception: continue
        ts = r.get('timestamp')
        if ts:
            try:
                if datetime.fromisoformat(ts.replace('Z', '+00:00')) < SINCE: continue
            except Exception: pass
        in_window = True
        t = r.get('type')
        if t == 'system' and r.get('subtype') == 'compact_boundary': compactions[proj] += 1
        if t == 'assistant':
            m = r.get('message') or {}
            if r.get('isApiErrorMessage') or r.get('apiError'):
                api_err[str(r.get('apiErrorType') or r.get('apiErrorStatus') or r.get('error'))[:40]] += 1
            mid = m.get('id'); u = m.get('usage') or {}
            model = mshort(m.get('model'))
            if mid and mid not in seen_msg and u:
                seen_msg.add(mid); w = wtok(u)
                tok[('sub' if is_sub else 'main', model)] += w
                proj_tok[proj] += w
                if is_sub:
                    tok_agent[atype] += w; out_tok += u.get('output_tokens', 0); amodel = model; nturn += 1
            for b in m.get('content') or []:
                if not isinstance(b, dict) or b.get('type') != 'tool_use': continue
                tid = b.get('id')
                if tid in id2tool: continue
                name = b.get('name'); inp = b.get('input') or {}
                id2tool[tid] = name
                (sub_tools if is_sub else main_tools)[name] += 1
                if name == 'Agent':
                    st = inp.get('subagent_type') or 'general-purpose(default)'
                    disp[st] += 1; disp_proj[(proj, st)] += 1
                    disp_model[(st, inp.get('model') or '-')] += 1
                    if inp.get('run_in_background'): bg[st] += 1
                elif name == 'Skill':
                    skills[inp.get('skill')] += 1; skills_proj[(proj, inp.get('skill'))] += 1
                elif name == 'Bash':
                    cmd = inp.get('command') or ''
                    for mm in re.finditer(r'(?:^|[;&|]\s*|\n)\s*mem(-[a-z]+)?\s+([a-z]+)', cmd):
                        k = 'mem' + (mm.group(1) or '') + ' ' + mm.group(2)
                        (mem_cmd_sub if is_sub else mem_cmd)[k] += 1
                    if not is_sub and re.search(r'\b(pytest|cargo (test|build|clippy|check)|npm (test|run build)|ruff|mypy|tsc|validate\.py|plugin eval)\b', cmd):
                        main_bash_checks[re.search(r'\b(pytest|cargo \w+|npm \w+|ruff|mypy|tsc|validate\.py|plugin eval)', cmd).group(1)] += 1
        elif t == 'user':
            m = r.get('message') or {}
            c = m.get('content')
            if isinstance(c, str):
                if not is_sub and not r.get('isMeta') and not r.get('isCompactSummary'):
                    if '[Request interrupted' in c: interrupts[proj] += 1
                    elif not c.startswith('<'): user_prompts[proj] += 1
                continue
            for b in c or []:
                if not isinstance(b, dict): continue
                if b.get('type') == 'text':
                    tx = b.get('text') or ''
                    if '[Request interrupted' in tx and not is_sub: interrupts[proj] += 1
                    elif not is_sub and not r.get('isMeta') and not tx.startswith('<'): user_prompts[proj] += 1
                if b.get('type') != 'tool_result': continue
                name = id2tool.get(b.get('tool_use_id'), '?')
                cc = b.get('content')
                txt = cc if isinstance(cc, str) else ' '.join(x.get('text', '') for x in cc or [] if isinstance(x, dict))
                if name == 'Agent' and not is_sub:
                    for flag in ('BLOCKED', 'NEEDS_CONTEXT', 'turn budget', 'checkpoint', 'DONE_WITH_CONCERNS'):
                        if flag in txt[:3000]: agent_result_flags[flag] += 1
                if name == 'Read' and not is_sub and len(txt) > 40000: main_read_big += 1
                if b.get('is_error'):
                    scope = 'sub' if is_sub else 'main'
                    errs[(scope, name)] += 1
                    low = txt.lower()
                    if 'permission' in low or 'denied' in low or "user doesn't want" in low or 'rejected' in low:
                        denied[(scope, name)] += 1
                    if name == 'Agent': agent_err[re.sub(r'[0-9a-f]{8,}', '#', txt[:90])] += 1
                    key = re.sub(r'\s+', ' ', re.sub(r'(/[\w.\-]+)+', '/P', re.sub(r'\d+', 'N', txt[:110])))
                    err_msgs[(name, key[:90])] += 1
        elif t == 'attachment':
            a = r.get('attachment') or {}
            at = a.get('type') or ''
            if 'hook' in at:
                hook_msgs[(at, str(a.get('hookName') or a.get('hookEvent') or '')[:30])] += 1
    fh.close()
    if is_sub and in_window and nturn:
        agent_runs[atype] += 1; agent_model[(atype, amodel)] += 1
        agent_turns[atype].append(nturn); agent_out[atype].append(out_tok)

def top(c, n=25, fmt=str):
    return '\n'.join(f'  {v:>7,.0f}  {fmt(k)}' for k, v in sorted(c.items(), key=lambda x: -x[1])[:n])
def med(l):
    l = sorted(l); return l[len(l)//2] if l else 0
def p90(l):
    l = sorted(l); return l[int(len(l)*0.9)] if l else 0

tot = sum(tok.values())
print(f'FILES {len(files)}  window since {SINCE:%Y-%m-%d %H:%M}Z  (this session excluded)')
print('\n## sessions / prompts / interrupts / compactions per project')
for p in sorted(sessions, key=lambda p: -proj_tok[p]):
    print(f'  {p:30} sess {sessions[p]:>3} prompts {user_prompts[p]:>4} interrupts {interrupts[p]:>3} compact {compactions[p]:>3} wtok {proj_tok[p]/1e6:>8.1f}M {100*proj_tok[p]/tot:4.0f}%')
print('\n## weighted tokens (in + 1.25 cw + 0.1 cr + 5 out; NOT price-adjusted) by scope/model, M')
for k, v in sorted(tok.items(), key=lambda x: -x[1]): print(f'  {k[0]:5} {k[1]:8} {v/1e6:>9.1f}M {100*v/tot:4.0f}%')
print('\n## Agent dispatches (deduped tool_use), total', sum(disp.values()))
for k, v in disp.most_common(40):
    models = ','.join(f'{m}:{n}' for (s, m), n in disp_model.items() if s == k and m != '-')
    print(f'  {v:>5}  {k:42} bg {bg[k]:>4}  {("model param " + models) if models else ""}')
print('\n## Subagent transcripts by type: runs, model, median/p90 turns, median out tok, share of weighted tokens')
for k in sorted(agent_runs, key=lambda k: -tok_agent[k]):
    models = ','.join(f'{m}:{n}' for (s, m), n in agent_model.items() if s == k)
    print(f'  {k:42} runs {agent_runs[k]:>4} [{models}] turns {med(agent_turns[k])}/{p90(agent_turns[k])} out {med(agent_out[k]):>6} wtok {tok_agent[k]/1e6:>7.1f}M {100*tok_agent[k]/tot:4.1f}% unfinished {unfinished[k]}')
print('\n## general-purpose/claude descriptions (first 2 words)'); print(top(gp_desc, 20))
print('\n## Skill loads, total', sum(skills.values())); print(top(skills, 50))
print('\n## Skill loads by project'); print(top(skills_proj, 40, lambda k: f'{k[0]:28} {k[1]}'))
print('\n## dispatches by project'); print(top(disp_proj, 60, lambda k: f'{k[0]:28} {k[1]}'))
print('\n## main-session tools'); print(top(main_tools, 40))
print('\n## subagent tools'); print(top(sub_tools, 30))
print('\n## main-session checks run inline via Bash'); print(top(main_bash_checks))
print('main Read results > 40k chars:', main_read_big)
print('\n## mem commands main'); print(top(mem_cmd, 30))
print('\n## mem commands subagents'); print(top(mem_cmd_sub, 30))
print('\n## tool errors (scope, tool)'); print(top(errs, 30))
print('\n## denied/rejected'); print(top(denied, 15))
print('\n## top error messages'); print(top(err_msgs, 45, lambda k: f'{k[0]:10} {k[1]}'))
print('\n## Agent tool errors'); print(top(agent_err, 12))
print('\n## agent result flags', dict(agent_result_flags))
print('\n## API errors'); print(top(api_err, 10))
print('\n## hook attachments'); print(top(hook_msgs, 20))
