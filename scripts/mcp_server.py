#!/usr/bin/env python3
"""
Keel MCP server — local, stdio, no dependencies.

Exposes the brain at ~/brain to any MCP client (Claude Desktop, Codex, Cursor)
as a set of tools. There is no database and no auth because nothing is hosted:
this is a process on your own machine reading your own markdown files.

    python3 mcp_server.py            # speaks JSON-RPC on stdin/stdout
    python3 mcp_server.py --selftest # drives itself and prints a report

Anything written to stdout that is not protocol will break the client, so all
diagnostics go to stderr.
"""

import sys
import json
import pathlib
import tempfile
import traceback
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brain  # noqa: E402  — parsing, so the format has one definition

FALLBACK_PROTOCOL = "2025-06-18"

# what a document is worth when the context budget runs out
DOC_RANK = {"constraint": 0, "preference": 1, "decision": 2, "risk": 3,
            "playbook": 4, "note": 5, "commitment": 6}

# clients that support server instructions show these to the model up front
INSTRUCTIONS = (
    "Keel holds the user's persistent context: who they are, how they work, what "
    "was decided and why. At the start of a conversation call keel_profile and "
    "treat what it returns as how the user wants to be worked with. Before "
    "substantive work — drafting, deciding, recurring work, anything involving "
    "named colleagues — call keel_recall. Capture what is worth keeping with "
    "keel_remember; nothing enters the brain until the user approves it through "
    "keel_inbox and keel_approve.")


def log(msg):
    print(f"[keel] {msg}", file=sys.stderr, flush=True)


def tokens(text):
    return {w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split()
            if len(w) > 2}


def one_line(text):
    """Frontmatter values are single lines — a newline would end one early."""
    return " ".join(str(text).split())


def recency(d):
    day = brain.as_date(d.get("updated")) or brain.as_date(d.get("created"))
    return day.toordinal() if day else 0


# ---------------------------------------------------------------- retrieval

def retrieve(query, budget=6000):
    """Two-step: anchor on entities, then pull only what is written about them."""
    nodes = brain.load_nodes()
    if not nodes:
        return f"No brain found at {brain.BRAIN}."
    ents = [n for n in nodes if brain.is_entity(n)]
    docs = [n for n in nodes if not brain.is_entity(n)
            and n.get("status") not in brain.INACTIVE]
    by_id = {n["id"]: n for n in nodes}
    q = tokens(query)

    # An org or the profile connects to everything, so matching one drags the
    # whole brain in. Hubs are poor anchors and poor hops — a pricing question
    # should never surface someone's career situation via their employer.
    HUB = {"org", "profile"}

    # step 1 — score entities, requiring a real match rather than one stray word
    scored = []
    for e in ents:
        title_id = (e.get("title", "") + " " + e.get("id", "")).lower()
        strong = any(w in title_id for w in q if len(w) > 3)
        hay = tokens(" ".join([e.get("id", ""), e.get("title", ""),
                               " ".join(e.get("tags", []) or []), e["_body"][:600]]))
        overlap = len(q & hay)
        if e.get("type") == "task_type":
            overlap *= 2          # a matching kind of work is the richest anchor
        if e.get("type") in HUB:
            overlap = 0 if not strong else 1   # only if named outright
        if overlap >= 2 or strong:
            scored.append((overlap + (3 if strong else 0), e))
    scored.sort(key=lambda x: -x[0])
    anchors = [e for _, e in scored[:4]]

    # step 2 — one hop out, never through a hub
    focus = {e["id"] for e in anchors}
    anchor_ids = {a["id"] for a in anchors}
    for e in anchors:
        if e.get("type") in HUB:
            continue
        for edge in e.get("edges", []):
            tgt = by_id.get(edge.get("to"))
            if tgt and tgt.get("type") not in HUB:
                focus.add(tgt["id"])
    for e in ents:                                   # inbound edges too
        if e.get("type") in HUB:
            continue
        for edge in e.get("edges", []):
            if edge.get("to") in anchor_ids:
                focus.add(e["id"])

    # step 3 — documents about those entities
    out = []
    if anchors:
        out.append("## Anchored on\n" + "\n".join(
            f"- **{e.get('title', e['id'])}** ({e.get('type')}) — {e['_body'].splitlines()[0][:110] if e['_body'] else ''}"
            for e in anchors))
        picked = []
        for d in docs:
            hits = [a for a in d.get("about", []) if a.get("entity") in focus]
            if hits:
                picked.append((DOC_RANK.get(d.get("type"), 9), d, hits[0].get("relation", "about")))
        limit = 7
    else:
        out.append(f"No entity in the graph matched \"{query}\". "
                   f"Falling back to whatever the wiki has on it.")
        picked = [(DOC_RANK.get(d.get("type"), 9), d, "about") for d in docs
                  if q & tokens(d.get("title", "") + " " + d["_body"][:800])]
        limit = 6

    # best first: by type, then newest first within a type — so the cut below
    # drops the stalest documents, never the latest
    picked.sort(key=lambda x: (x[0], -recency(x[1])))
    picked = picked[:limit]    # precision over recall — four right beats forty plausible

    if not picked:
        out.append("\nNothing is written about these yet.")
        return "\n".join(out)

    out.append("\n## What is written about them")
    used, left_out = 0, []
    for _, d, rel in picked:
        body = d["_body"]
        # whole documents or none: a half-read constraint is worse than an unread one
        if used and used + len(body) > budget:
            left_out.append(d)
            continue
        stale = " ⚠ past review date" if (
            (rv := brain.as_date(d.get("review_by"))) and rv < brain.TODAY) else ""
        out.append(f"\n### {d.get('type', '?').upper()} · {d.get('title', d['id'])}"
                   f"{stale}\n*{rel} · {d.get('confidence', '?')} confidence · "
                   f"{d.get('_path')}*\n\n{body}")
        used += len(body)
    if left_out:
        out.append("\n_Over the budget, so not loaded — read any of these in full with keel_read:_")
        out += [f"- `{d['id']}` — {d.get('type')}: {d.get('title', d['id'])}" for d in left_out]
    return "\n".join(out)


def profile():
    """The profile and global preferences — what the SessionStart hook loads in
    Claude Code. Other clients have no hook, so the model calls this instead."""
    loaded, skipped = brain.standing_context()
    if not loaded:
        return (f"No profile or global preferences in {brain.BRAIN} yet. Nothing "
                "standing to load — use keel_recall for anything specific.")
    out = ["The user's profile and standing preferences, from their brain. Treat "
           "these as how they want to be worked with, not as background reading. "
           "Preferences scoped to one kind of work come back from keel_recall when "
           "that work is in play."]
    out += [f"\n<!-- {rel} -->\n{text}" for rel, text in loaded]
    if skipped:
        ids = {n["_path"]: n["id"] for n in brain.load_nodes()}
        out.append("\n_Over the size budget, not loaded — read with keel_read if needed: "
                   + ", ".join(f"`{ids.get(rel, rel)}`" for rel in skipped) + "_")
    return "\n".join(out)


def list_entities(kind=None):
    nodes = brain.load_nodes()
    ents = [n for n in nodes if brain.is_entity(n) and (not kind or n.get("type") == kind)]
    if not ents:
        return "No entities." if not kind else f"No entities of type {kind}."
    count = {}
    for d in nodes:
        if brain.is_entity(d):
            continue
        for a in d.get("about", []):
            count[a.get("entity")] = count.get(a.get("entity"), 0) + 1
    rows = sorted(ents, key=lambda n: (n.get("type", ""), n.get("title", "")))
    return "\n".join(f"- `{n['id']}` — {n.get('title')} ({n.get('type')}"
                     f"{', ' + str(count[n['id']]) + ' docs' if count.get(n['id']) else ''})"
                     for n in rows)


def read_node(node_id):
    for n in brain.load_nodes():
        if n["id"] == node_id:
            meta = {k: v for k, v in n.items() if not k.startswith("_")}
            return f"# {n.get('title', node_id)}\n\n```yaml\n" + \
                   json.dumps(meta, indent=2, default=str) + f"\n```\n\n{n['_body']}"
    return f"No node with id `{node_id}`."


# ---------------------------------------------------------------- capture + review

def remember(kind, title, content, about=None, edges=None, confidence="medium",
             review_by=None, due=None, direction=None, counterparty=None):
    """Write a proposal to inbox/. Never straight into the brain — the review gate
    is the only thing between a useful brain and a poisoned one."""
    today = brain.TODAY
    if kind not in brain.FOLDER:
        raise ValueError(f"kind must be one of: {', '.join(sorted(brain.FOLDER))}")
    if confidence not in ("high", "medium", "low"):
        raise ValueError("confidence must be high, medium or low")
    title = one_line(title)
    if not title:
        raise ValueError("title is empty")
    if review_by:
        review = brain.as_date(review_by)
        if not review:
            raise ValueError("review_by must be a date, YYYY-MM-DD")
    else:
        review = brain.add_months(today, 6)
    about = [a for a in (about or []) if isinstance(a, dict)]
    edges = [e for e in (edges or []) if isinstance(e, dict)]

    slug = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")[:60]
    slug = "-".join(p for p in slug.split("-") if p) or "untitled"
    inbox = brain.BRAIN / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    stem, nid, k = f"{today}-{kind}-{slug}", f"{kind}-{slug}", 2
    path = inbox / f"{stem}.md"
    while path.exists():                  # never overwrite a proposal still waiting
        path, nid, k = inbox / f"{stem}-{k}.md", f"{kind}-{slug}-{k}", k + 1

    fm = [f"id: {nid}", f"type: {kind}", f"title: {title}",
          "status: active", f"confidence: {confidence}", "scope: personal",
          "provenance: mcp:session", f"created: {today}", f"updated: {today}",
          f"review_by: {review}"]
    notes = []

    # anything already in the graph, or waiting in the inbox to join it
    known = {n["id"] for n in brain.load_nodes() if brain.is_entity(n)}
    pending = {m.get("id") for _, m, _ in brain.inbox_items()
               if m.get("type") in brain.ENTITY_TYPES}

    if kind == "commitment":
        way = direction or "owed"
        if way not in ("owed", "waiting-on"):
            raise ValueError("direction must be owed or waiting-on")
        fm.append(f"direction: {way}")
        if counterparty:
            fm.append(f"counterparty: {one_line(counterparty)}")
        if due:
            when = brain.as_date(due)
            if not when:
                raise ValueError("due must be a date, YYYY-MM-DD")
            fm.append(f"due: {when}")
        else:
            notes.append("⚠ no due date — the brief can't flag it when it slips.")
        # anchor it to the counterparty, so it surfaces whenever they are in play
        who = one_line(counterparty or "")
        if who in known | pending and not any(a.get("entity") == who for a in about):
            about.append({"relation": "concerns", "entity": who})
    elif due or direction or counterparty:
        notes.append("⚠ due, direction and counterparty only apply to commitments — ignored.")

    if kind in brain.ENTITY_TYPES:
        if about:
            notes.append("⚠ entities link through edges, not about — about ignored.")
        links = [e for e in edges if e.get("to") in known | pending and e.get("type")]
        if links:
            fm.append("edges:")
            for e in links:
                fm += [f"  - type: {one_line(e['type'])}", f"    to: {e['to']}"]
        dropped = [str(e.get("to")) for e in edges if e not in links]
        if not links:
            notes.append("⚠ no edges — an entity nothing connects to is rarely surfaced.")
    else:
        if edges:
            notes.append("⚠ documents link through about, not edges — edges ignored.")
        links = [a for a in about if a.get("entity") in known | pending]
        if links:
            fm.append("about:")
            for a in links:
                fm += [f"  - relation: {one_line(a.get('relation') or 'concerns')}",
                       f"    entity: {a['entity']}"]
        dropped = [str(a.get("entity")) for a in about if a not in links]
        if not links:
            notes.append("⚠ no about — this preference would load into every session. "
                         "Anchor it unless it truly applies everywhere."
                         if kind == "preference" else
                         "⚠ no graph anchor — this will be findable by search only.")
    if dropped:
        notes.append(f"⚠ dropped unknown entities: {', '.join(dropped)}")
    waiting = [x for x in (link.get("to") or link.get("entity") for link in links) if x in pending]
    if waiting:
        notes.append(f"⚠ {', '.join(waiting)} still waiting in the inbox — approve it first.")

    path.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + str(content).strip() + "\n",
                    encoding="utf-8")
    msg = (f"Proposed → {path.relative_to(brain.BRAIN)}\n"
           f"Not in the brain until the user approves it (keel_inbox, then keel_approve).")
    return msg + "".join(f"\n{n}" for n in notes)


def inbox():
    items = brain.inbox_items()
    if not items:
        return "Inbox empty — nothing waiting for review."
    out = [f"{len(items)} proposal(s) waiting. Show the user a compact summary — type, "
           "claim, source, confidence — and take their call on each: keel_approve "
           "(with their wording as content if they edit it) or keel_reject."]
    for kind in sorted({m.get("type") or "?" for _, m, _ in items}):
        group = [(p, m, b) for p, m, b in items if (m.get("type") or "?") == kind]
        out.append(f"\n## {kind} ({len(group)})")
        for p, m, body in group:
            links = [f"{a.get('relation', 'about')} {a['entity']}" for a in m.get("about", [])] + \
                    [f"{e.get('type')} {e['to']}" for e in m.get("edges", [])]
            out.append(f"\n### `{p.name}`\n**{m.get('title') or '(untitled)'}** · "
                       f"{m.get('confidence') or '?'} confidence · "
                       f"{m.get('provenance') or 'no source'}\n"
                       f"Links: {', '.join(links) if links else 'none'}\n\n{body}")
    return "\n".join(out)


def run_report(fn):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue() or "(no output)"


# ---------------------------------------------------------------- tools

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
WRITES = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}

TOOLS = [
    {"name": "keel_profile",
     "description": "Load who the user is and their standing preferences — how they want to be "
                    "worked with. Call once at the start of every conversation, before anything "
                    "else, and follow what it returns.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": READ_ONLY},
    {"name": "keel_recall",
     "description": "Retrieve relevant context from the user's brain: preferences, decisions, "
                    "constraints, risks and playbooks about whatever this session touches. Call "
                    "this BEFORE substantive work — drafting a document, making a decision, "
                    "running a recurring piece of work, or anything involving named colleagues.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "What the session is about — a project, "
                                                    "person, kind of work, or topic."},
         "budget": {"type": "integer", "description": "Max characters of document text (default "
                                                     "6000). Documents are never cut: those over "
                                                     "the budget are listed for keel_read."}},
         "required": ["query"]},
     "annotations": READ_ONLY},
    {"name": "keel_remember",
     "description": "Propose something worth keeping for the review inbox. Documents: a decision "
                    "with its rejected alternative, a constraint, a scoped preference, a risk with "
                    "a review date, a playbook, a note, a commitment with a due date. Entities: a "
                    "new person, org, task, task type, skill or system. Never writes into the "
                    "brain directly — the user approves first.",
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": sorted(brain.FOLDER)},
         "title": {"type": "string"},
         "content": {"type": "string", "description": "Markdown body. For a decision, always "
                                                      "include what was rejected and why."},
         "about": {"type": "array",
                   "description": "Documents only: the entities it is about. Ids come from "
                                  "keel_list_entities. A preference with no about loads into "
                                  "every session.",
                   "items": {"type": "object", "properties": {
                       "relation": {"type": "string", "description": "concerns, constrains, "
                                    "applies_to, shaped, blocks, documents, instance_of, "
                                    "evidence_for or derived_from"},
                       "entity": {"type": "string"}},
                       "required": ["entity"]}},
         "edges": {"type": "array",
                   "description": "Entities only: links to other entities.",
                   "items": {"type": "object", "properties": {
                       "type": {"type": "string", "description": "works_at, reports_to, "
                                "member_of, owns, owned_by, created_by, part_of, instance_of, "
                                "requires_skill, sub_skill_of or depends_on"},
                       "to": {"type": "string"}},
                       "required": ["type", "to"]}},
         "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
         "review_by": {"type": "string", "description": "YYYY-MM-DD — when this should be "
                                                        "re-checked. Default: six months out."},
         "due": {"type": "string", "description": "Commitments only: YYYY-MM-DD."},
         "direction": {"type": "string", "enum": ["owed", "waiting-on"],
                       "description": "Commitments only: owed = the user promised it; "
                                      "waiting-on = someone owes the user."},
         "counterparty": {"type": "string", "description": "Commitments only: who it is owed "
                                                           "to or by — an entity id if they are "
                                                           "in the graph."}},
         "required": ["kind", "title", "content"]},
     "annotations": WRITES},
    {"name": "keel_list_entities",
     "description": "List entities in the graph — people, orgs, tasks, kinds of work, skills — "
                    "with their ids. Use before keel_remember to anchor a document correctly.",
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "description": "Optional filter, e.g. person or task_type."}}},
     "annotations": READ_ONLY},
    {"name": "keel_read",
     "description": "Read one node in full by its id.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                     "required": ["id"]},
     "annotations": READ_ONLY},
    {"name": "keel_inbox",
     "description": "List the proposals waiting for review, in full, grouped by type. Use when "
                    "the user wants to review what was captured.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": READ_ONLY},
    {"name": "keel_approve",
     "description": "Approve one proposal on the user's say-so: files it from the inbox into the "
                    "brain and adds the reciprocal half of owns/owned_by edges. If the user "
                    "reworded it, pass their wording as content — it replaces the body verbatim.",
     "inputSchema": {"type": "object", "properties": {
         "file": {"type": "string", "description": "The proposal's file name, from keel_inbox."},
         "content": {"type": "string", "description": "Optional: the user's edited wording."}},
         "required": ["file"]},
     "annotations": WRITES},
    {"name": "keel_reject",
     "description": "Reject one proposal on the user's say-so: deletes it from the inbox.",
     "inputSchema": {"type": "object", "properties": {
         "file": {"type": "string", "description": "The proposal's file name, from keel_inbox."}},
         "required": ["file"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}},
    {"name": "keel_health",
     "description": "Is the brain still being fed, still true, still retrievable? Reports "
                    "staleness, broken references, unanchored documents and capture rate.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": READ_ONLY},
    {"name": "keel_missing",
     "description": "Structural gaps: decisions with no rejected alternative, kinds of work with "
                    "no playbook, global preferences that probably want scoping, people with no org.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": READ_ONLY},
    {"name": "keel_todo",
     "description": "Open loops and live risks — what the user owes, what they are waiting on "
                    "and for how long, open tasks, and risks past their review date.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": READ_ONLY},
]


def call_tool(name, args):
    # a server lives for days inside a desktop client — "today" is read per call
    brain.TODAY = date.today()
    if name == "keel_profile":
        return profile()
    if name == "keel_recall":
        return retrieve(args["query"], int(args.get("budget") or 6000))
    if name == "keel_remember":
        return remember(args["kind"], args["title"], args["content"],
                        about=args.get("about"), edges=args.get("edges"),
                        confidence=args.get("confidence") or "medium",
                        review_by=args.get("review_by"), due=args.get("due"),
                        direction=args.get("direction"), counterparty=args.get("counterparty"))
    if name == "keel_list_entities":
        return list_entities(args.get("kind"))
    if name == "keel_read":
        return read_node(args["id"])
    if name == "keel_inbox":
        return inbox()
    if name == "keel_approve":
        return brain.approve(args["file"], args.get("content"))
    if name == "keel_reject":
        return brain.reject(args["file"])
    if name == "keel_health":
        return run_report(brain.cmd_health)
    if name == "keel_missing":
        return run_report(brain.cmd_missing)
    if name == "keel_todo":
        return run_report(brain.cmd_todo)
    raise ValueError(f"unknown tool: {name}")


# ---------------------------------------------------------------- protocol

def reply(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def error(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def handle(msg):
    """Returns a response dict, or None for notifications."""
    if not isinstance(msg, dict):
        return error(None, -32600, "invalid request: expected a JSON object")
    method, mid = msg.get("method"), msg.get("id")

    if method == "initialize":
        client = (msg.get("params") or {}).get("protocolVersion")
        return reply(mid, {
            "protocolVersion": client or FALLBACK_PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "keel", "version": "1.1.0"},
            "instructions": INSTRUCTIONS})

    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return reply(mid, {})

    if method == "tools/list":
        return reply(mid, {"tools": TOOLS})

    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            text = call_tool(p.get("name"), p.get("arguments") or {})
            return reply(mid, {"content": [{"type": "text", "text": text}]})
        except ValueError as e:              # a bad argument — said plainly, no traceback
            log(f"tool error: {e}")
            return reply(mid, {"content": [{"type": "text", "text": f"Error: {e}"}],
                               "isError": True})
        except Exception as e:
            log(f"tool error: {traceback.format_exc()}")
            return reply(mid, {"content": [{"type": "text", "text": f"Error: {e}"}],
                               "isError": True})

    if mid is None:
        return None
    return error(mid, -32601, f"method not found: {method}")


def safe_handle(msg):
    """handle(), but an exception becomes an error response, never a dead server."""
    try:
        return handle(msg)
    except Exception:
        log(traceback.format_exc())
        return error(msg.get("id") if isinstance(msg, dict) else None, -32603, "internal error")


def handle_line(line):
    """One line of input to the line to write back, or None if there is nothing
    to say. A batch array (protocol 2025-03-26) gets an array back."""
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        log("skipped non-JSON line")
        return None
    if isinstance(msg, list):
        if not msg:
            return json.dumps(error(None, -32600, "invalid request: empty batch"))
        out = [r for r in (safe_handle(m) for m in msg) if r is not None]
        return json.dumps(out) if out else None
    resp = safe_handle(msg)
    return json.dumps(resp) if resp is not None else None


def serve():
    for stream in (sys.stdin, sys.stdout):    # MCP is UTF-8 whatever the locale says
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    log(f"brain at {brain.BRAIN} — {len(brain.load_nodes())} nodes")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        out = handle_line(line)
        if out is not None:
            sys.stdout.write(out + "\n")
            sys.stdout.flush()


# ---------------------------------------------------------------- selftest

def selftest():
    ok = True

    def check(label, passed, detail=""):
        nonlocal ok
        ok &= bool(passed)
        print(f"{label:<20}→ {'ok  ' if passed else 'FAIL'} {detail}")

    def call(tool, args=None):
        r = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": tool, "arguments": args or {}}})
        return r["result"]["content"][0]["text"], bool(r["result"].get("isError"))

    print("protocol:")
    r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"}})
    check("initialize", r["result"]["serverInfo"]["name"] == "keel"
          and r["result"].get("instructions"), f"proto {r['result']['protocolVersion']}")
    names = [t["name"] for t in handle({"jsonrpc": "2.0", "id": 2,
                                        "method": "tools/list"})["result"]["tools"]]
    check("tools/list", len(names) == len(set(names)) == 11, f"{len(names)}: {', '.join(names)}")
    check("notification", handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None)
    check("unknown method", handle({"jsonrpc": "2.0", "id": 4,
                                    "method": "nope/nope"})["error"]["code"] == -32601)
    batch = json.loads(handle_line('[{"jsonrpc":"2.0","id":5,"method":"ping"}]') or "null")
    check("batch", isinstance(batch, list) and batch[0].get("id") == 5)
    check("non-object line", json.loads(handle_line("[1, 2]"))[0]["error"]["code"] == -32600)
    check("bare value line", json.loads(handle_line("42"))["error"]["code"] == -32600)

    print(f"\nread tools, against {brain.BRAIN}:")
    for tool, args in [("keel_profile", {}), ("keel_list_entities", {}), ("keel_health", {}),
                       ("keel_todo", {}), ("keel_inbox", {}), ("keel_recall", {"query": "pricing"})]:
        txt, bad = call(tool, args)
        first = txt.strip().splitlines()[0][:60] if txt.strip() else ""
        check(tool, not bad, f"{len(txt)} chars | {first}")

    # the write path runs in a throwaway brain — a selftest never touches the real one
    print("\nwrite path, in a throwaway brain:")
    real = brain.BRAIN
    with tempfile.TemporaryDirectory() as tmp:
        brain.BRAIN = pathlib.Path(tmp)
        try:
            (brain.BRAIN / "graph" / "task_types").mkdir(parents=True)
            (brain.BRAIN / "graph" / "task_types" / "pricing.md").write_text(
                "---\nid: task_type-pricing\ntype: task_type\ntitle: Pricing change\n"
                "review_by: 2099-01-01\n---\n\nChanging live prices.\n", encoding="utf-8")
            rule = {"kind": "constraint", "title": "Per-credit price falls at every tier",
                    "content": "A bigger tier never costs more per credit.",
                    "about": [{"relation": "constrains", "entity": "task_type-pricing"}]}
            txt, bad = call("keel_remember", rule)
            check("keel_remember", not bad and txt.startswith("Proposed"))
            call("keel_remember", dict(rule, content="A second take on the same rule."))
            files = sorted(p.name for p in (brain.BRAIN / "inbox").glob("*.md"))
            check("no overwrite", len(files) == 2, ", ".join(files))
            txt, bad = call("keel_inbox")
            check("keel_inbox", not bad and "2 proposal(s)" in txt)
            first = next(f for f in files if not f.endswith("-2.md"))
            txt, bad = call("keel_approve", {"file": first})
            check("keel_approve", not bad and txt.startswith("Approved"), txt.splitlines()[0])
            second = next(f for f in files if f.endswith("-2.md"))
            txt, bad = call("keel_reject", {"file": second})
            check("keel_reject", not bad and not list((brain.BRAIN / "inbox").glob("*.md")))
            txt, _ = call("keel_recall", {"query": "pricing change"})
            check("recall finds it", "Per-credit price" in txt)
            txt, bad = call("keel_approve", {"file": "../graph/task_types/pricing.md"})
            check("inbox/ only", bad and "No proposal" in txt)
        finally:
            brain.BRAIN = real

    print("\nSELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    serve()
