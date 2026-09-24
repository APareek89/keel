# Keel

A persistent context layer for AI coding sessions. It remembers how you work, what you
decided, and who you work with — so you stop re-briefing the model every morning.

Keel is a Claude Code skill plus a plain-markdown knowledge base at `~/brain`. It also
works in Codex, and in Claude Desktop, Cursor or any MCP client through a local MCP
server. Nothing is hosted: no database, no account — the markdown files are the database.

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
playbooks, commitments, notes. Prose, *read* rather than traversed, growing without
bound. Each carries an `about:` reference into the graph; that reference is its only link.

Putting a decision *in* the graph ruins both layers. Decisions rarely relate to other
decisions in a way worth walking — they are statements about a project or a kind of work.
Made into nodes they swamp the graph and turn a map into a hairball, while their content
still has to be read to be useful.

|  | Graph | Wiki |
|---|---|---|
| Holds | entities | statements about entities |
| Types | `profile` `person` `org` `task` `task_type` `skill` `system` | `decision` `risk` `constraint` `preference` `playbook` `commitment` `note` |
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

**Nothing is written without review.** Capture proposes into `~/brain/inbox/`; you approve
or reject. A memory that is 80% right is worse than none, because it degrades every later
output invisibly and you cannot tell which fifth is wrong.

**Everything expires.** Every node carries `review_by`. A brain where nothing expires rots
quietly until a stale fact embarrasses you — and then you stop trusting all of it.
`keel health` surfaces expiries, contradictions, broken references and unanchored
documents.

## Install

```bash
git clone https://github.com/APareek89/keel.git
mkdir -p ~/.claude/skills/keel
cp -r keel/SKILL.md keel/scripts ~/.claude/skills/keel/
mkdir -p ~/brain/{graph/{people,orgs,tasks,task_types,skills,systems},wiki/{decisions,risks,constraints,preferences,playbooks,commitments,notes},loops,inbox,_templates,_index}
cp -r keel/templates/* ~/brain/_templates/
```

Then run `/keel` in Claude Code. First invocation runs setup.

Using Codex too? Install the same skill there — the Codex MCP config below points at
this copy:

```bash
mkdir -p ~/.codex/skills/keel
cp -r keel/SKILL.md keel/scripts ~/.codex/skills/keel/
```

### Load preferences into every session (optional)

A `SessionStart` hook puts your profile and global preferences into context before you
type anything. A preference scoped to a kind of work — one with an `about:` — stays out
until that work comes up. Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ {
          "type": "command",
          "command": "python3 $HOME/.claude/skills/keel/scripts/session_start.py 2>/dev/null || true",
          "timeout": 5
      } ] }
    ]
  }
}
```

It fails silently and exits 0 if the brain is missing, so a broken hook never blocks a
session. `keel health` warns if it is loading nothing.

### MCP server — one brain, every client

A local stdio MCP server exposes the brain to Claude Desktop, Codex and Cursor.
**No database, no auth, no hosting** — it is a process on your own machine reading
your own markdown. The files are the database.

```json
// Claude Desktop: ~/Library/Application Support/Claude/claude_desktop_config.json
// Cursor:         ~/.cursor/mcp.json
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

Eleven tools:

| Tool | Does |
|---|---|
| `keel_profile` | your profile and global preferences — clients other than Claude Code have no session hook, so the model calls this first |
| `keel_recall` | two-step retrieval for whatever the session touches |
| `keel_remember` | propose a decision, constraint, preference, risk, playbook, note or commitment — or a new person, org, task, task type, skill or system |
| `keel_inbox` `keel_approve` `keel_reject` | review proposals from any client |
| `keel_list_entities` `keel_read` | browse the graph |
| `keel_health` `keel_missing` `keel_todo` | the same reports as the commands below |

In clients that show server instructions, the server tells the model to call
`keel_profile` first. Check it before wiring a client — it only reads your brain,
and runs its write path in a throwaway one:

```bash
python3 scripts/mcp_server.py --selftest
```

This is what makes the brain *shared* rather than copied. Without it each client
holds its own snapshot and they drift; with it, a capture from Claude Desktop
lands in the same inbox as one from Claude Code, and either can approve it.

**claude.ai in a browser is the one surface this does not reach** — a local server
is not reachable from a web page. Upload the brain to a Project for read-only use
there. Remote MCP would fix it and is deliberately not built: hosting other
people's brains means auth, storage and a privacy surface, which is a company
rather than a tool you can `git clone`.

### Codex skill

Codex has no session-start hook, so its always-loaded file *is* the hook:

```bash
python3 ~/.claude/skills/keel/scripts/brain.py export-codex
```

Writes your profile and global preferences into `~/.codex/AGENTS.md` between managed
markers, so anything you wrote in that file survives. Re-run when they change; `health`
flags the export when it goes stale.

## Commands

```bash
python3 ~/.claude/skills/keel/scripts/brain.py health         # fed? true? retrievable?
python3 ~/.claude/skills/keel/scripts/brain.py missing        # structural gaps
python3 ~/.claude/skills/keel/scripts/brain.py todo           # open loops, commitments, live risks
python3 ~/.claude/skills/keel/scripts/brain.py inbox          # proposals waiting for review
python3 ~/.claude/skills/keel/scripts/brain.py approve FILE   # file a proposal into the brain
python3 ~/.claude/skills/keel/scripts/brain.py reject FILE    # delete a proposal
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

Working, and in daily use by its author. Not yet built: a scheduled agent for overnight
capture and the morning brief.

MIT.
