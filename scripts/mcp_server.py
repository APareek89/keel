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
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brain  # noqa: E402  — parsing, so the format has one definition

TODAY = date.today()
FALLBACK_PROTOCOL = "2025-06-18"

# what a document is worth when the context budget runs out
DOC_RANK = {"constraint": 0, "preference": 1, "decision": 2, "risk": 3,
            "playbook": 4, "task": 5, "note": 6, "commitment": 7}


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
    picked = []
    for d in docs:
        if d.get("status") in ("superseded", "archived"):
            continue
        hits = [a for a in d.get("about", []) if a.get("entity") in focus]
        if hits:
            picked.append((DOC_RANK.get(d.get("type"), 9), d, hits[0].get("relation", "about")))
    picked.sort(key=lambda x: (x[0], x[1].get("updated", "")))
    picked = picked[:7]        # precision over recall — four right beats forty plausible

    out, used = [], 0
    if anchors:
        out.append("## Anchored on\n" + "\n".join(
            f"- **{e.get('title', e['id'])}** ({e.get('type')}) — {e['_body'].splitlines()[0][:110] if e['_body'] else ''}"
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
                       f"{stale}\n*{rel} · {d.get('confidence', '?')} confidence · "
                       f"{d.get('_path')}*\n\n{body}")
            used += len(body)
            if used > budget:
                out.append("\n_(budget reached — ask again with a narrower query for more)_")
                break
    else:
        out.append("\nNothing is written about these yet.")
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


def remember(kind, title, content, about=None, confidence="medium", review_months=6):
    """Write a proposal to inbox/. Never straight into the brain — the review gate
    is the only thing between a useful brain and a poisoned one."""
    slug = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")[:60]
    slug = "-".join(p for p in slug.split("-") if p)
    inbox = brain.BRAIN / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{TODAY}-{kind}-{slug}.md"

    yr, mo = TODAY.year, TODAY.month + review_months
    yr, mo = yr + (mo - 1) // 12, (mo - 1) % 12 + 1
    review = f"{yr}-{mo:02d}-{min(TODAY.day, 28):02d}"

    fm = [f"id: {kind}-{slug}", f"type: {kind}", f"title: {title}",
          "status: active", f"confidence: {confidence}", "scope: personal",
          "provenance: mcp:session", f"created: {TODAY}", f"updated: {TODAY}",
          f"review_by: {review}"]
    valid = {n["id"] for n in brain.load_nodes()}
    refs = [a for a in (about or []) if a.get("entity") in valid]
    dropped = [a.get("entity") for a in (about or []) if a.get("entity") not in valid]
    if refs:
        fm.append("about:")
        for a in refs:
            fm += [f"  - relation: {a.get('relation', 'concerns')}",
                   f"    entity: {a['entity']}"]

    path.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + content.strip() + "\n")
    msg = f"Proposed → {path.relative_to(brain.BRAIN)}\nNot in the brain until approved (`/keel review`)."
    if dropped:
        msg += f"\n⚠ dropped unknown entities: {', '.join(dropped)}"
    if not refs:
        msg += "\n⚠ no graph anchor — this will be findable by search only."
    return msg


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
     "description": "Capture something worth keeping into the review inbox: a decision with its "
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
