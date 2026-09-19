#!/usr/bin/env python3
"""
Keel MCP server — local, stdio, no dependencies.

Exposes the brain at ~/brain to any MCP client (Claude Desktop, Codex, Cursor)
as a set of tools. There is no database and no auth because there is no server:
this is a process on your own machine reading your own markdown files.

    python3 mcp_server.py            # speaks JSON-RPC on stdin/stdout
    python3 mcp_server.py --selftest # drives itself and prints a report

Anything written to stdout that is not protocol will break the client, so all
diagnostics go to stderr.
"""

import os
import sys
import json
import pathlib
import traceback
import contextlib
import fcntl
import time
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brain  # noqa: E402  — parsing, so the format has one definition

TODAY = date.today()
FALLBACK_PROTOCOL = "2025-06-18"

# what a document is worth when the context budget runs out
DOC_RANK = {"constraint": 0, "preference": 1, "decision": 2, "risk": 3,
            "playbook": 4, "task": 5, "note": 6, "commitment": 7}


DIRECTIVE_RANK = {"use": 0, "cite": 1, "confirm": 2, "verify": 3, "ignore": 4}
LEGEND = (
    "**How to treat what follows.** Each item carries a `directive`:\n"
    "- `use` — apply it; no need to mention it\n"
    "- `cite` — apply it, but say it is unconfirmed\n"
    "- `confirm` — **ASK the user before relying on it**; the work may have moved on\n"
    "- `verify` — content may be false; newer activity contradicts it\n"
    "Items marked `ignore` are withheld from this result, not deleted.\n")


@contextlib.contextmanager
def brain_lock(timeout=10):
    """Serialise writes. The nightly pass rewrites frontmatter; a concurrent
    capture must not land in the middle of that and lose."""
    lock = brain.BRAIN / "_index" / "brain.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock, "w")
    waited = 0.0
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            time.sleep(0.2); waited += 0.2
            if waited >= timeout:
                fh.close()
                raise TimeoutError("brain is locked by another process")
    try:
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()


def state_of(n):
    return (n.get("directive") or "use").strip().strip('"')


def log(msg):
    print(f"[keel] {msg}", file=sys.stderr, flush=True)


def tokens(text):
    return {w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split()
            if len(w) > 2}


# ---------------------------------------------------------------- retrieval

def retrieve(query, budget=6000):
    """Two-step: anchor on entities, then pull only what is written about them."""
    nodes = brain.load_nodes()
    if not nodes:
        return f"No brain found at {brain.BRAIN}."
    ents = [n for n in nodes if brain.is_entity(n)]
    docs = [n for n in nodes if not brain.is_entity(n)]
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
    anchors = [e for _, e in scored[:4] if state_of(e) != "ignore"]

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
    picked = []
    withheld = 0
    for d in docs:
        if d.get("status") in ("superseded", "archived") or state_of(d) == "ignore":
            withheld += 1
            continue
        hits = [a for a in d.get("about", []) if a.get("entity") in focus]
        if hits:
            picked.append((DOC_RANK.get(d.get("type"), 9), d, hits[0].get("relation", "about")))
    # A trustworthy document outranks a merely on-topic one.
    picked.sort(key=lambda x: (DIRECTIVE_RANK.get(state_of(x[1]), 0),
                               x[0], x[1].get("updated", "")))
    picked = picked[:7]        # precision over recall — four right beats forty plausible

    out, used = [LEGEND], 0
    if anchors:
        out.append("## Anchored on\n" + "\n".join(
            f"- **{e.get('title', e['id'])}** ({e.get('type')}) · `{state_of(e)}`"
            + (f" — {e.get('state_note', '').strip(chr(34))}" if state_of(e) in ("confirm", "verify")
               else f" — {e['_body'].splitlines()[0][:100] if e['_body'] else ''}")
            for e in anchors))
    else:
        out.append(f"No entity in the graph matched \"{query}\". "
                   f"Falling back to whatever the wiki has on it.")
        picked = [(DOC_RANK.get(d.get("type"), 9), d, "about") for d in docs
                  if q & tokens(d.get("title", "") + " " + d["_body"][:800])][:6]

    if picked:
        out.append("\n## What is written about them")
        for _, d, rel in picked:
            body = d["_body"]
            if used + len(body) > budget:
                body = body[:max(300, budget - used)] + "\n…(truncated)"
            stale = " ⚠ past review date" if (
                (rv := brain.as_date(d.get("review_by"))) and rv < TODAY) else ""
            out.append(f"\n### {d.get('type', '?').upper()} · {d.get('title', d['id'])}"
                       f"{stale}\n*directive: **{state_of(d)}** · {d.get('relevance', '?')} · "
                       f"{d.get('evidence', d.get('confidence', '?'))} · {rel} · "
                       f"{d.get('_path')}*\n\n{body}")
            used += len(body)
            if used > budget:
                out.append("\n_(budget reached — ask again with a narrower query for more)_")
                break
    else:
        out.append("\nNothing is written about these yet.")

    gated = [x for x in ([a for a in anchors] + [d for _, d, _ in picked])
             if state_of(x) in ("confirm", "verify")]
    if gated:
        out.append("\n## Before you use this\n"
                   "These are **not** cleared for silent use — ask the user first:")
        for g in gated:
            note = (g.get("state_note") or "").strip('"')
            out.append(f"- **{g.get('title', g['id'])}** (`{state_of(g)}`)"
                       + (f" — {note}" if note else ""))
    if withheld:
        out.append(f"\n_{withheld} item(s) withheld as `ignore` — retained on disk, "
                   f"ask by name if you need them._")
    return "\n".join(out)


def list_entities(kind=None):
    nodes = [n for n in brain.load_nodes() if brain.is_entity(n)]
    if kind:
        nodes = [n for n in nodes if n.get("type") == kind]
    if not nodes:
        return "No entities." if not kind else f"No entities of type {kind}."
    docs = [n for n in brain.load_nodes() if not brain.is_entity(n)]
    count = {}
    for d in docs:
        for a in d.get("about", []):
            count[a.get("entity")] = count.get(a.get("entity"), 0) + 1
    rows = sorted(nodes, key=lambda n: (n.get("type", ""), n.get("title", "")))
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


DOC_DIRS = {"decision": "decisions", "preference": "preferences", "risk": "risks",
            "constraint": "constraints", "playbook": "playbooks", "note": "notes",
            "task": "tasks"}
ENT_DIRS = {"task_type": "task_types", "person": "people", "org": "orgs",
            "project": "tasks", "skill": "skills", "system": "systems"}


def remember(kind, title, content, about=None, confidence="medium", review_months=6):
    """Write straight into the brain, marked as unconfirmed.

    There is no review queue any more: one that nobody walks through is not a
    safety mechanism, it is a queue that rots while the graph stays frozen. A
    single capture lands as `evidence: inferred` / `directive: cite`, so a later
    session applies it but says it is unconfirmed. The nightly pass promotes it
    to `observed` once the same thing shows up in three independent sessions,
    and demotes it to `confirm` when the work goes quiet. Nothing is deleted.
    """
    slug = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")[:60]
    slug = "-".join(p for p in slug.split("-") if p)
    if kind in ENT_DIRS:
        dest_dir = brain.BRAIN / "graph" / ENT_DIRS[kind]
    else:
        dest_dir = brain.BRAIN / "wiki" / DOC_DIRS.get(kind, "notes")
    path = dest_dir / f"{slug}.md"

    yr, mo = TODAY.year, TODAY.month + review_months
    yr, mo = yr + (mo - 1) // 12, (mo - 1) % 12 + 1
    review = f"{yr}-{mo:02d}-{min(TODAY.day, 28):02d}"

    fm = [f"id: {kind}-{slug}", f"type: {kind}",
          f"last_activity: {TODAY}", "relevance: current",
          "evidence: inferred", "directive: cite",
          f"title: {title}", "status: active", f"confidence: {confidence}",
          "scope: personal", "provenance: mcp:session", f"created: {TODAY}",
          f"updated: {TODAY}", f"review_by: {review}"]
    valid = {n["id"] for n in brain.load_nodes()}
    refs = [a for a in (about or []) if a.get("entity") in valid]
    dropped = [a.get("entity") for a in (about or []) if a.get("entity") not in valid]
    if refs:
        fm.append("about:")
        for a in refs:
            fm += [f"  - relation: {a.get('relation', 'concerns')}",
                   f"    entity: {a['entity']}"]

    try:
        with brain_lock():
            dest_dir.mkdir(parents=True, exist_ok=True)
            if path.exists():
                path = dest_dir / f"{slug}-{TODAY}.md"
            path.write_text("---\n" + "\n".join(fm) + "\n---\n\n"
                            + content.strip() + "\n")
    except TimeoutError:
        return ("Could not write — the brain is locked by the nightly pass. "
                "Try again in a moment.")

    msg = (f"Written → {path.relative_to(brain.BRAIN)}\n"
           f"In the brain now, as `directive: cite` — a session will apply it but say "
           f"it is unconfirmed until it recurs in three independent sessions.")
    if dropped:
        msg += f"\n⚠ dropped unknown entities: {', '.join(dropped)}"
    if not refs:
        msg += "\n⚠ no graph anchor — findable by search only."
    return msg


def pending_confirmations():
    """Everything the brain will not let a session use silently."""
    rows = []
    for n in brain.load_nodes():
        d = state_of(n)
        if d in ("confirm", "verify"):
            rows.append((DIRECTIVE_RANK[d], d, n))
    if not rows:
        return "Nothing is gated — every item in the brain is cleared for use."
    rows.sort(key=lambda r: -r[0])
    out = ["These need the user's confirmation before you rely on them:\n"]
    for _, d, n in rows:
        note = (n.get("state_note") or "").strip('"')
        out.append(f"- **{n.get('title', n['id'])}** (`{n.get('type')}`) — `{d}`"
                   + (f"\n    {note}" if note else ""))
    out.append("\nAsk once, in one line, naming what you want to use it for.")
    return "\n".join(out)


def run_report(fn):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue() or "(no output)"


# ---------------------------------------------------------------- tools

TOOLS = [
    {"name": "keel_recall",
     "description": "Retrieve relevant context from the user's brain: preferences, decisions, "
                    "constraints, risks and playbooks about whatever this session touches. Call "
                    "this BEFORE substantive work — drafting a document, making a decision, "
                    "running a recurring piece of work, or anything involving named colleagues.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "What the session is about — a project, "
                                                    "person, kind of work, or topic."},
         "budget": {"type": "integer", "description": "Max characters of document text (default 6000)."}},
         "required": ["query"]}},
    {"name": "keel_remember",
     "description": "Capture something worth keeping. It goes straight into the brain marked "
                    "unconfirmed (directive: cite) — there is no review queue. A decision with its "
                    "rejected alternative, a constraint, a scoped preference, a risk with a review "
                    "date, a person fact, a playbook. Never writes into the brain directly — the "
                    "user approves first.",
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["decision", "risk", "constraint", "preference",
                                             "playbook", "note", "commitment"]},
         "title": {"type": "string"},
         "content": {"type": "string", "description": "Markdown body. For a decision, always "
                                                      "include what was rejected and why."},
         "about": {"type": "array", "description": "Graph anchors. Use keel_list_entities to get ids.",
                   "items": {"type": "object", "properties": {
                       "relation": {"type": "string"}, "entity": {"type": "string"}},
                       "required": ["entity"]}},
         "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
         "required": ["kind", "title", "content"]}},
    {"name": "keel_list_entities",
     "description": "List entities in the graph — people, orgs, tasks, kinds of work, skills — "
                    "with their ids. Use before keel_remember to anchor a document correctly.",
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "description": "Optional filter, e.g. person or task_type."}}}},
    {"name": "keel_read",
     "description": "Read one node in full by its id.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                     "required": ["id"]}},
    {"name": "keel_pending",
     "description": "List everything in the brain that must NOT be used silently — items "
                    "whose topic has gone quiet, or whose content newer activity "
                    "contradicts. Call this when starting substantive work so you know "
                    "what to ask about before you rely on it.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "keel_health",
     "description": "Is the brain still being fed, still true, still retrievable? Reports "
                    "staleness, broken references, unanchored documents and capture rate.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "keel_missing",
     "description": "Structural gaps: decisions with no rejected alternative, kinds of work with "
                    "no playbook, global preferences that probably want scoping, people with no org.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "keel_todo",
     "description": "Open loops and live risks — what is owed, what is being waited on, what is "
                    "past its review date.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def call_tool(name, args):
    if name == "keel_recall":
        return retrieve(args["query"], int(args.get("budget") or 6000))
    if name == "keel_remember":
        return remember(args["kind"], args["title"], args["content"],
                        args.get("about"), args.get("confidence", "medium"))
    if name == "keel_list_entities":
        return list_entities(args.get("kind"))
    if name == "keel_read":
        return read_node(args["id"])
    if name == "keel_pending":
        return pending_confirmations()
    if name == "keel_health":
        return run_report(brain.cmd_health)
    if name == "keel_missing":
        return run_report(brain.cmd_missing)
    if name == "keel_todo":
        return run_report(brain.cmd_todo)
    raise ValueError(f"unknown tool: {name}")


# ---------------------------------------------------------------- protocol

def handle(msg):
    """Returns a response dict, or None for notifications."""
    method, mid = msg.get("method"), msg.get("id")

    if method == "initialize":
        client = (msg.get("params") or {}).get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": client or FALLBACK_PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "keel", "version": "1.0.0"}}}

    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            text = call_tool(p.get("name"), p.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": text}]}}
        except Exception as e:
            log(f"tool error: {traceback.format_exc()}")
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": f"Error: {e}"}],
                               "isError": True}}

    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve():
    log(f"brain at {brain.BRAIN} — {len(brain.load_nodes())} nodes")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            log("skipped non-JSON line")
            continue
        try:
            resp = handle(msg)
        except Exception:
            log(traceback.format_exc())
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": "internal error"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        ok = True
        r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}})
        print(f"initialize      → {r['result']['serverInfo']['name']} "
              f"proto {r['result']['protocolVersion']}")
        r = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in r["result"]["tools"]]
        print(f"tools/list      → {len(names)}: {', '.join(names)}")
        ok &= len(names) == 7
        print(f"notification    → {handle({'jsonrpc':'2.0','method':'notifications/initialized'})}")
        for tool, args in [("keel_list_entities", {}), ("keel_health", {}),
                           ("keel_recall", {"query": "pricing"})]:
            r = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": tool, "arguments": args}})
            txt = r["result"]["content"][0]["text"]
            bad = r["result"].get("isError")
            ok &= not bad
            print(f"{tool:<18}→ {'ERROR ' if bad else ''}{len(txt)} chars"
                  f"{' | ' + txt.splitlines()[0][:60] if txt.strip() else ''}")
        r = handle({"jsonrpc": "2.0", "id": 4, "method": "nope/nope"})
        print(f"unknown method  → {r['error']['code']}")
        print("\nSELFTEST", "PASS" if ok else "FAIL")
        sys.exit(0 if ok else 1)
    serve()
