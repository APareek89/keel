# Keel

A persistent context layer for AI coding sessions. It remembers how you work, what you
decided, and who you work with — so you stop re-briefing the model every morning.

Keel is a Claude Code skill plus a plain-markdown knowledge base at `~/brain`. It also
works in Codex. There is no server, no database and no account.

```
/keel orient     Load what matters for what you're working on
/keel brief      Morning brief: pending, owed, waiting, stale
/keel todo       Open loops and live risks
/keel brain      Visual map of everything it knows
/keel health     Is it being fed, still true, still retrievable?
/keel missing    What it should know and doesn't
/keel review     Approve or reject captured proposals
/keel remember   Capture something from this conversation
```

## The problem

Every session starts from zero. You re-explain who you are, how you want a document
structured, what was already decided, which option you rejected and why. The AI is a
capable contractor who has never worked here before — every single morning.

The obvious fix is "give it memory". But retrieval isn't the hard part, and facts aren't
what's being lost. What dies when a session closes is *judgement*: the decision you
reached, the three options you rejected and the reason, the fact that your CFO stops
reading after page one. None of that is sitting in a document waiting to be searched.

## The model: two layers

This is the part that matters, and it's the thing most "second brain" designs get wrong.

**Graph — things with identity.** People, orgs, tasks, task types, skills, systems. They
persist, they relate to each other, and walking between them is meaningful. This layer
stays small — tens of nodes — which is what keeps it legible and traversal cheap.

**Wiki — statements about those things.** Decisions, risks, constraints, preferences,
playbooks, notes. Prose, *read* rather than traversed, growing without bound. Each carries
an `about:` reference into the graph; that reference is its only link.

Putting a decision *in* the graph ruins both layers. Decisions rarely relate to other
decisions in a way worth walking — they are statements about a project or a kind of work.
Made into nodes they swamp the graph and turn a map into a hairball, while their content
still has to be read to be useful.

|  | Graph | Wiki |
|---|---|---|
| Holds | entities | statements about entities |
| Types | `person` `org` `task` `task_type` `skill` `system` | `decision` `risk` `constraint` `preference` `playbook` `note` |
| Links via | `edges:` entity → entity | `about:` document → entity |
| Found by | traversal from an anchor | pulled via `about:`, or searched |
| Grows | slowly, bounded | continuously, unbounded |

A project is just a task with children — one recursive type via `part_of`, not two types.

### Retrieval is two-step

1. **Anchor in the graph.** Which entities does this session touch? Walk one hop.
2. **Pull the wiki.** Read documents whose `about:` names those entities, ranked by type
   (constraints and scoped preferences first) and recency.

If a `task_type` is among the anchors, one hop pulls the playbook, the scoped preferences
and the constraints for that kind of work together. That is the whole reason the type
layer exists.

## Two rules that keep it trustworthy

**Nothing is deleted, and nothing waits for approval.** A memory that is 80% right is
worse than none — but a review queue nobody walks through is not the fix. It rots while the
graph stays frozen. So everything enters the brain immediately carrying keywords that say
how much weight to give it: `use`, `cite`, `confirm`, `verify`, `ignore`. A single capture
is `cite` — apply it, but say it is unconfirmed. A project quiet for three weeks is
`confirm` — ask before building on it. Nothing is ever removed; it just stops being
loaded.

**Everything expires.** Relevance and evidence are recomputed nightly from measured
activity, and every node carries `review_by`. A brain where nothing expires rots
quietly until a stale fact embarrasses you — and then you stop trusting all of it.
`keel health` surfaces expiries, contradictions, broken references and unanchored
documents.

## Install

```bash
git clone https://github.com/APareek89/keel.git
mkdir -p ~/.claude/skills/keel
cp -r keel/SKILL.md keel/scripts ~/.claude/skills/keel/
mkdir -p ~/brain/{graph/{people,orgs,tasks,task_types,skills},wiki/{decisions,risks,constraints,preferences,playbooks,notes},loops,inbox,_templates,_index}
cp -r keel/templates/* ~/brain/_templates/
```

Then run `/keel` in Claude Code. First invocation runs setup.

### Let it build itself (recommended)

Without this, the brain only grows when you remember to run `/keel remember`, and only
reaches the graph when you remember to run `/keel review`. In practice neither happens, and
you end up with a full inbox and a graph frozen on install day.

`autobrain.py` reads your own Claude Code and Codex transcripts from disk, measures how
much *active* time went into each topic, and writes when repetition and time both clear:

```bash
python3 ~/.claude/skills/keel/scripts/autobrain.py scan      # see it before trusting it
python3 ~/.claude/skills/keel/scripts/autobrain.py promote   # dry run; --apply to write
```

Then schedule `scripts/nightly.sh`. On macOS, a launchd agent at 02:30:

```bash
cp scripts/nightly.sh ~/.claude/skills/keel/scripts/ && chmod +x ~/.claude/skills/keel/scripts/nightly.sh
cp examples/com.keel.autobrain.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.keel.autobrain.plist
```

Logs land in `~/brain/_index/nightly.log`. Remove it with
`launchctl bootout gui/$(id -u)/com.keel.autobrain`.

It writes a `task` node for sustained work that has none, flags nodes the work has moved
past, and promotes repeated captures out of the inbox. It never rewrites prose — no
pattern-match can tell that a sentence stopped being true, so it flags the node and leaves
the rewrite to a session.

**Set up `~/brain/_index/lexicon.json` first** (see `examples/lexicon.example.json`). It
maps topics to the phrases you actually type, and it is the difference between this working
and silently reporting nothing. Keep the phrases distinctive: one generic word merges
unrelated topics into identical figures that look like real data.

### Load preferences into every session (optional)

A `SessionStart` hook puts your profile and standing preferences into context before you
type anything. Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ {
          "type": "command",
          "command": "python3 $HOME/.claude/skills/keel/scripts/autobrain.py session-start --days 14",
          "timeout": 15
      } ] }
    ]
  }
}
```

It also appends a **live-topics block** — what you have actually spent time on lately, and
whether the brain is behind it. Reads a 12h cache, so it costs ~80ms. It fails silently and
exits 0 if the brain is missing, so a broken hook never blocks a session.
(`scripts/session_start.py` is a shim onto the same code, for existing installs.)

### MCP server — one brain, every client

A local stdio MCP server exposes the brain to Claude Desktop, Codex and Cursor.
**No database, no auth, no hosting** — it is a process on your own machine reading
your own markdown. The files are the database.

```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{ "mcpServers": { "keel": {
    "command": "python3",
    "args": ["/Users/YOU/.claude/skills/keel/scripts/mcp_server.py"] } } }
```

```toml
# ~/.codex/config.toml
[mcp_servers.keel]
command = "python3"
args = ["/Users/YOU/.codex/skills/keel/scripts/mcp_server.py"]
```

Seven tools: `keel_recall` `keel_remember` `keel_list_entities` `keel_read`
`keel_health` `keel_missing` `keel_todo`. Check it before wiring a client:

```bash
python3 scripts/mcp_server.py --selftest
```

This is what makes the brain *shared* rather than copied. Without it each client
holds its own snapshot and they drift; with it, a capture from Claude Desktop
lands in the same inbox as one from Claude Code.

**claude.ai in a browser is the one surface this does not reach** — a local server
is not reachable from a web page. Upload the brain to a Project for read-only use
there. Remote MCP would fix it and is deliberately not built: hosting other
people's brains means auth, storage and a privacy surface, which is a company
rather than a tool you can `git clone`.

### Keeping both clients in sync

Claude Code and Codex each keep their own copy of the skill, and they drift. Run this after
every change, from a checkout:

```bash
./scripts/sync-clients.sh
```

It backs up each client directory before overwriting, and skips clients that do not have
the skill installed.

### Codex skill

Codex has no session-start hook, so its always-loaded file *is* the hook:

```bash
python3 ~/.claude/skills/keel/scripts/brain.py export-codex
```

Writes your profile and preferences into `~/.codex/AGENTS.md` between managed markers, so
anything you wrote in that file survives. Re-run when preferences change; `health` flags
the export when it goes stale.

## Commands

```bash
python3 ~/.claude/skills/keel/scripts/brain.py health         # fed? true? retrievable?
python3 ~/.claude/skills/keel/scripts/brain.py missing        # structural gaps
python3 ~/.claude/skills/keel/scripts/brain.py todo           # open loops, live risks
python3 ~/.claude/skills/keel/scripts/brain.py view           # HTML map + graph
python3 ~/.claude/skills/keel/scripts/brain.py export-codex   # sync to Codex
```

Standard library only. No pip install, no external assets — the generated HTML works
offline and nothing leaves the machine.

## Examples

`examples/` holds three fully-populated brains for different roles, all synthetic:

| Example | Role | Entities | Documents |
|---|---|---|---|
| `marketing/` | Head of Growth Marketing, D2C brand | 24 | 10 |
| `consulting/` | Engagement Manager, cost transformation | 22 | 10 |
| `sales/` | VP Sales, B2B SaaS moving upmarket | 23 | 11 |

Render any of them to see the shape of a mature brain:

```bash
BRAIN_DIR=examples/sales python3 scripts/brain.py view
```

Worth opening `sales/wiki/risks/` — the Meridian deal is forecast at 70% and is really 40%,
because the economic buyer has never been met. That is the kind of thing a brain is for:
not the fact, but the judgement about the fact.

## Privacy

Your brain is plain markdown on your own disk. Nothing is uploaded. Keep `~/brain` out of
any repository you publish — it will contain colleagues by name, commitments, and whatever
your work involves. The generated `_index/brain.html` maps all of it; treat it as private.

## Status

Working, and in daily use by its author. Overnight capture and the MCP server are both in.
Not yet built: a graph index inside the MCP server, so retrieval is a lookup rather than a
filesystem walk, and Cursor support.

MIT.
