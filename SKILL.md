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
Keel wired to Codex — your profile and preferences now load into every Codex
session via AGENTS.md.
```

Then print the menu. Total: one action, no questions.

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
  That *is* the review step, and it happens later, when they chooses.
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
already has connected — not to leave them with an empty directory.

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
| Exports they already has | `~/Downloads/*.zip` matching `chatgpt`/`conversations`/`claude*export` | Only these name patterns. Never a general Downloads scan. |

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

Finally write the setup marker so the menu stops offering this:

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
wired, `"claude-code"` when Claude Code is.

to `~/brain/_index/setup.json`, then show them the menu.

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

The SessionStart hook has **already loaded** `profile.md` and everything in
`preferences/`. Don't re-read them. Your job is the selective part:

**Step 1 — anchor in the graph.** Which entities does this session touch? A project,
a person, a task type, the repo in the cwd. Search entities only — it's a small set:

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

Skip `status: superseded` and `archived` unless they's asking about history. When
there's no obvious anchor, fall back to full-text search across `~/brain/wiki`.

Budget 2–4k tokens. Over budget, drop whole documents by rank — never truncate one,
since a half-read constraint is worse than an unread one.

Then say in two or three lines what you loaded and why. They needs to be able to spot
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
with a date; a **task_type** when a piece of work looks like it will recur; a
**playbook** when a procedure is worth repeating.

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
2. **You owe** — `loops/owed.md`, by due date. Flag anything past due.
3. **Waiting on** — `loops/waiting-on.md` plus mail and Slack threads. Compute days
   elapsed and name the silence: *"Asked the reviewer 9 days ago, no reply."* This block is
   why the brief exists.
4. **Blocked on you** — projects with a `blocked_by` edge on a decision they haven't made.
5. **Inbox triage** — filter connector deltas against the graph. Surface mail from
   people and projects they owns; count the rest rather than listing it.
6. **Needs a look** — run `brain.py health` and report only what it flags.
7. **Approve queue** — count in `~/brain/inbox/`.

Every block should retire an item, flag a slip, or ask a one-line question. A brief
that only ever adds to their list gets abandoned within a fortnight.

---

## Review

Read each file in `~/brain/inbox/`. Show a compact summary — type, claim, source,
confidence — and take their call one at a time. Group by type when the batch is large.

On approval: move the file to the right directory and **add the reciprocal edge** to
anything it points at. On rejection: delete it. If they edits it, keep their wording
verbatim — their phrasing of their own preferences beats yours.

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
profile and preferences inlined — Codex has no session-start hook, so its
always-loaded file *is* the hook. Regenerate whenever profile or preferences change:

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

## The model — two layers

**This is the heart of the skill.** Memory is a small entity graph plus a growing
wiki, and keeping them apart is what makes both work.

**Graph — things with identity.** People, orgs, projects, task types, skills,
systems. They persist, they relate to each other, and walking between them is
meaningful. This layer stays small — tens of nodes, not hundreds — which is what
keeps it readable and traversal cheap.

**Wiki — statements about those things.** Decisions, risks, constraints,
preferences, playbooks, task records, notes. These are prose, they are *read* not
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
| Types | `profile` `person` `org` `project` `task_type` `skill` `system` | `decision` `risk` `constraint` `preference` `playbook` `task` `note` |
| Links via | `edges:` — entity → entity only | `about:` — document → entity |
| Retrieved by | traversal from an anchor | pulled via `about:`, or searched |
| Grows | slowly, bounded | continuously, unbounded |
| Rendered | yes, in `/keel brain` | no — shown as documents *on* an entity |

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
supersedes: decision-2026-08-archive-retired    # doc → doc, a field not an edge
---

Prose written for a model to read. This is the part that gets retrieved and
actually used — the graph only helps find it.
```

`review_by` is mandatory on both. A brain where nothing expires rots quietly until
a stale fact embarrasses them, and then they stops trusting all of it.

### Vocabularies

**Entity edges** — `works_at` `reports_to` `member_of` `owns` `owned_by`
`part_of` `instance_of` `requires_skill` `sub_skill_of` `depends_on`

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
retrieved.

### Layout

```
~/brain/
  graph/                    ← entities. small, bounded, rendered.
    profile.md
    people/  orgs/  projects/  task_types/  skills/  systems/
  wiki/                     ← documents. prose, unbounded, read.
    decisions/  risks/  constraints/  preferences/  playbooks/  tasks/  notes/
  loops/                    ← structured state: owed.md, waiting-on.md
  inbox/  _templates/  _index/
```

The split is visible in the filesystem on purpose: it forces the question at
capture time rather than letting everything drift into the graph.

Templates are in `_templates/`. Copy one rather than writing frontmatter from memory.

---

## What runs automatically

Three pieces, all deterministic — no model, no tokens. Install them once:

1. **SessionStart hook** → `autobrain.py session-start`. Loads `profile.md`,
   everything in `preferences/`, and a **live-topics block** measured from the
   user's own Claude Code and Codex transcripts. Emits the hook JSON envelope,
   reads a 12h cache, costs ~80ms. A node whose topic shows activity newer than
   its `updated:` is marked stale there — when you are about to rely on one, ask
   first. (`scripts/session_start.py` is a shim onto the same code.)
2. **Nightly pass** — `scripts/nightly.sh`, run by cron or a launchd agent.
   Runs `promote --apply`, `export-codex`, `view`. Logs to
   `~/brain/_index/nightly.log`.
3. **Codex** gets the same context through the `keel:start`/`keel:end` block in
   `~/.codex/AGENTS.md`, rewritten nightly. Text outside the markers is preserved.

### State, not approval

**Nothing is deleted and nothing waits for a human queue.** Everything enters the
brain immediately and carries keywords saying how much weight to give it. A review
gate nobody walks through is not a safety mechanism — it is a queue that rots,
while the graph stays frozen on install day.

Two **independent** axes, because a thing can be recent but unproven, or old but
certain, and those need different answers. Conflating them is what makes lifecycle
models unusable.

**Relevance** — recency of activity on its topic, measured from transcripts:

| band | when | directive |
|---|---|---|
| `current` | activity ≤14d | `use` |
| `fading` | 15–60d | `confirm` |
| `dormant` | >60d | `ignore` (retained, never deleted) |
| `standing` | identity and global preferences | `use` |
| `paused` / `archived` | set explicitly | `confirm` / `ignore` |

**Evidence** — strength of the claim:

| band | when | directive |
|---|---|---|
| `stated` | the user said it outright | `use` |
| `observed` | ≥3 independent captures | `use` |
| `inferred` | 1–2 captures, or auto-written | `cite` |
| `contradicted` | newer activity than the content | `verify` |
| `superseded` | explicitly replaced | `ignore` |

**The stricter directive wins.** Five keywords a session acts on:

```
use     — apply it; no need to mention it
cite    — apply it, but say it is unconfirmed
confirm — ASK before relying on it; the work may have moved on
verify  — content may be false; newer activity contradicts it
ignore  — do not load unless asked; retained, never deleted
```

The legend ships in the SessionStart block, and entities needing confirmation are
listed there by name, so a session does not have to open files to discover it must
ask. Run `autobrain.py state --apply`; the nightly pass does it for you.

**Three rules keep this honest:**
1. **Identity does not decay.** People, orgs, skills, the profile and global
   preferences are `standing` — a colleague's role is not made uncertain by a quiet
   fortnight. Only work state decays.
2. **Only a topic's own node can be contradicted** by activity on it. A person who
   merely mentions a project is not invalidated by work on that project. Skipping
   this flags two-thirds of the brain as suspect.
3. **An explicit judgement outranks a day count.** `status: paused` means paused
   whether it went quiet yesterday or last month.

### The promotion rule

Repetition **and** time must both clear for a *new node*, because either alone is a
bad signal: one long session is a detour, and ten passing mentions are noise.

| promotes | when |
|---|---|
| a new `task` node | ≥3 sessions **and** ≥3 distinct days **and** ≥2h active, with no node |
| a staleness flag | topic activity is newer than the node's `updated:` |

Anything auto-written carries `auto: true` and lands as `inferred`/`cite`, so it can
be audited or reverted with one grep.

### `autobrain.py`

```bash
python3 scripts/autobrain.py scan       # what was worked on vs what the brain knows
python3 scripts/autobrain.py promote    # dry run; --apply to write
python3 scripts/autobrain.py digest     # unclaimed sessions, to name new topics
python3 scripts/autobrain.py state       # recompute directives; --apply to write
python3 scripts/autobrain.py absorb      # dissolve inbox/ into the brain; --apply
python3 scripts/autobrain.py export-codex
```

**The division of labour matters.** The script counts — deterministic, exact,
free. It never writes prose, because no amount of pattern-matching can tell that
"employment ends 10 September" stopped being true. It flags the node; a session
rewrites it, moving superseded text into a dated `<details>` block rather than
deleting it.

### Two things that will bite

**The lexicon is where matching lives or dies.** `~/brain/_index/lexicon.json`
maps topics to the phrases the user actually types — they say "cover letter",
never "job search". Without it, matching silently under-reports. It is also where
matching goes *wrong*: one generic word there merges unrelated topics into
identical hour counts, which looks like working data and is not. A single shared
tag once fused three separate projects this way. The opposite failure is just as
easy: two topics sharing a common word ("notebook") caused the nightly pass to
auto-create a second node for work that already had one. **Before adding a topic,
check whether an existing one already covers it, and pin it with `entity_map`
rather than letting it spawn a duplicate.** Keep phrases distinctive; run `digest`
to find work no topic claims yet. See `examples/lexicon.example.json`.

**Transcripts are not user speech.** A `type:user` record contains injected skill
text, pastes, command output and tool results. Counting those produces confident
nonsense — topics like "script" and "review" with a hundred sessions each.
`is_human()` filters them; don't remove it.

**Still not built:** a graph index in the MCP server so retrieval is instant and
the same brain works from Cursor. Say so plainly if asked — don't imply more
automation than exists.
