#!/usr/bin/env python3
"""Price one week of Claude Code transcripts and attribute the main session's context to what filled it.

Read-only over ~/.claude/projects. Figures only, no content dumps.
Usage: usage_main_context.py [SESSION_ID_TO_EXCLUDE] [DAYS]

Carry cost of an item = its tokens written once to the cache (1-hour write price) plus its tokens
re-read from cache on every later main call of the same context segment (a compaction starts a new
segment). Tokens of an item are estimated from characters with a ratio calibrated on context growth.
"""
import json, os, re, sys, glob, collections, statistics
from datetime import datetime, timedelta, timezone

ROOT = os.path.expanduser('~/.claude/projects')
SELF = sys.argv[1] if len(sys.argv) > 1 else '\0'
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 7
SINCE = datetime.now(timezone.utc) - timedelta(days=DAYS)
SINCE_ISO = SINCE.strftime('%Y-%m-%dT%H:%M:%S')

# USD per MTok: input, output, cache read (skill claude-api table, cached 2026-11-03). Cache write: 1.25x input (5m), 2x (1h).
PRICE = {'fable': (8, 40, 0.20), 'opus': (4, 20, 0.20), 'sonnet': (2, 10, 0.10), 'haiku': (0.10, 0.50, 0.01)}
HAIKU_LONG = (0.50, 2.50, 0.05)  # Haiku 5.5 prompts over 100K tokens; cache read assumed 0.1x input

def mfam(m):
    m = m or ''
    for k in PRICE:
        if k in m: return k
    return None

def prices(fam, prompt_tokens):
    if fam == 'haiku' and prompt_tokens > 100_000: return HAIKU_LONG
    return PRICE[fam]

def cost(u, fam):
    cw = u.get('cache_creation') or {}
    cw1h = cw.get('ephemeral_1h_input_tokens', 0); cw5m = cw.get('ephemeral_5m_input_tokens', 0)
    if not cw: cw5m = u.get('cache_creation_input_tokens', 0)
    inp, cr, out = u.get('input_tokens', 0), u.get('cache_read_input_tokens', 0), u.get('output_tokens', 0)
    pi, po, pr = prices(fam, inp + cw1h + cw5m + cr)
    parts = {'input': inp * pi, 'cache_write': (cw5m * 1.25 + cw1h * 2) * pi, 'cache_read': cr * pr, 'output': out * po}
    return {k: v / 1e6 for k, v in parts.items()}

def short(p):
    return p.rsplit('-Private-', 1)[-1].rsplit('-WORK-', 1)[-1][:26]

def flat(c):
    if isinstance(c, str): return c
    if isinstance(c, list):
        return ''.join(x.get('text', '') if isinstance(x, dict) and x.get('type') == 'text' else
                       (json.dumps(x) if isinstance(x, dict) and x.get('type') != 'image' else '') for x in c)
    return ''

CHECK = re.compile(r'\b(pytest|cargo (test|build|clippy|check|fmt|run)|validate\.py|npm (run|test)|ruff|plugin (eval|validate|test)|tsc|port\.py|mypy|uv run)\b')
def bash_class(cmd):
    c = re.sub(r'^\s*(cd [^&;]+(&&|;)\s*)+', '', cmd or '').strip()
    if CHECK.search(c.split('\n', 1)[0]) and not re.match(r'git\b', c): return 'check'
    if re.match(r'(git|gh)\b', c): return 'git/gh'
    if re.search(r'(^|[;&|]\s*)mem\b', c): return 'mem'
    if re.match(r'(python3?|uv run python)\b', c): return 'python'
    if re.match(r'(cat|sed|head|tail|nl|less|bat|jq|wc|awk)\b', c): return 'read-file'
    if re.match(r'(grep|rg|find|ls|fd|tree|ast-grep)\b', c): return 'search'
    return 'other'

def pct(l, q):
    l = sorted(l); return l[min(len(l) - 1, int(len(l) * q))] if l else 0

files = [f for f in glob.glob(ROOT + '/**/*.jsonl', recursive=True)
         if os.path.getmtime(f) > SINCE.timestamp() and SELF not in f]

money = collections.defaultdict(float)            # (scope, fam, part) -> USD
proj_money = collections.defaultdict(float)
agent = collections.defaultdict(lambda: collections.defaultdict(list))  # type -> metric -> values
agent_cost = collections.defaultdict(float)
main_items = []        # (cat, chars, session, seg, call_idx)
sessions = {}          # sid -> dict(calls=[(seg, ctx, fam, out, think)], proj)
brief_chars = collections.defaultdict(list); report_chars = collections.defaultdict(list)
bash_chars = collections.defaultdict(list)
session_sub_cost = collections.defaultdict(float)

for f in files:
    rel = os.path.relpath(f, ROOT); proj = short(rel.split('/')[0])
    is_sub = '/subagents/' in f
    sid = rel.split('/')[1].split('.')[0]
    atype = None
    if is_sub:
        try: atype = json.load(open(f[:-6] + '.meta.json')).get('agentType') or '?'
        except Exception: atype = 'workflow/?'
    seen = set(); id2tool = {}; aid2type = {}; seg = 0; calls = []; run_cost = 0.0; run_out = run_think = turns = 0
    for line in open(f, errors='replace'):
        try: r = json.loads(line)
        except Exception: continue
        ts = r.get('timestamp') or ''
        if ts and ts < SINCE_ISO: continue
        t = r.get('type')
        if t == 'system' and r.get('subtype') == 'compact_boundary':
            seg += 1; continue
        if t == 'assistant':
            m = r.get('message') or {}; mid = m.get('id'); u = m.get('usage') or {}
            fam = mfam(m.get('model'))
            if mid and mid not in seen and u and fam:
                seen.add(mid); c = cost(u, fam)
                for k, v in c.items(): money[('sub' if is_sub else 'main', fam, k)] += v
                tot = sum(c.values()); proj_money[proj] += tot
                out = u.get('output_tokens', 0); think = (u.get('output_tokens_details') or {}).get('thinking_tokens', 0)
                if is_sub:
                    run_cost += tot; run_out += out; run_think += think; turns += 1
                else:
                    ctx = u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0) + u.get('cache_read_input_tokens', 0)
                    calls.append((seg, ctx, fam, out, think))
                    if think: main_items.append(('assistant thinking (tokens x ratio)', think * 3.62, sid, seg, len(calls)))
            if is_sub: continue
            for b in m.get('content') or []:
                if not isinstance(b, dict): continue
                if b.get('type') == 'tool_use':
                    inp = b.get('input') or {}; name = b.get('name')
                    id2tool[b.get('id')] = (name, inp)
                    if name == 'Agent':
                        st = inp.get('subagent_type') or 'general-purpose'
                        brief_chars[st].append(len(inp.get('prompt', '')))
                        main_items.append(('brief:' + st, len(json.dumps(inp)), sid, seg, len(calls)))
                    elif name in ('Edit', 'Write', 'MultiEdit'):
                        main_items.append(('main edit/write input', len(json.dumps(inp)), sid, seg, len(calls)))
                    else:
                        main_items.append(('input:' + str(name), len(json.dumps(inp)), sid, seg, len(calls)))
                elif b.get('type') == 'text':
                    main_items.append(('assistant text', len(b.get('text', '')), sid, seg, len(calls)))
        elif t == 'user' and not is_sub:
            m = r.get('message') or {}; content = m.get('content')
            if r.get('isCompactSummary'):
                main_items.append(('compact summary', len(flat(content)), sid, seg, len(calls))); continue
            if isinstance(content, str): content = [{'type': 'text', 'text': content}]
            for b in content or []:
                if not isinstance(b, dict): continue
                if b.get('type') == 'tool_result':
                    name, inp = id2tool.get(b.get('tool_use_id'), ('?', {}))
                    n = len(flat(b.get('content')))
                    if name == 'Agent':
                        st = inp.get('subagent_type') or 'general-purpose'
                        txt = flat(b.get('content')); mm = re.search(r'agentId: ([0-9a-f]+)', txt)
                        if mm and 'Async agent launched' in txt:
                            aid2type[mm.group(1)] = st; cat = 'dispatch boilerplate (bg launch)'
                        else:
                            cat = 'report:' + st; report_chars[st].append(n)
                    elif name == 'Bash':
                        bc = bash_class(inp.get('command')); cat = 'bash:' + bc; bash_chars[bc].append(n)
                    else:
                        cat = 'result:' + str(name)
                    main_items.append((cat, n, sid, seg, len(calls)))
                elif b.get('type') == 'text':
                    tx = b.get('text', '')
                    mm = re.search(r'agent-message from="([0-9a-f]+)"', tx[:200])
                    if mm:
                        st = aid2type.get(mm.group(1), 'SendMessage/other')
                        cat = 'report:' + st; report_chars[st].append(len(tx))
                    elif tx.startswith('Base directory for this skill'):
                        nm = tx.split('\n', 1)[0].rstrip('/').rsplit('/', 1)[-1]
                        cat = 'skill body:' + nm
                    elif r.get('isMeta') or tx.startswith('<'): cat = 'meta text'
                    else: cat = 'user prompt'
                    main_items.append((cat, len(tx), sid, seg, len(calls)))
        elif t == 'attachment' and not is_sub and r.get('rendered'):
            a = r.get('attachment') or {}
            cat = 'att:' + str(a.get('type'))
            rend = r['rendered'] if isinstance(r['rendered'], str) else flat(r['rendered'])
            if a.get('type') == 'queued_command':
                mm = re.search(r'agent-message from="([0-9a-f]+)"', rend[:400])
                if mm:
                    st = aid2type.get(mm.group(1), 'SendMessage/other'); report_chars[st].append(len(rend))
                    main_items.append(('report:' + st, len(rend), sid, seg, len(calls))); continue
                cat = 'task-notification boilerplate' if '<task-notification>' in rend else 'att:queued_command (other)'
            if a.get('type') == 'hook_additional_context': cat += ':' + str(a.get('hookEvent') or (a.get('hookName') or '').split(':')[0])
            main_items.append((cat, len(flat(r['rendered']) if not isinstance(r['rendered'], str) else r['rendered']), sid, seg, len(calls)))
    if is_sub:
        if turns:
            a = agent[atype]; a['cost'].append(run_cost); a['out'].append(run_out); a['think'].append(run_think); a['turns'].append(turns)
            agent_cost[atype] += run_cost
            session_sub_cost[sid] += run_cost
    elif calls:
        sessions[sid] = {'calls': calls, 'proj': proj}

# ---- calibrate chars per token on context growth within segments
grow = chars_in = 0
by_sess = collections.defaultdict(list)
for it in main_items: by_sess[it[2]].append(it)
for sid, s in sessions.items():
    calls = s['calls']
    for i in range(1, len(calls)):
        if calls[i][0] == calls[i - 1][0]:
            d = calls[i][1] - calls[i - 1][1] - calls[i - 1][3]  # thinking assumed kept in context
            if d > 0: grow += d
    chars_in += sum(n for cat, n, _, sg, ci in by_sess[sid] if not cat.startswith(('assistant', 'input:', 'brief:', 'main edit')) and 0 < ci < len(calls))
RATIO = chars_in / grow if grow else 3.6
RATIO = min(max(RATIO, 2.5), 5.0)

# ---- carry cost per category
carry = collections.defaultdict(float); toks = collections.defaultdict(float); cnt = collections.Counter()
base_carry = 0.0; base_tok = []
for sid, s in sessions.items():
    calls = s['calls']; n = len(calls)
    suffix = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        nxt_same = i + 1 < n and calls[i + 1][0] == calls[i][0]
        suffix[i] = PRICE[calls[i][2]][2] / 1e6 + (suffix[i + 1] if nxt_same else 0)
    for cat, ch, _, sg, ci in by_sess[sid]:
        if ci >= n: continue
        tk = ch / (3.62 if cat.startswith('assistant thinking') else RATIO); fam = calls[ci][2]  # thinking was stored as tokens x 3.62
        carry[cat] += tk * (PRICE[fam][0] * 2 / 1e6) + tk * suffix[ci]
        toks[cat] += tk; cnt[cat] += 1
    # base load: context of the first call of each segment, minus items entered before it
    firsts = {}
    for i, c in enumerate(calls): firsts.setdefault(c[0], i)
    for sg, i in firsts.items():
        pre = sum(ch for cat, ch, _, s2, ci in by_sess[sid] if s2 == sg and ci <= i) / RATIO
        b = max(0, calls[i][1] - pre); base_tok.append(b)
        base_carry += b * (PRICE[calls[i][2]][0] * 2 / 1e6) + b * suffix[i]

main_total = sum(v for (sc, _, _), v in money.items() if sc == 'main')
sub_total = sum(v for (sc, _, _), v in money.items() if sc == 'sub')
print(f'FILES {len(files)}  window since {SINCE:%Y-%m-%d %H:%MZ}  main sessions {len(sessions)}  chars/token ratio {RATIO:.2f}')
print(f'\n## USD by scope/model/part  (total {main_total + sub_total:.0f}: main {main_total:.0f} = {100*main_total/(main_total+sub_total):.0f}%, sub {sub_total:.0f})')
agg = collections.defaultdict(float)
for (sc, fam, part), v in money.items(): agg[(sc, fam)] += v
for (sc, fam), v in sorted(agg.items(), key=lambda x: -x[1]):
    parts = ' '.join(f'{p} {money[(sc, fam, p)]:.0f}' for p in ('input', 'cache_write', 'cache_read', 'output'))
    print(f'  {sc:4} {fam:7} {v:8.0f}  {100*v/(main_total+sub_total):4.0f}%   ({parts})')
print('\n## USD by project')
for p, v in sorted(proj_money.items(), key=lambda x: -x[1])[:8]: print(f'  {p:28} {v:8.0f}')

print('\n## Main sessions: calls, context per call median/p90/max (k tokens), cost main vs its subagents (USD)')
rows = []
for sid, s in sessions.items():
    ctx = [c[1] for c in s['calls']]; fam = collections.Counter(c[2] for c in s['calls']).most_common(1)[0][0]
    mc = 0.0
    rows.append((s['proj'], sid[:8], fam, len(ctx), statistics.median(ctx) / 1e3, pct(ctx, .9) / 1e3, max(ctx) / 1e3,
                 len({c[0] for c in s['calls']}) - 1, session_sub_cost.get(sid, 0)))
allctx = [c[1] for s in sessions.values() for c in s['calls']]
print(f'  all main calls {len(allctx)}: median {statistics.median(allctx)/1e3:.0f}k p90 {pct(allctx,.9)/1e3:.0f}k')
for r in sorted(rows, key=lambda r: -r[3])[:14]:
    print(f'  {r[0]:26} {r[1]} {r[2]:6} calls {r[3]:5} ctx {r[4]:5.0f}/{r[5]:5.0f}/{r[6]:5.0f}k compactions {r[7]} sub$ {r[8]:6.1f}')
print(f'  base load (first call of a segment, minus items before it): median {statistics.median(base_tok)/1e3:.1f}k tokens, carry {base_carry:.0f} USD')

print('\n## Main-context carry cost by category (write once + re-read on later calls), top 45')
tot_carry = sum(carry.values()) + base_carry
print(f'  {"base load (system, tools, CLAUDE.md, listings)":48} carry {base_carry:7.1f} USD {100*base_carry/tot_carry:4.1f}%')
groups = collections.defaultdict(float)
for cat, v in carry.items(): groups[cat.split(':')[0]] += v
for cat, v in sorted(carry.items(), key=lambda x: -x[1])[:45]:
    print(f'  {cat:48} n {cnt[cat]:5} tok {toks[cat]/1e6:6.2f}M carry {v:7.1f} USD {100*v/tot_carry:4.1f}%  mean {toks[cat]/cnt[cat]:7.0f} tok')
print('  -- grouped:')
for g, v in sorted(groups.items(), key=lambda x: -x[1]): print(f'  {g:30} {v:8.1f} USD {100*v/tot_carry:4.1f}%')
print(f'  carry total {tot_carry:.0f} USD vs main cache_read+cache_write {sum(money[("main",f,p)] for f in PRICE for p in ("cache_read","cache_write")):.0f} USD')

print('\n## Main Bash results by class: n, median/p90/max chars, total chars')
for bc, l in sorted(bash_chars.items(), key=lambda x: -sum(x[1])):
    print(f'  {bc:10} n {len(l):5} {statistics.median(l):7.0f} {pct(l,.9):7.0f} {max(l):7.0f} total {sum(l)/1e6:5.2f}M')

print('\n## Agents: runs, USD total, USD/run median, turns median, output median, thinking share of output, brief/report chars median')
for at, a in sorted(agent.items(), key=lambda x: -agent_cost[x[0]])[:22]:
    out = sum(a['out']); th = sum(a['think'])
    key = at.split(':')[-1]
    bk = next((v for k, v in brief_chars.items() if k.split(':')[-1] == key), [])
    rp = next((v for k, v in report_chars.items() if k.split(':')[-1] == key), [])
    print(f'  {at:36} runs {len(a["cost"]):4} ${agent_cost[at]:7.1f} ${statistics.median(a["cost"]):5.2f}/run turns {statistics.median(a["turns"]):4.0f} '
          f'out {statistics.median(a["out"]):6.0f} think {100*th/out if out else 0:3.0f}%  brief {statistics.median(bk) if bk else 0:6.0f} report {statistics.median(rp) if rp else 0:6.0f}')
