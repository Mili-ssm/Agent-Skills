#!/usr/bin/env python3
"""Second pass: errors by agent type, rework, main context size, reviewer output shape."""
import json, os, re, glob, collections
from datetime import datetime, timedelta, timezone
ROOT = os.path.expanduser('~/.claude/projects')
SINCE = datetime.now(timezone.utc) - timedelta(days=7)
C = collections.Counter
import sys
SELF = sys.argv[1] if len(sys.argv) > 1 else '\0'  # id of the session running the study, to exclude it
def short(p): return p.rsplit('-Private-', 1)[-1].rsplit('-WORK-', 1)[-1][:22]

ERR = [('sleep-blocked', 'Blocked: sleep'), ('no tool bash', 'No such tool available: bash'),
       ('no tool Monitor', 'No such tool available: Monitor'), ('no tool TaskStop', 'No such tool available: TaskStop'),
       ('worktree isolated', 'isolated in the worktree'), ('zsh alias fn', 'defining function based on alias'),
       ('zsh no matches', 'no matches found'), ('zsh = not found', '= not found'), ('zsh bad subst', 'bad substitution'),
       ('classifier denied', 'auto mode classifier'), ('safety check', 'built-in Claude Code safety check'),
       ('user rejected', "doesn't want to proceed"), ('mem shrink', 'use --shrink'), ('webfetch size', 'maxContentLength'),
       ('file modified since read', 'modified since read'), ('not read yet', 'has not been read yet')]
err_by = C(); impl_kind = C(); rev_kind = C(); gp_model_kind = C()
main_ctx = collections.defaultdict(list); main_turns = C(); main_parts = collections.defaultdict(lambda: C())
rev_parts = C(); impl_parts = C(); gp_parts = C()
dur = collections.defaultdict(list); sendmsg = C(); ask = C()
sub_first_len = collections.defaultdict(list); sub_final_len = collections.defaultdict(list)
classifier_reasons = C(); bash_per_run = collections.defaultdict(list)
rev_think = []; inline_checks_by_proj = C(); cr_by_proj = C()

for f in glob.glob(ROOT + '/**/*.jsonl', recursive=True):
    if os.path.getmtime(f) < SINCE.timestamp() or SELF in f: continue
    proj = short(os.path.relpath(f, ROOT).split('/')[0])
    is_sub = '/subagents/' in f; atype = 'main'
    if is_sub:
        try: atype = json.load(open(f[:-6] + '.meta.json')).get('agentType') or '?'
        except Exception: atype = 'workflow'
    seen = set(); id2 = {}; first = True; t0 = t1 = None; nbash = 0; last_text = 0
    for line in open(f, errors='replace'):
        if '"api-request' in line[:300]: continue
        try: r = json.loads(line)
        except Exception: continue
        ts = r.get('timestamp')
        if ts:
            try:
                d = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if d < SINCE: continue
                t0 = t0 or d; t1 = d
            except Exception: pass
        t = r.get('type'); m = r.get('message') or {}
        if t == 'assistant':
            u = m.get('usage') or {}; mid = m.get('id')
            if mid and mid not in seen and u:
                seen.add(mid)
                parts = C(inp=u.get('input_tokens', 0), cw=u.get('cache_creation_input_tokens', 0),
                          cr=u.get('cache_read_input_tokens', 0), out=u.get('output_tokens', 0))
                if not is_sub:
                    main_ctx[proj].append(parts['inp'] + parts['cw'] + parts['cr']); main_turns[proj] += 1
                    main_parts[proj].update(parts)
                elif atype.endswith('skeptical-reviewer'): rev_parts.update(parts)
                elif atype.endswith('implementer'): impl_parts.update(parts)
                elif atype == 'general-purpose': gp_parts.update(parts)
            for b in m.get('content') or []:
                if not isinstance(b, dict): continue
                if b.get('type') == 'text': last_text = len(b.get('text') or '')
                if b.get('type') != 'tool_use' or b.get('id') in id2: continue
                name = b.get('name'); inp = b.get('input') or {}; id2[b['id']] = name
                if name in ('Bash', 'bash'): nbash += 1
                if is_sub: continue
                if name == 'SendMessage': sendmsg[proj] += 1
                if name == 'AskUserQuestion': ask[proj] += 1
                if name == 'Bash' and re.search(r'\b(pytest|cargo (test|build|clippy|check)|validate\.py|npm run|ruff)\b', inp.get('command') or ''):
                    inline_checks_by_proj[proj] += 1
                if name == 'Agent':
                    st = (inp.get('subagent_type') or 'general-purpose'); desc = (inp.get('description') or '').lower()
                    pr = (inp.get('prompt') or '').lower()
                    if st.endswith('check-runner'): cr_by_proj[proj] += 1
                    if st.endswith('implementer'):
                        k = 'fix round' if re.search(r'\bfix|round [2-9]|re-?work|follow-?up', desc) else 'task'
                        impl_kind[(proj, k)] += 1
                    elif st.endswith('skeptical-reviewer'):
                        k = ('round 2+' if re.search(r'round [2-9]|re-?review|second', desc + pr[:1500]) else
                             'process' if 'process' in desc else 'pre-push/pr' if re.search(r'push|pr\b|merge|commit', desc) else 'review')
                        rev_kind[(proj, k)] += 1
                    elif st == 'general-purpose':
                        k = ('fact-check' if 'fact' in desc else 'review' if 'review' in desc else 'write/wave' if re.search(r'wave|writ|note|alias', desc)
                             else 'apply/fix' if re.search(r'apply|fix', desc) else 'lookup/judge' if re.search(r'lookup|judge', desc) else 'other')
                        gp_model_kind[(proj, k, inp.get('model') or '-')] += 1
        elif t == 'user':
            c = m.get('content')
            if is_sub and first:
                first = False
                txt = c if isinstance(c, str) else ' '.join(x.get('text', '') for x in c or [] if isinstance(x, dict))
                sub_first_len[atype].append(len(txt))
            if isinstance(c, str): continue
            for b in c or []:
                if not isinstance(b, dict) or b.get('type') != 'tool_result' or not b.get('is_error'): continue
                cc = b.get('content')
                txt = cc if isinstance(cc, str) else ' '.join(x.get('text', '') for x in cc or [] if isinstance(x, dict))
                for k, pat in ERR:
                    if pat in txt:
                        err_by[(k, atype.replace('agent-skills:', ''))] += 1
                        if k == 'classifier denied':
                            mm = re.search(r'Reason: (.{0,110})', txt)
                            classifier_reasons[(atype.replace('agent-skills:', ''), re.sub(r'\s+', ' ', mm.group(1)) if mm else '?')] += 1
                        break
    if is_sub and t0 and t1:
        dur[atype].append((t1 - t0).total_seconds()); bash_per_run[atype].append(nbash); sub_final_len[atype].append(last_text)

def med(l): l = sorted(l); return l[len(l)//2] if l else 0
def p90(l): l = sorted(l); return l[int(len(l)*.9)] if l else 0
print('## errors by category and agent')
cur = None
for (k, a), v in sorted(err_by.items(), key=lambda x: (x[0][0], -x[1])):
    if k != cur: print(f' {k}: total {sum(n for (kk, _), n in err_by.items() if kk == k)}'); cur = k
    print(f'     {v:>4} {a}')
print('\n## classifier denial reasons'); [print(f'  {v:>3} {k[0]:20} {k[1]}') for k, v in classifier_reasons.most_common(25)]
print('\n## implementer dispatch kinds'); [print(f'  {v:>4} {k}') for k, v in sorted(impl_kind.items())]
print('\n## reviewer dispatch kinds'); [print(f'  {v:>4} {k}') for k, v in sorted(rev_kind.items())]
print('\n## general-purpose kinds (proj, kind, model)'); [print(f'  {v:>4} {k}') for k, v in gp_model_kind.most_common(30)]
print('\n## main sessions: turns, median/p90/max context tokens per turn, token parts (M)')
for p in main_turns:
    l = main_ctx[p]; mp = main_parts[p]
    print(f'  {p:24} turns {main_turns[p]:>5} ctx {med(l)//1000}k/{p90(l)//1000}k/{max(l)//1000}k  in {mp["inp"]/1e6:.1f} cw {mp["cw"]/1e6:.1f} cr {mp["cr"]/1e6:.0f} out {mp["out"]/1e6:.2f}  sendmsg {sendmsg[p]} ask {ask[p]} inline-checks {inline_checks_by_proj[p]} check-runner {cr_by_proj[p]}')
for n, pp in (('reviewer', rev_parts), ('implementer', impl_parts), ('general-purpose', gp_parts)):
    print(f'  {n:16} in {pp["inp"]/1e6:.1f} cw {pp["cw"]/1e6:.1f} cr {pp["cr"]/1e6:.0f} out {pp["out"]/1e6:.2f}')
print('\n## per agent: median/p90 duration s, median/p90 Bash calls, median brief chars, median final text chars')
for a in sorted(dur, key=lambda a: -len(dur[a])):
    if len(dur[a]) < 3: continue
    print(f'  {a.replace("agent-skills:", ""):22} n {len(dur[a]):>4} dur {med(dur[a]):>5.0f}/{p90(dur[a]):>5.0f} bash {med(bash_per_run[a])}/{p90(bash_per_run[a])} brief {med(sub_first_len[a]):>6} final {med(sub_final_len[a]):>6}')
