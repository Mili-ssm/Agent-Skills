import json,os,re,glob,sys,time,collections
from datetime import datetime as D, timedelta, timezone
SELF = sys.argv[1] if len(sys.argv) > 1 else '\0'  # id of the session running the study, to exclude it
SINCE = datetime_since = D.now(timezone.utc) - timedelta(days=7)
ROOT=os.path.expanduser('~/.claude/projects'); since=time.time()-7*86400
PAT=re.compile(r'\b(pytest|cargo (test|build|clippy|check)|validate\.py|npm run|ruff)\b')
sizes=[];trim=0;n=0;big=[];bykind=collections.defaultdict(list);bg=0;gap=[]
for f in glob.glob(ROOT+'/*/*.jsonl'):
    if os.path.getmtime(f)<since or SELF in f: continue
    pend={}
    for l in open(f,errors='replace'):
        if '"api-request' in l[:300]: continue
        try:r=json.loads(l)
        except: continue
        ts0=r.get('timestamp')
        if ts0:
            try:
                if D.fromisoformat(ts0.replace('Z','+00:00'))<SINCE: continue
            except Exception: pass
        m=r.get('message') or {}; c=m.get('content')
        if not isinstance(c,list): continue
        for b in c:
            if not isinstance(b,dict): continue
            if b.get('type')=='tool_use' and b.get('name')=='Bash':
                cmd=(b.get('input') or {}).get('command') or ''
                mm=PAT.search(cmd)
                if mm:
                    pend[b['id']]=(mm.group(1),bool(re.search(r'\|\s*(tail|head|grep)|-q\b|--quiet',cmd)),bool((b.get('input') or {}).get('run_in_background')),r.get('timestamp'))
            if b.get('type')=='tool_result' and b.get('tool_use_id') in pend:
                k,tr,isbg,ts=pend.pop(b['tool_use_id'])
                t=b.get('content'); t=t if isinstance(t,str) else ' '.join(x.get('text','') for x in t or [] if isinstance(x,dict))
                n+=1; sizes.append(len(t)); trim+=tr; bg+=isbg; bykind[k].append(len(t))
                try:
                    gap.append((D.fromisoformat(r['timestamp'].replace('Z','+00:00'))-D.fromisoformat(ts.replace('Z','+00:00'))).total_seconds())
                except Exception: pass
sizes.sort(); gap.sort()
q=lambda l,p:l[int(len(l)*p)] if l else 0
print('n',n,'trimmed by tail/head/grep/-q',trim,'background',bg)
print('result chars median/p90/max/sum',q(sizes,.5),q(sizes,.9),sizes[-1] if sizes else 0,sum(sizes),'~tokens sum',sum(sizes)//4)
print('over 4000 chars',sum(s>4000 for s in sizes),'over 20000',sum(s>20000 for s in sizes))
print('wall seconds median/p90/max',q(gap,.5),q(gap,.9),gap[-1] if gap else 0,'over 60s',sum(g>60 for g in gap),'sum min',round(sum(gap)/60))
for k,v in sorted(bykind.items(),key=lambda x:-len(x[1])): v.sort(); print(f'  {k:14} n {len(v):>4} median {q(v,.5):>6} p90 {q(v,.9):>6}')
