"""Memory plugin usage from Claude Code transcripts (read-only over ~/.claude/projects).

Usage: python3 memory_usage.py [FIRST_DAY [LAST_DAY]]   (YYYY-MM-DD, by a session's first record; default: the last 14 days)
Counts tool calls once per tool_use id. Prints project folder names: do not paste them into the repository.
"""
import json, re, glob, os, collections, sys, datetime, statistics
SINCE = sys.argv[1] if len(sys.argv) > 1 else (datetime.date.today() - datetime.timedelta(days=13)).isoformat()
UNTIL = sys.argv[2] if len(sys.argv) > 2 else "9999-12-31"
SINCE_TS = datetime.datetime.fromisoformat(SINCE).replace(tzinfo=datetime.timezone.utc).timestamp()
root = os.path.expanduser("~/.claude/projects")
MEMRE = re.compile(r'(?:^|[\s;&|(`$/"\'])mem"?\s+(search|remember|show|memories|memory|note|synthesis|supersede|confirm|refute|forget|curate|review|observe|unify|merge|promote|history|settle|check|similar)\b')
sess = []
sub = collections.Counter(); sub_files = 0; sub_with_mem = 0
for f in glob.glob(root + "/**/*.jsonl", recursive=True):
    if os.path.getmtime(f) < SINCE_TS: continue
    is_sub = "/subagents/" in f
    seen = set(); s = dict(file=f, proj=f.split("/projects/")[1].split("/")[0], cmds=collections.Counter(),
        skills=collections.Counter(), agents=collections.Counter(), automem=0, compacts=0, summ_nyr=0,
        rem_after_compact=0, followed=[], first_edit=None, first_search=None, first_web=None, n=0, cwd=None, t0=None, t1=None, entry=None, prompts=0)
    idx = 0; compacted = False
    for line in open(f, errors="ignore"):
        try: d = json.loads(line)
        except: continue
        t = d.get("timestamp")
        if t:
            s["t0"] = s["t0"] or t; s["t1"] = t
        s["cwd"] = s["cwd"] or d.get("cwd"); s["entry"] = s["entry"] or d.get("entrypoint")
        if d.get("type") == "system" and d.get("subtype") == "compact_boundary":
            s["compacts"] += 1; compacted = True
        if d.get("isCompactSummary"):
            txt = json.dumps(d.get("message", {}))
            if "not yet recorded" in txt.lower(): s["summ_nyr"] += 1; s["followed"].append(False)
        m = d.get("message") or {}
        if d.get("type") == "user" and isinstance(m.get("content"), str) and not d.get("isMeta") and not d.get("isCompactSummary"):
            s["prompts"] += 1
        cont = m.get("content")
        if not isinstance(cont, list): continue
        for b in cont:
            if not isinstance(b, dict) or b.get("type") != "tool_use": continue
            if b.get("id") in seen: continue
            seen.add(b.get("id")); idx += 1
            name = b.get("name"); inp = b.get("input") or {}
            if name == "Bash":
                for mm in MEMRE.finditer(inp.get("command", "")):
                    s["cmds"][mm.group(1)] += 1
                    if mm.group(1) == "search" and s["first_search"] is None: s["first_search"] = idx
                    if mm.group(1) == "remember" and compacted: s["rem_after_compact"] += 1
                    if mm.group(1) == "remember" and s["followed"]: s["followed"][-1] = True
            elif name == "Skill":
                s["skills"][inp.get("skill", "")] += 1
            elif name in ("Agent", "Task"):
                s["agents"][inp.get("subagent_type", "general-purpose")] += 1
                if (inp.get("subagent_type") or "").split(":")[-1] == "researcher" and s["first_web"] is None: s["first_web"] = idx  # not memory-researcher, which reads the memory first
                if inp.get("subagent_type") == "memory:memory-recorder" and s["followed"]: s["followed"][-1] = True
            elif name in ("WebSearch", "WebFetch"):
                if s["first_web"] is None: s["first_web"] = idx
            elif name in ("Write", "Edit"):
                p = inp.get("file_path", "")
                if "/.claude/projects/" in p and "/memory/" in p: s["automem"] += 1
                elif s["first_edit"] is None: s["first_edit"] = idx
    if s["t0"] is None or not (SINCE <= s["t0"][:10] <= UNTIL): continue
    if is_sub:
        sub_files += 1
        if s["cmds"]: sub_with_mem += 1
        sub.update(s["cmds"]); continue
    sess.append(s)

headless = [s for s in sess if s["entry"] in ("sdk-cli", "sdk-py", "sdk-ts") or (s["cwd"] or "").startswith(os.path.expanduser("~/.local"))]
inter = [s for s in sess if s not in headless and s["prompts"] > 0]
print(f"main transcripts {SINCE} to {UNTIL}: {len(sess)}  headless/sdk: {len(headless)}  interactive w/ prompts: {len(inter)}")
print("entrypoints:", collections.Counter(s['entry'] for s in sess))
def agg(L, key):
    c = collections.Counter()
    for s in L: c.update(s[key])
    return c
print("\n== interactive sessions ==")
print("mem cmds:", dict(agg(inter, "cmds").most_common()))
print("sessions with >=1 mem search:", sum(1 for s in inter if s["cmds"]["search"]), "/", len(inter))
print("sessions with >=1 mem remember:", sum(1 for s in inter if s["cmds"]["remember"]), "/", len(inter))
print("sessions with auto-memory writes:", sum(1 for s in inter if s["automem"]), " total writes:", sum(s["automem"] for s in inter))
mskills = {k: v for k, v in agg(inter, "skills").items() if "memory" in k}
print("memory skills loaded:", mskills)
print("memory agents:", {k: v for k, v in agg(inter, "agents").items() if k.startswith("memory")})
edit_sessions = [s for s in inter if s["first_edit"]]
before = sum(1 for s in edit_sessions if s["first_search"] and s["first_search"] < s["first_edit"])
print(f"sessions that edited files: {len(edit_sessions)}; searched mem before first edit: {before}; searched only after: {sum(1 for s in edit_sessions if s['first_search'] and s['first_search']>s['first_edit'])}; never searched: {sum(1 for s in edit_sessions if not s['first_search'])}")
comp = [s for s in inter if s["compacts"]]
print(f"\ncompacted sessions: {len(comp)} (compactions: {sum(s['compacts'] for s in comp)}); summaries with 'not yet recorded': {sum(s['summ_nyr'] for s in comp)}; of those, followed by mem remember or memory-recorder before the next summary: {sum(sum(s['followed']) for s in comp)}; sessions with mem remember after a compaction: {sum(1 for s in comp if s['rem_after_compact'])}")
print("\n== per project (interactive) ==")
pp = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
for s in inter:
    p = pp[s["proj"][-45:]]; p[0] += 1; p[1] += s["cmds"]["search"]; p[2] += s["cmds"]["remember"]; p[3] += s["automem"]; p[4] += s["compacts"]
for k, v in sorted(pp.items(), key=lambda x: -x[1][0]): print(f"{v[0]:4d} sess  search {v[1]:4d}  remember {v[2]:4d}  automem {v[3]:3d}  compacts {v[4]:3d}  {k}")
print("\n== per day (interactive) ==")
dd = collections.defaultdict(lambda: [0, 0, 0, 0])
for s in inter:
    d = dd[s["t0"][:10]]; d[0] += 1; d[1] += 1 if s["cmds"]["search"] else 0; d[2] += s["cmds"]["search"]; d[3] += s["cmds"]["remember"]
for k in sorted(dd): print(k, "sessions", dd[k][0], "with-search", dd[k][1], "searches", dd[k][2], "remembers", dd[k][3])
print(f"\n== subagents == files {sub_files}, with mem call {sub_with_mem}; cmds {dict(sub.most_common())}")
print("headless mem cmds:", dict(agg(headless, "cmds").most_common()))

# Outcome metrics. Logs: $MEM_DATA, else $XDG_STATE_HOME/agent-memory, else ~/.local/state/agent-memory.
DATA = os.environ.get("MEM_DATA") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "agent-memory")
def read_log(rel):
    """Lines of a JSON-lines log whose date (t) is inside the window; None when the log is missing."""
    path = os.path.join(DATA, rel)
    if not os.path.isfile(path): return None
    out = []
    for line in open(path, errors="ignore"):
        try: d = json.loads(line)
        except ValueError: continue
        if isinstance(d, dict) and SINCE <= str(d.get("t", ""))[:10] <= UNTIL: out.append(d)
    return out
def ts(d):
    try: return datetime.datetime.strptime(d["t"], "%Y-%m-%dT%H:%M:%SZ").timestamp()
    except (KeyError, ValueError, TypeError): return None
def pct(v, q):
    v = sorted(v); return v[min(len(v) - 1, int(q * len(v)))] if v else 0
print("\n== outcome metrics ==")
web = [s for s in inter if s["first_web"]]
print(f"M2 sessions with web research before any mem search: {sum(1 for s in web if not s['first_search'] or s['first_web'] < s['first_search'])} / sessions with web research: {len(web)}")
usage = read_log("usage/log.jsonl")
if usage is None: print("M3 no log")
else:
    searches = [d for d in usage if d.get("cmd") == "search" and ts(d) is not None]
    shows = [(ts(d), set(d.get("paths") or [])) for d in usage if d.get("cmd") == "show" and ts(d) is not None]
    hit = sum(1 for d in searches if any(0 <= t - ts(d) <= 1800 and p & set(d.get("results") or []) for t, p in shows))
    print(f"M3 searches followed within 30 minutes by mem show of a returned record: {hit} / {len(searches)}")
hooks = read_log("hooks/log.jsonl")
if hooks is None: print("M5 no log\nM8 no log")
else:
    pc = [d for d in hooks if d.get("hook") == "post-compact"]
    print(f"M5 compactions: {len(pc)}; with a handoff block: {sum(1 for d in pc if d.get('handoff'))}; marker without a parsed block: {sum(1 for d in pc if d.get('marker') and not d.get('handoff'))}; with all six fields: {sum(1 for d in pc if len(d.get('handoff') or []) == 6)}; unrecorded items: {sum(d.get('unrecorded') or 0 for d in pc)}; mismatch lines shown: {sum(d.get('mismatches') or 0 for d in pc)}; post-compact ms p90: {pct([d.get('ms') or 0 for d in pc], 0.9)}")
    ch = [d["chars"] for d in hooks if d.get("hook") == "session-index" and isinstance(d.get("chars"), int)]
    print(f"M8 characters injected by session-index: median {int(statistics.median(ch)) if ch else 0}, max {max(ch) if ch else 0} per call")
