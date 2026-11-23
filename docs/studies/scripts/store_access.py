"""How agents reach the mem store: `mem` commands vs direct file tools. Read-only over ~/.claude/projects.

Counts each tool_use id once. Prints aggregate counts only (no project names, no file contents).
"""
import collections, glob, json, os, re, sys, time

DAYS = float(sys.argv[1]) if len(sys.argv) > 1 else 3
since = time.time() - DAYS * 86400
home = os.path.expanduser("~")
STORE = home + "/.local/share/agent-memory/store"
SUBS = ("search|remember|show|read|memories|memory|note|synthesis|supersede|confirm|refute|forget|curate|review|observe|"
        "unify|merge|promote|history|settle|check|similar|rules|triage|find|related|passages|stats|topics|new|import|"
        "session-index|signal|terms|projects|init|distinct|restore|reminders|run|fill|due|apply")
MEM = re.compile(r'(?:^|[\s;&|(`$/"\'])mem(?:-[a-z]+)?"?\s+(' + SUBS + r')\b')
SHELL_READ = re.compile(r'\b(cat|sed|head|tail|grep|rg|ugrep|less|awk|find|ls|wc|python3?)\b')


def area(path: str) -> str | None:
    p = path.replace("~", home)
    if "/.sources/" in p and STORE in p:
        return "store:.sources"
    if p.startswith(STORE) or "agent-memory/store" in p:
        rest = p[len(STORE):].lstrip("/").split("/")[0] if p.startswith(STORE) else "?"
        return "store:" + (rest or "root")
    if "/.memory/" in p or p.endswith("/.memory"):
        return "project:.memory"
    if "/.claude/projects/" in p and "/memory/" in p:
        return "auto-memory"
    return None


counts = collections.Counter()          # (who, class) -> n
areas = collections.Counter()           # (who, class, area) -> n
memcmds = collections.Counter()
sessions_direct = collections.Counter()  # who -> sessions with any direct store read
sessions_mem = collections.Counter()
nfiles = collections.Counter()
for f in glob.glob(home + "/.claude/projects/**/*.jsonl", recursive=True):
    if os.path.getmtime(f) < since or (len(sys.argv) > 2 and sys.argv[2] in f):
        continue
    who = "subagent" if "/subagents/" in f else "main"
    nfiles[who] += 1
    seen, had_direct, had_mem = set(), False, False
    for line in open(f, errors="ignore"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msg = d.get("message") or {}
        if d.get("type") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for c in msg["content"]:
            if c.get("type") != "tool_use" or c.get("id") in seen:
                continue
            seen.add(c.get("id"))
            name, inp = c.get("name", ""), c.get("input") or {}
            if name == "Bash":
                cmd = inp.get("command", "")
                hits = MEM.findall(cmd)
                if hits:
                    had_mem = True
                    counts[(who, "mem command")] += 1
                    for h in hits:
                        memcmds[h] += 1
                touched = {a for a in (area(t) for t in re.findall(r'[~/][^\s"\'|;&<>)]+', cmd)) if a}
                if touched and SHELL_READ.search(cmd) and not hits:
                    had_direct = True
                    counts[(who, "shell on store files")] += 1
                    for a in touched:
                        areas[(who, "shell", a)] += 1
            elif name in ("Read", "Grep", "Glob", "Edit", "Write", "MultiEdit"):
                path = inp.get("file_path") or inp.get("path") or ""
                a = area(path) if path else None
                if a:
                    kind = "write tool on store files" if name in ("Edit", "Write", "MultiEdit") else "read tool on store files"
                    if kind.startswith("read"):
                        had_direct = True
                    counts[(who, kind)] += 1
                    areas[(who, name, a)] += 1
            elif name.startswith("mcp__fff__"):
                path = json.dumps(inp)
                if area(path) or "agent-memory" in path:
                    had_direct = True
                    counts[(who, "fff search on store")] += 1
    sessions_direct[who] += had_direct
    sessions_mem[who] += had_mem

print(f"transcripts (last {DAYS:g} days): {dict(nfiles)}")
print(f"sessions using mem commands: {dict(sessions_mem)}; with direct store reads: {dict(sessions_direct)}")
print("\nCalls by class:")
for (who, k), n in sorted(counts.items()):
    print(f"  {who:9} {k:28} {n}")
print("\nDirect access by tool and area (top 25):")
for (who, tool, a), n in areas.most_common(25):
    print(f"  {who:9} {tool:6} {a:22} {n}")
print("\nmem subcommands (top 15):", memcmds.most_common(15))
