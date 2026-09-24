---
name: keel
description: Keel — a persistent context layer for the user, backed by a markdown knowledge base at ~/brain. Invoked bare ("/keel") it runs first-time setup, wires a new client, or shows a command menu. Use it to load the user's preferences, active decisions, stakeholders and open loops at the start of substantive work so output is aligned without them re-briefing you; to capture new decisions, preferences, people, tasks and commitments mid-conversation; for their morning brief; and to check what the brain is missing or where it has gone stale. Trigger on "orient me", "what do I need to know", "catch me up", "remember this", "what's pending", "morning brief", "start my day", "what am I waiting on", "what did we decide about X", "is the brain ok", "show me the brain" — and also proactively whenever a session involves drafting a document, making or revisiting a decision, running a recurring piece of work, or working with named colleagues, even when the user doesn't mention the brain at all.
---

# Keel

A knowledge base at `~/brain` that survives between sessions. Read from it before
substantive work; write to it when something worth keeping appears.

The failure this prevents: the user re-explaining who they are, how they work, and what
was already decided, at the start of every session. The failure that would be
worse: a brain full of noise that makes output *less* accurate. Guard the second
at least as hard as the first.

Scripts live in this skill's `scripts/` folder — `~/.claude/skills/keel/scripts/`
in Claude Code, `~/.codex/skills/keel/scripts/` in Codex. Commands below use the
Claude Code path.

---

## First invocation — set up, then show the commands

Read `~/brain/_index/setup.json` before anything else. Three cases:

**1. No file, or the brain has fewer than three nodes** → nothing has been set up.
Run [Get Started](#get-started) in full, then print the menu. Do not show the menu
first and make them pick it — they invoked the command, that *is* the request.

**2. File exists but this client is not in its `clients` list** → the brain is
built, but this editor is not wired to it yet. Do the short client setup below,
then print the menu. This is the Codex-after-Claude case, and vice versa.

**3. File exists and this client is listed** → print the menu and stop.

### Client setup (case 2 — takes one step, no questions)

Work out which client you are in — `~/.claude/skills/keel/` means Claude Code,
`~/.codex/skills/keel/` means Codex — and wire only that one:

- **Claude Code**: confirm a `SessionStart` hook exists in `~/.claude/settings.json`
  pointing at `scripts/session_start.py`. If not, offer to add it (one edit), since
  without it nothing loads automatically.
- **Codex**: run `brain.py export-codex`. Codex has no session-start hook, so
  `~/.codex/AGENTS.md` *is* the always-loaded surface.

Then add the client to `setup.json` and say in one line what changed:

```
Keel wired to Codex — your profile and global preferences now load into every
Codex session via AGENTS.md.
```

Then print the menu. Total: one action, no questions.

**Claude Desktop, Cursor and other MCP clients** can't read `~/brain` through
this skill — they reach it through the local MCP server, `scripts/mcp_server.py`
(see [Other clients](#other-clients--the-mcp-server)). When the user asks to
wire one, add the `keel` entry to that client's MCP config — the paths are in
the README — run `mcp_server.py --selftest`, and add `"claude-desktop"` or
`"cursor"` to `clients`. One edit; they restart the client to pick it up.

### The menu

```
Keel — what would you like?

  /keel orient     Load what matters for what you're working on
  /keel brief      Morning brief: pending, owed, waiting, stale
  /keel todo       Open loops and live risks, nothing else
  /keel brain      Visual map of everything it knows
  /keel health     Is it being fed, still true, still retrievable?
  /keel missing    What it should know and doesn't
  /keel review     Approve or reject captured proposals   (N waiting)
  /keel remember   Capture something from this conversation
```

Fill in N from the file count in `~/brain/inbox/`. Print it and stop — no
commentary, and don't recommend which to pick unless asked.

---

## Get Started

**This must not become a conversation.** They typed a command; they did not ask to
start a project. One question, do the work, confirm, hand back control — all in
this turn.

- **Exactly one AskUserQuestion.** A multi-select over the sources you found. Not
  a sequence, not a clarifying follow-up. One.
- **Don't narrate while working.** No "now reading the Codex sessions…". Work, then
  report once at the end.
- **Don't ask what to do with what you find.** Everything becomes an inbox proposal.
  That *is* the review step, and it happens later, when they choose.
- **Never stop midway to ask.** If a source is slow, unparseable or empty, skip it
  and mention it in the closing summary.

**Always end by printing the menu.** Setup that finishes without showing what
can be done next leaves them with a built brain and no idea how to use it. Print
the menu, then exactly this shape of line:

```
Keel is live — 24 proposals waiting. Carry on with your work.
```

Then **stop**. Don't offer next steps, don't ask whether they want to review now,
don't summarise what you learned about them. They'll come back when they want to.

Runs once. The point is to build a brain worth having on day one, from sources they
already have connected — not to leave them with an empty directory.

**Four rules, in order of importance:**

1. **Never glob their document folders.** Not `~/Documents`, not `~/Downloads`, not
   `~/Desktop`, not the working directory. Unbounded discovery — searching for
   anything that looks useful — is what makes this feel invasive, and it's
   unpredictable for them to reason about.
2. **Do check the known AI-tool paths below.** These are a *fixed allowlist*, not
   discovery: the paths are written down here, so what gets touched is auditable and
   can't grow silently. Enumerate first, tell them exactly what you found — path,
   size, file count, date range — then ask before reading a byte. Don't make them go
   and export something the machine already has.
3. **Offer only connectors that are actually connected.** Enumerate with the MCP
   registry tools. An offer they can't accept is noise.
4. **One month of history, not everything.** Enough to be useful, small enough to
   review.

### Local AI sources — the allowlist

Check each; report only what exists. Anything not on this list needs an explicit
request from them.

| Source | Path | What it's good for |
|---|---|---|
| Claude Code sessions | *(no file access — use the session MCP tools)* | **The best source.** `list_sessions` then `list_events` gives real work: decisions, procedures, people. Already structured, no parsing. |
| Claude Code memory | `~/.claude/projects/*/memory/` | Already-distilled markdown. Near-zero processing — import almost directly. |
| Codex sessions | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` | JSONL, `{timestamp, type, payload}` per line. Real transcripts. |
| Claude Desktop | `~/Library/Application Support/Claude/` | Large. Format not verified — report what's there, don't promise it parses. |
| Cursor | `~/Library/Application Support/Cursor/User/globalStorage/` | Mostly editor state; chat history is in an opaque store. Low expected yield — say so. |
| ChatGPT desktop | `~/Library/Application Support/com.openai.chat/` | Pairing config only, no history. Mention it's empty rather than staying silent. |
| Exports they already have | `~/Downloads/*.zip` matching `chatgpt`/`conversations`/`claude*export` | Only these name patterns. Never a general Downloads scan. |

**Read order matters.** Start with Claude Code memory (structured, instant), then
Claude Code sessions (richest signal), then Codex sessions. Stop when the inbox has
enough for one review sitting — a hundred proposals they'll never get through is worse
than twenty they will.

**The flow.** Use AskUserQuestion so they can pick with a click:

- **Local AI data** — one option per source that actually exists, each labelled with
  what was found: *"Claude Code — 21 transcripts, 15 in the last month"*. Never list
  a path that isn't there.
- **Connectors** — one per live connector, with what it contributes: *Slack —
  colleagues, commitments and decisions from the last month*; *Gmail — who you're
  waiting on, what you promised*.
- **Files you upload** — an open field for anything outside both: PRDs, org charts,
  strategy docs.

Multi-select. Nothing is mandatory; skipping every source is a valid answer.

Then process what they chose into `~/brain/inbox/` as proposals, never straight into
the brain. Expect a large first batch; group the review by type so approving is fast.
Aim for breadth over depth on the first pass: a thin `person` node for everyone who
matters beats a rich node for one.

Finally write the setup marker to `~/brain/_index/setup.json`, so the menu stops
offering this:

```json
{
  "completed": "YYYY-MM-DD",
  "sources": ["slack", "uploads"],
  "clients": ["claude-code"],
  "version": 4
}
```

`clients` is what stops a fresh install in the other editor from either
re-running the whole setup or silently doing nothing. Add `"codex"` when Codex is
wired, `"claude-code"` when Claude Code is, `"claude-desktop"` or `"cursor"` when
their MCP entry is added. Then show them the menu.

---

## The daily connector check

Once a day, on the first session, see whether anything new has been connected:

```bash
python3 ~/.claude/skills/keel/scripts/brain.py connectors --seen slack,gmail,calendar
```

Pass the connectors you actually found. The script returns only genuinely new ones,
so they are never asked twice about the same thing. If `new` is non-empty, offer once —
*"Gmail is connected now. Want me to pull the last month to enrich the brain?"* —
and record the answer either way:

```bash
python3 ~/.claude/skills/keel/scripts/brain.py connectors --seen gmail --record
```

Ask once and record. A prompt that reappears every morning gets the whole skill
switched off.

---

## Orient

Loading the whole brain defeats the point — it wastes context and drowns the signal.

The SessionStart hook has **already loaded** `profile.md` and the global
preferences — those with no `about:`. Don't re-read them. Your job is the
selective part, scoped preferences included:

**Step 1 — anchor in the graph.** Which entities does this session touch? A task or
project, a person, a task type, the repo in the cwd. Search entities only — it's a
small set:

```bash
rg -l -i "<anchor>" ~/brain/graph
```

Read those, follow their `edges:` one hop to directly related entities. One hop is
strong, two is weak, three is noise.

**Step 2 — pull the wiki for those entities.** Documents name what they're about,
so find them by reference:

```bash
rg -l "entity: <entity-id>" ~/brain/wiki
```

Rank what you read: **constraints and scoped preferences first** (standing rules
violated silently are expensive), then decisions, then risks and playbooks, then
the rest. Recency breaks ties.

**If a `task_type` is among the anchors, that's the jackpot** — its documents are
the playbook, the scoped preferences and the constraints for that kind of work,
all in one pull. That is the whole reason the type layer exists.

Skip `status: superseded` and `archived` unless they're asking about history. When
there's no obvious anchor, fall back to full-text search across `~/brain/wiki`.

Budget 2–4k tokens. Over budget, drop whole documents by rank — never truncate one,
since a half-read constraint is worse than an unread one.

Then say in two or three lines what you loaded and why. They need to be able to spot
the brain feeding you something wrong, and they can't if retrieval is invisible.

If nothing relevant exists, say so plainly rather than padding with tangential files.

---

## Capture (`remember`)

**Nothing is written straight into the brain.** Proposals go to `~/brain/inbox/`
as `YYYY-MM-DD-<slug>.md` and wait for review.

A memory that is 80% right is worse than none: it degrades every future output
invisibly and they have no way to tell which fifth is wrong. The review gate is the
only thing between a useful brain and a poisoned one. Don't bypass it, even when
the fact seems obviously correct.

**The test for keeping something: will it change what I do in a future session?**

**Then decide which layer.** Is it a thing with identity (→ `graph/`, gets `edges:`)
or a statement about one (→ `wiki/`, gets `about:`)? Most captures are documents.
A new entity is a bigger deal than it looks — it's a claim that something is a
first-class part of their world, so create one only when documents need somewhere to
hang from.

Worth capturing — a **decision** with its rejected alternative and reason; a
**preference**, scoped with `applies_to` unless it genuinely is global; a
**constraint**; a **risk** with a review date; a **person** fact; a **commitment**
with a `due` date and a `direction` (`owed` or `waiting-on`); a **task_type** when
a piece of work looks like it will recur; a **playbook** when a procedure is worth
repeating.

Not worth capturing — anything recoverable from the repo or filesystem, session
narration, restatements of tool output, facts with no bearing on future work. When
unsure, drop it. Under-capture is recoverable; over-capture is not.

**Two judgement calls that matter:**

*Feedback that changes how they'll work next time is a preference or constraint in
disguise* — promote it rather than filing it as task history. "Per-credit price must
fall at every tier" started as feedback on a ladder and is now a standing rule.

*A second instance of similar work means a `task_type` is due.* That's the moment the
preferences and playbooks get somewhere permanent to live.

Set `confidence` honestly: `high` if they said it outright, `medium` if inferred from
behaviour, `low` if you're guessing. Low-confidence proposals are still worth making.

---

## Brief

One page, in this order. Skip empty blocks rather than padding them.

1. **Today's shape** — calendar. Per meeting: who's attending, their `person` node,
   open loops with them.
2. **You owe** — commitments with `direction: owed`, plus any rows in
   `loops/owed.md`, by due date. `brain.py todo` lists both and flags anything
   past due.
3. **Waiting on** — commitments with `direction: waiting-on` and
   `loops/waiting-on.md`, plus mail and Slack threads. Compute days elapsed and
   name the silence: *"Asked the reviewer 9 days ago, no reply."* This block is
   why the brief exists.
4. **Blocked on you** — tasks that a document `blocks` (through `about:`) where
   the next move is theirs: a decision they haven't made, an answer they owe.
5. **Inbox triage** — filter connector deltas against the graph. Surface mail from
   people and tasks they own; count the rest rather than listing it.
6. **Needs a look** — run `brain.py health` and report only what it flags.
7. **Approve queue** — the count from `brain.py inbox`.

Every block should retire an item, flag a slip, or ask a one-line question. A brief
that only ever adds to their list gets abandoned within a fortnight.

---

## Review

`brain.py inbox` lists what's waiting. Read each file, show a compact summary —
type, claim, source, confidence — and take their call one at a time. Group by type
when the batch is large.

On approval run `brain.py approve <file>`. It files the node in the right folder,
adds the **reciprocal edge** for `owns`/`owned_by`, fills a missing `review_by`,
and refuses if the id already exists — merge by hand then. On rejection run
`brain.py reject <file>`. If they edit it, write their wording into the inbox file
verbatim first — their phrasing of their own preferences beats yours.

---

## Health, Missing, To-do, Brain

Run the script. It's deterministic, costs no tokens, and checks things that are
tedious to eyeball. Read the output and tell them what matters in a couple of lines —
don't paste it back at them.

```bash
python3 ~/.claude/skills/keel/scripts/brain.py health    # fed? true? retrievable?
python3 ~/.claude/skills/keel/scripts/brain.py missing   # structural gaps
python3 ~/.claude/skills/keel/scripts/brain.py todo      # open loops, live risks
python3 ~/.claude/skills/keel/scripts/brain.py view      # HTML map + graph
```

**Codex.** The same brain works in Codex via `~/.codex/AGENTS.md`, which has their
profile and global preferences inlined — Codex has no session-start hook, so its
always-loaded file *is* the hook. Regenerate whenever the profile or a global
preference changes:

```bash
python3 ~/.claude/skills/keel/scripts/brain.py export-codex
```

It replaces only the block between the `keel:start` / `keel:end`
markers, so anything they wrote in that file survives. `health` flags the export
when it goes stale — a stale export means Codex is silently running on old
preferences, which is worse than none because nothing looks wrong.

**Health** answers four questions, each a way this fails: is it still being fed
(a brain that stopped growing is one they stopped using — the failure that precedes
all others); is it still true; can it be retrieved (orphans matter because Orient
walks the graph, so an unconnected node is invisible); will the brief work.

**Missing** finds structural gaps mechanically — decisions with no rejected
alternative, task types with no playbook, global preferences that probably want
scoping, people with no org. **Layer judgement on top**: scan recent sessions for
people, task types or recurring procedures that never made it into the brain, and
propose them. The script can't see transcripts; you can.

**View** writes `~/brain/_index/brain.html` and opens it. **Never publish it as an
artifact or upload it anywhere** — it maps their private context, including people and
commitments. Regenerate rather than share.

When something is flagged, offer to fix it in the same breath. Broken edges and
missing `review_by` dates you can just fix. Stale nodes need their call: still true,
needs updating, or archive.

---

## Other clients — the MCP server

Claude Desktop, Cursor and anything else that speaks MCP reach the same `~/brain`
through `scripts/mcp_server.py`, a local stdio server. It keeps every rule here:
two-step retrieval, proposals into `inbox/`, nothing filed without approval.

| Tool | Does |
|---|---|
| `keel_profile` | the profile and global preferences — the hook's job, in clients with no hook |
| `keel_recall` | two-step retrieval for whatever the session touches |
| `keel_remember` | propose a document or an entity into `inbox/` |
| `keel_inbox` `keel_approve` `keel_reject` | the review gate |
| `keel_list_entities` `keel_read` | browse the graph |
| `keel_health` `keel_missing` `keel_todo` | the reports above |

Check it with `python3 scripts/mcp_server.py --selftest`. It only reads the real
brain; its write path runs in a throwaway one.

---

## The model — two layers

**This is the heart of the skill.** Memory is a small entity graph plus a growing
wiki, and keeping them apart is what makes both work.

**Graph — things with identity.** People, orgs, tasks and projects, task types,
skills, systems. They persist, they relate to each other, and walking between them
is meaningful. This layer stays small — tens of nodes, not hundreds — which is what
keeps it readable and traversal cheap.

**Wiki — statements about those things.** Decisions, risks, constraints,
preferences, playbooks, commitments, notes. These are prose, they are *read* not
traversed, and they grow without bound. They carry an `about:` reference into the
graph; that reference is their only link to it.

Putting a decision in the graph is the mistake that ruins both layers. Decisions
rarely relate to other decisions in any way worth walking — they are statements
about a project or a task type. Made into nodes, they swamp the graph (22 of 40
nodes here, before the split) and turn a legible map into a hairball, while their
actual content still has to be read to be useful.

| | Graph | Wiki |
|---|---|---|
| Holds | entities | statements about entities |
| Types | `profile` `person` `org` `task` `task_type` `skill` `system` | `decision` `risk` `constraint` `preference` `playbook` `commitment` `note` |
| Links via | `edges:` — entity → entity only | `about:` — document → entity |
| Retrieved by | traversal from an anchor | pulled via `about:`, or searched |
| Grows | slowly, bounded | continuously, unbounded |
| Rendered | yes, in `/keel brain` | no — shown as documents *on* an entity |

A project is just a task with children — each sub-task points at it with
`part_of`. One recursive type, not two.

### Retrieval is two-step

1. **Anchor in the graph.** Which entities does this session touch? Walk one hop
   for directly related entities. Small, cheap, precise.
2. **Pull the wiki.** Read documents whose `about:` names those entities, ranked
   by type (constraint and preference first, then decision, then the rest) and
   recency. Full-text search is the fallback when there is no obvious anchor.

This is why the split matters operationally, not just aesthetically. Before it, a
two-hop walk from a person reached unrelated decisions through shared projects.
Now you get exactly the documents written about the entities actually in play.

### Which layer does it go in?

Ask in order; first yes wins.

1. **Does it have identity — would you say "the X" and mean a specific thing that
   persists?** → **graph entity**
2. **Is it a statement, rule, record or procedure *about* something?** → **wiki
   document**, with `about:` naming what it concerns
3. **Does it only make sense inside its parent and never gets queried alone?** →
   **property** on whichever of the two it belongs to

Relationships between two *entities* are **edges**. Relationships between two
*documents* — supersedes, contradicts, motivated_by — are plain frontmatter
fields, never edges. That distinction alone removed six edges from this brain.

### Frontmatter

An **entity** — only entities carry `edges:`:

```yaml
---
id: task_type-pricing-change
type: task_type
title: Live pricing change
status: active
confidence: high
scope: personal
provenance: session:2026-09-02
created: 2026-09-02
updated: 2026-09-02
review_by: 2027-09-02
edges:
  - type: requires_skill
    to: skill-billing-ops
    primary: true
---
```

A **document** — only documents carry `about:`:

```yaml
---
id: decision-2026-09-02-park-dont-archive
type: decision
title: Retire prices by tag-parking, never by archiving
status: active
confidence: high
review_by: 2027-03-02
about:
  - relation: constrains
    entity: task_type-pricing-change
# doc → doc: a field, not an edge
supersedes: decision-2026-08-archive-retired
---

Prose written for a model to read. This is the part that gets retrieved and
actually used — the graph only helps find it.
```

`review_by` is mandatory on both. A brain where nothing expires rots quietly until
a stale fact embarrasses them, and then they stop trusting all of it.

### Vocabularies

**Entity edges** — `works_at` `reports_to` `member_of` `owns` `owned_by`
`created_by` `part_of` `instance_of` `requires_skill` `sub_skill_of` `depends_on`

**Document relations** (`about:` → `relation:`) — `concerns` `constrains`
`applies_to` `shaped` `blocks` `documents` `instance_of` `evidence_for`
`derived_from`

**Document-to-document fields** — `supersedes` `superseded_by` `contradicts`
`motivated_by` `rejected_in_favour_of`

Direction reads subject → object: `task-q4-campaign --owned_by--> person-self`.
Getting it backwards silently corrupts traversal.

**Preferences are scoped, not global.** A preference with `relation: applies_to`
fires only for that task type. One with no `about:` at all is global — correct for
"give a recommendation, not a survey", and it loads via the hook rather than being
retrieved. Anything with an `about:` stays out of the hook and loads only when
what it's about is in play.

### Layout

```
~/brain/
  graph/                    ← entities. small, bounded, rendered.
    profile.md
    people/  orgs/  tasks/  task_types/  skills/  systems/
  wiki/                     ← documents. prose, unbounded, read.
    decisions/  risks/  constraints/  preferences/  playbooks/  commitments/  notes/
  loops/                    ← optional hand-kept tables: owed.md, waiting-on.md
  inbox/  _templates/  _index/
```

The split is visible in the filesystem on purpose: it forces the question at
capture time rather than letting everything drift into the graph.

Templates are in `_templates/`. Copy one rather than writing frontmatter from memory.

---

## What runs automatically

A SessionStart hook loads `profile.md` and the global preferences into every Claude
Code session — those are already in context before you read this. In other clients
the MCP server's `keel_profile` does the same job when the model calls it.
Everything else runs when invoked.

Not yet built: a **scheduled agent** for the nightly capture pass and the morning
brief. Say so plainly if they ask — don't imply more automation than exists.
