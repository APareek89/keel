#!/usr/bin/env python3
"""
Keel brain tools.

    brain.py health             fed? true? retrievable? will the brief work?
    brain.py missing            structural gaps
    brain.py todo               open loops, commitments, open tasks, live risks
    brain.py view [--no-open]   writes an HTML overview + knowledge graph and opens it
    brain.py inbox              proposals waiting for review
    brain.py approve <file>     file a proposal from inbox/ into the brain
    brain.py reject <file>      delete a proposal
    brain.py connectors --seen a,b [--record]
    brain.py export-codex       profile + global preferences into ~/.codex/AGENTS.md

Reads ~/brain (override with BRAIN_DIR). Standard library only — no pip install,
no external assets, so the HTML works offline and nothing leaves the machine.
"""

import os
import sys
import json
import pathlib
import webbrowser
from pathlib import Path
from datetime import date, datetime, timedelta

BRAIN = Path(os.environ.get("BRAIN_DIR", Path.home() / "brain"))
SKIP_DIRS = {"_templates", "_index", "inbox", "journal"}
TODAY = date.today()


# ---------------------------------------------------------------- parsing

def parse_frontmatter(text):
    """Parse the YAML subset this KB actually uses. Returns {} if no frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, ""
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, ""

    meta, edges, about, cur = {}, [], [], None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()

        if indent == 0 and ":" in line:
            cur = None
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if key in ("edges", "about"):
                cur = key
                continue
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                meta[key] = [v.strip() for v in inner.split(",") if v.strip()] if inner else []
            else:
                meta[key] = val.strip('"\'')
        elif cur in ("edges", "about"):
            bucket = edges if cur == "edges" else about
            if line.startswith("- "):
                bucket.append({})
                line = line[2:].strip()
            if ":" in line and bucket:
                k, _, v = line.partition(":")
                bucket[-1][k.strip()] = v.strip().strip('"\'')

    meta["edges"] = [e for e in edges if e.get("to")]
    meta["about"] = [a for a in about if a.get("entity")]
    return meta, "\n".join(lines[end + 1:]).strip()


def load_nodes():
    nodes = []
    if not BRAIN.exists():
        return nodes
    for path in sorted(BRAIN.rglob("*.md")):
        rel = path.relative_to(BRAIN)
        if rel.parts and rel.parts[0] in SKIP_DIRS:
            continue
        if path.name == "README.md":
            continue
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if not meta.get("id"):
            continue
        meta["_path"] = str(rel)
        meta["_body"] = body
        nodes.append(meta)
    return nodes


def as_date(value):
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# Two layers. The graph holds things with identity that relate to each other;
# everything else is a statement *about* those things — prose to be read, not
# traversed. Mixing them is what makes the graph unreadable.
# a project is just a task with children — one recursive type, not two
ENTITY_TYPES = {"profile", "person", "org", "task", "task_type", "skill", "system"}
DOC_TYPES = {"decision", "risk", "constraint", "preference", "playbook", "note", "commitment"}

# where an approved node is filed. The profile is the one fixed path: graph/profile.md
FOLDER = {
    "person": "graph/people", "org": "graph/orgs", "task": "graph/tasks",
    "task_type": "graph/task_types", "skill": "graph/skills", "system": "graph/systems",
    "decision": "wiki/decisions", "risk": "wiki/risks", "constraint": "wiki/constraints",
    "preference": "wiki/preferences", "playbook": "wiki/playbooks", "note": "wiki/notes",
    "commitment": "wiki/commitments",
}

# the one edge pair in the vocabulary with an inverse — approval adds the other half
INVERSE = {"owns": "owned_by", "owned_by": "owns"}

INACTIVE = ("superseded", "archived")


def is_entity(n):
    return n.get("type") in ENTITY_TYPES


def is_global_preference(n):
    """A preference with no `about:` fires on every session. One with `about:`
    is scoped: it loads only when what it's about is in play."""
    return n.get("type") == "preference" and not n.get("about")


def add_months(d, months):
    y, m = d.year, d.month + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return date(y, m, min(d.day, 28))


def hook_sources():
    """What loads into every session: the profile and the global preferences.
    One definition for the SessionStart hook, the Codex export and the MCP
    server. Load a scoped preference everywhere and scoping means nothing."""
    paths = []
    profile = BRAIN / "graph" / "profile.md"
    if profile.exists():
        paths.append(profile)
    prefs = BRAIN / "wiki" / "preferences"
    for p in (sorted(prefs.glob("*.md")) if prefs.is_dir() else []):
        try:
            meta, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if not meta.get("about") and meta.get("status") not in INACTIVE:
            paths.append(p)
    return paths


def standing_context(budget=6000):
    """(path in the brain, text) for each hook source that fits the budget, plus
    the paths of any skipped for size. The budget stops one file that grew
    unbounded from quietly taxing every session."""
    loaded, skipped, used = [], [], 0
    for p in hook_sources():
        try:
            text = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        rel = str(p.relative_to(BRAIN))
        if used + len(text) > budget:
            skipped.append(rel)
            continue
        loaded.append((rel, text))
        used += len(text)
    return loaded, skipped


def loop_rows(name):
    """Data rows of loops/<name>.md, a hand-kept markdown table. The header is
    the row just above the |---| rule; `_(empty` rows are placeholders."""
    f = BRAIN / "loops" / f"{name}.md"
    if not f.exists():
        return []
    lines = [ln.strip() for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()]

    def is_rule(ln):
        return ln.startswith("|") and set(ln) <= set("|-: ")

    rows = []
    for i, ln in enumerate(lines):
        if not ln.startswith("|") or is_rule(ln) or "_(empty" in ln:
            continue
        if i + 1 < len(lines) and is_rule(lines[i + 1]):
            continue                                   # header row
        rows.append(ln)
    return rows


def direction_of(c):
    return ((c.get("direction") or "").split() or ["owed"])[0]


def open_commitments(nodes, direction):
    """Commitment documents not yet done, `direction: owed` or `waiting-on`,
    soonest due first."""
    return sorted((n for n in nodes if n.get("type") == "commitment"
                   and n.get("status") not in ("done",) + INACTIVE
                   and direction_of(n) == direction),
                  key=lambda n: str(as_date(n.get("due")) or "9999"))


def commitment_line(c):
    """One line for the brief: what, with whom, when — and how long the silence is."""
    bits = [c.get("title") or c["id"]]
    if c.get("counterparty"):
        bits.append(c["counterparty"])
    due = as_date(c.get("due"))
    if due:
        bits.append(f"due {due}")
    asked = as_date(c.get("created"))
    if direction_of(c) == "waiting-on" and asked:
        bits.append(f"asked {(TODAY - asked).days} day(s) ago")
    line = "  ·  ".join(bits)
    return line + ("  ← PAST DUE" if due and due < TODAY else "")


def analyse(nodes):
    """Graph metrics over ENTITIES only. Documents attach by `about:` and are
    counted per entity rather than drawn as nodes."""
    ents = [n for n in nodes if is_entity(n)]
    docs = [n for n in nodes if not is_entity(n)]
    ids = {n["id"] for n in ents}
    all_ids = {n["id"] for n in nodes}
    linked = set()
    edges, dangling = [], []

    for n in ents:
        for e in n.get("edges", []):
            target = e.get("to")
            if target in ids:
                edges.append({"from": n["id"], "to": target, "type": e.get("type", "related")})
                linked.add(n["id"])
                linked.add(target)
            elif target in all_ids:
                dangling.append((n["id"], target, n["_path"] + "  (points at a document — move to its `about:`)"))
            else:
                dangling.append((n["id"], target, n["_path"]))

    # documents reference the graph; unanchored ones are search-only
    doc_count, unanchored = {}, []
    for d in docs:
        refs = [a for a in d.get("about", []) if a.get("entity") in ids]
        bad = [a for a in d.get("about", []) if a.get("entity") not in all_ids]
        for a in refs:
            doc_count[a["entity"]] = doc_count.get(a["entity"], 0) + 1
        for a in bad:
            dangling.append((d["id"], a["entity"], d["_path"]))
        # a global preference (no `about:`) is loaded by the hook every session,
        # never retrieved by walking — it is correctly unanchored, not a gap.
        if not refs and not is_global_preference(d):
            unanchored.append(d)

    stale = [n for n in nodes
             if (d := as_date(n.get("review_by"))) and d < TODAY
             and n.get("status") not in ("archived", "superseded")]
    undated = [n for n in nodes if not as_date(n.get("review_by"))]
    # only entities can be orphaned — a document is never walked to, it's read.
    orphans = [n for n in ents if n["id"] not in linked and n.get("type") != "profile"]
    low_conf = [n for n in nodes if n.get("confidence") == "low"]

    # capture rate — nodes created per week, last 4 weeks
    weeks = []
    for w in range(4):
        start = TODAY - timedelta(days=7 * (w + 1))
        end = TODAY - timedelta(days=7 * w)
        count = sum(1 for n in nodes if (d := as_date(n.get("created"))) and start < d <= end)
        weeks.append(count)

    created = [d for n in nodes if (d := as_date(n.get("created")))]
    updated = [d for n in nodes if (d := as_date(n.get("updated")))]

    inbox_dir = BRAIN / "inbox"
    inbox = sorted(inbox_dir.glob("*.md")) if inbox_dir.exists() else []

    types = {}
    for n in nodes:
        types[n.get("type", "untyped")] = types.get(n.get("type", "untyped"), 0) + 1

    return {
        "nodes": nodes, "entities": ents, "docs": docs,
        "edges": edges, "types": types, "doc_count": doc_count,
        "unanchored": unanchored,
        "stale": stale, "undated": undated, "orphans": orphans,
        "dangling": dangling, "low_conf": low_conf,
        "weeks": weeks, "inbox": inbox,
        "last_created": max(created) if created else None,
        "last_updated": max(updated) if updated else None,
    }


# ---------------------------------------------------------------- health

def cmd_health():
    nodes = load_nodes()
    if not nodes:
        print(f"No brain found at {BRAIN}. Nothing to report.")
        return 1

    a = analyse(nodes)
    problems = []

    print(f"\n  BRAIN HEALTH · {BRAIN}  ·  {TODAY}")
    print("  " + "-" * 58)
    print(f"  GRAPH  {len(a['entities'])} entities · {len(a['edges'])} edges")
    print(f"  WIKI   {len(a['docs'])} documents · "
          f"{len(a['docs']) - len(a['unanchored'])} anchored to the graph")
    print("  " + "  ".join(f"{k}:{v}" for k, v in sorted(a["types"].items(), key=lambda x: -x[1])))

    # --- is capture still happening?
    print("\n  IS IT STILL BEING FED?")
    days_quiet = (TODAY - a["last_created"]).days if a["last_created"] else None
    w = a["weeks"]
    print(f"    Nodes added, last 4 weeks (newest first): {w[0]}, {w[1]}, {w[2]}, {w[3]}")
    if days_quiet is None:
        print("    ! No creation dates found.")
    elif days_quiet > 14:
        problems.append(f"nothing captured in {days_quiet} days — capture has stopped")
        print(f"    ! Nothing new in {days_quiet} days. The brain is going stale at the source.")
    elif days_quiet > 7:
        print(f"    ~ Quiet for {days_quiet} days.")
    else:
        print(f"    ✓ Last addition {days_quiet} day(s) ago.")

    if a["inbox"]:
        oldest = min(p.stat().st_mtime for p in a["inbox"])
        age = (datetime.now() - datetime.fromtimestamp(oldest)).days
        print(f"    {len(a['inbox'])} item(s) waiting in inbox, oldest {age} day(s) old.")
        if age > 7:
            problems.append(f"{len(a['inbox'])} proposals unreviewed for over a week")
    else:
        print("    Inbox empty — nothing awaiting your review.")

    # the hook loading nothing is invisible in normal use — check it explicitly
    if not hook_sources():
        problems.append("SessionStart hook has nothing to load — paths moved?")
        print("\n  ! The hook finds no profile or global preferences. It is silently")
        print("    loading nothing into every session. Expected graph/profile.md, or")
        print("    wiki/preferences/*.md with no `about:`")

    # --- is what's in there still true?
    print("\n  IS IT STILL TRUE?")
    if a["stale"]:
        problems.append(f"{len(a['stale'])} node(s) past review date")
        print(f"    ! {len(a['stale'])} past their review date:")
        for n in sorted(a["stale"], key=lambda n: n.get("review_by", ""))[:8]:
            print(f"        {n.get('review_by')}  {n['id']}  ({n['_path']})")
    else:
        print("    ✓ Nothing past its review date.")
    if a["undated"]:
        problems.append(f"{len(a['undated'])} node(s) with no expiry")
        print(f"    ! {len(a['undated'])} node(s) with no review_by — these can never be caught rotting:")
        for n in a["undated"][:5]:
            print(f"        {n['_path']}")
    if a["low_conf"]:
        print(f"    ~ {len(a['low_conf'])} low-confidence node(s) — worth confirming or dropping.")
    # a stale Codex export means Codex is silently running on old preferences
    stamp = BRAIN / "_index" / "codex_export.json"
    if stamp.exists():
        try:
            info = json.loads(stamp.read_text())
        except (ValueError, OSError):
            info = {}
        exported = as_date(info.get("exported"))
        srcs = hook_sources()
        dates = [d for p in srcs
                 if (d := as_date(parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))[0].get("updated")))]
        newest = max(dates, default=None)
        moved = sorted(info.get("files") or []) != sorted(str(p.relative_to(BRAIN)) for p in srcs)
        if exported and ((newest and newest > exported) or moved):
            problems.append("Codex export is stale — re-run export-codex")
            print(f"    ! Codex export is from {exported} but the profile or global preferences "
                  f"changed since. Codex is running on old preferences:")
            print(f"        python3 {pathlib_str(__file__)} export-codex")

    # --- can it actually be found?
    print("\n  CAN IT BE RETRIEVED?")
    if a["dangling"]:
        problems.append(f"{len(a['dangling'])} broken edge(s)")
        print(f"    ! {len(a['dangling'])} edge(s) point at nodes that don't exist:")
        for src, tgt, path in a["dangling"][:8]:
            print(f"        {src} → {tgt}   ({path})")
    else:
        print("    ✓ All edges resolve.")
    if a["unanchored"]:
        problems.append(f"{len(a['unanchored'])} document(s) not anchored to the graph")
        print(f"    ! {len(a['unanchored'])} document(s) with no `about:` — findable only by "
              f"search, never by walking from an entity:")
        for n in a["unanchored"][:8]:
            print(f"        {n['id']}  ({n['_path']})")
    else:
        print("    ✓ Every document is anchored to at least one entity.")
    if a["orphans"]:
        print(f"    ~ {len(a['orphans'])} entity(s) with no edges — rarely surfaced, since retrieval "
              f"walks the graph:")
        for n in a["orphans"][:8]:
            print(f"        {n['id']}  ({n['_path']})")
    else:
        print("    ✓ Every entity is reachable.")

    # --- will the brief have anything to say?
    print("\n  WILL THE MORNING BRIEF WORK?")
    in_use = any(n.get("type") == "commitment" for n in nodes)
    for name in ("owed", "waiting-on"):
        n = len(open_commitments(nodes, name)) + len(loop_rows(name))
        if n:
            print(f"    ✓ {name}: {n} item(s).")
            continue
        print(f"    ! {name}: nothing recorded — this block of the brief will be blank.")
        print(f"      A commitment with `direction: {name}` fills it, or a row in loops/{name}.md.")
        # only a problem once the brief is in use — a fresh brain isn't nagged
        if in_use or (BRAIN / "loops" / f"{name}.md").exists():
            problems.append(f"nothing recorded as {name}")

    print("\n  " + "-" * 58)
    if problems:
        print(f"  {len(problems)} thing(s) need attention:")
        for p in problems:
            print(f"    · {p}")
    else:
        print("  ✓ Healthy.")
    print()
    return 0


# ---------------------------------------------------------------- view

PALETTE = {
    "profile": "#2C6A5C", "preference": "#2C6A5C", "decision": "#A8641F",
    "constraint": "#9B3A2E", "task": "#2F5D8A", "project": "#2F5D8A", "person": "#6B4A8F",
    "org": "#6B4A8F", "team": "#6B4A8F", "commitment": "#8A6A16",
    "product": "#2F5D8A", "metric": "#2F5D8A", "playbook": "#4A7A5E",
}


def cmd_view(auto_open=True):
    nodes = load_nodes()
    if not nodes:
        print(f"No brain found at {BRAIN}.")
        return 1
    a = analyse(nodes)

    # documents grouped by the entity they are about
    docs_for = {}
    for d in a["docs"]:
        for ref in d.get("about", []):
            docs_for.setdefault(ref["entity"], []).append({
                "id": d["id"], "title": d.get("title", d["id"]),
                "type": d.get("type", ""), "relation": ref.get("relation", "about"),
                "path": d["_path"],
                "stale": bool((dt := as_date(d.get("review_by"))) and dt < TODAY),
                "excerpt": " ".join(d["_body"].split())[:260],
            })

    payload = {
        "nodes": [{
            "id": n["id"],
            "title": n.get("title", n["id"]),
            "type": n.get("type", "untyped"),
            "status": n.get("status", ""),
            "confidence": n.get("confidence", ""),
            "review_by": n.get("review_by", ""),
            "updated": n.get("updated", ""),
            "path": n["_path"],
            "stale": bool((d := as_date(n.get("review_by"))) and d < TODAY),
            "excerpt": " ".join(n["_body"].split())[:300],
            "docs": sorted(docs_for.get(n["id"], []), key=lambda x: x["type"]),
            "color": PALETTE.get(n.get("type", ""), "#7A8480"),
        } for n in a["entities"]],
        "edges": a["edges"],
        "stats": {
            "nodes": len(a["entities"]), "docs": len(a["docs"]),
            "unanchored": len(a["unanchored"]), "edges": len(a["edges"]),
            "stale": len(a["stale"]), "orphans": len(a["orphans"]),
            "dangling": len(a["dangling"]), "inbox": len(a["inbox"]),
            "types": a["types"],
            "weeks": a["weeks"],
            "last": str(a["last_created"] or "—"),
        },
        "generated": str(TODAY),
        "brain": str(BRAIN),
    }

    out = BRAIN / "_index"
    out.mkdir(exist_ok=True)
    target = out / "brain.html"
    target.write_text(HTML.replace("__DATA__", json.dumps(payload)), encoding="utf-8")

    print(f"Wrote {target}  ({payload['stats']['nodes']} nodes, {payload['stats']['edges']} edges)")
    if auto_open and not open_in_browser(target):
        print("  Open it in a browser — there's no desktop session here to open it in.")
    return 0


def open_in_browser(path):
    """Open a local file in the desktop browser — macOS, Linux or Windows.
    With no desktop session it does nothing, rather than start a terminal
    browser that would hang whoever ran the command."""
    if sys.platform.startswith("linux") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        return webbrowser.open(path.resolve().as_uri())
    except Exception:
        return False


HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Brain</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#F6F8F7;--surface:#fff;--sunk:#EDF1EF;--ink:#171D1B;--mut:#59635F;
--faint:#8A938F;--rule:#D6DEDA;--acc:#2C6A5C;--warn:#8A6A16;--crit:#9B3A2E}
@media(prefers-color-scheme:dark){:root{--bg:#101413;--surface:#171D1B;--sunk:#1D2523;
--ink:#E3E9E6;--mut:#98A29E;--faint:#6C7672;--rule:#2A3331;--acc:#5FAC97;--warn:#C6A34E;--crit:#D2796B}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
header{padding:26px 30px 20px;border-bottom:1px solid var(--rule)}
h1{margin:0 0 4px;font:500 21px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:-.01em}
.sub{color:var(--faint);font-size:12.5px}
.stats{display:flex;flex-wrap:wrap;gap:10px;padding:18px 30px}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:5px;padding:11px 15px;min-width:104px}
.card .n{font:600 22px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}
.card .l{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin-top:4px}
.card.bad .n{color:var(--crit)} .card.warn .n{color:var(--warn)}
main{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:0;height:calc(100vh - 200px);min-height:600px}
@media(max-width:880px){main{grid-template-columns:1fr;height:auto}#side{border-left:none;border-top:1px solid var(--rule)}}
#wrap{position:relative;margin:0 0 0 30px;border:1px solid var(--rule);border-radius:5px;background:var(--surface);overflow:hidden}
canvas{display:block;width:100%;height:100%;cursor:grab}
canvas:active{cursor:grabbing}
#legend{position:absolute;left:12px;bottom:12px;display:flex;flex-wrap:wrap;gap:5px;max-width:75%}
.tag{font-size:10px;letter-spacing:.04em;text-transform:uppercase;padding:2px 7px;border-radius:3px;
background:var(--sunk);color:var(--mut);display:flex;align-items:center;gap:5px}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}
#side{padding:0 30px 30px;overflow-y:auto}
#side h2{font:600 12px/1 -apple-system,system-ui,sans-serif;letter-spacing:.09em;text-transform:uppercase;
color:var(--faint);margin:0 0 12px}
.hint{color:var(--faint);font-size:13px}
.nt{font:500 15px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;margin:0 0 6px}
.meta{font-size:11.5px;color:var(--faint);margin-bottom:12px;font-variant-numeric:tabular-nums}
.ex{font-size:13px;color:var(--mut);border-left:2px solid var(--rule);padding-left:11px;margin-bottom:14px}
.rel{font-size:12.5px;color:var(--mut);margin:3px 0}
.rel b{color:var(--acc);font-weight:600}
.doc{border-left:2px solid var(--rule);padding:2px 0 2px 10px;margin:5px 0 8px}
.dt{font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
 color:var(--faint);margin-right:6px}
.dx{font-size:11.5px;color:var(--faint);line-height:1.45;margin-top:3px}
.pill{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
padding:2px 6px;border-radius:3px;background:var(--sunk);color:var(--faint);margin-left:6px}
.pill.stale{background:var(--crit);color:#fff}
</style></head><body>
<header><h1>Brain</h1><div class="sub" id="hdr"></div></header>
<div class="stats" id="stats"></div>
<main><div id="wrap"><canvas id="c"></canvas><div id="legend"></div></div>
<div id="side"><h2>Entity</h2><div id="detail" class="hint">Click any entity to see what the wiki knows about it.</div></div></main>
<script>
const D = __DATA__;
document.getElementById('hdr').textContent =
  D.brain + ' · generated ' + D.generated + ' · last addition ' + D.stats.last;

const S=D.stats, cards=[['Entities',S.nodes,''],['Edges',S.edges,''],
 ['Wiki docs',S.docs,''],['Unanchored',S.unanchored,S.unanchored?'warn':''],
 ['Stale',S.stale,S.stale?'bad':''],['Orphans',S.orphans,S.orphans?'warn':''],
 ['Broken links',S.dangling,S.dangling?'bad':''],['In review',S.inbox,'']];
document.getElementById('stats').innerHTML = cards.map(([l,n,c])=>
 `<div class="card ${c}"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');

const types=[...new Set(D.nodes.map(n=>n.type))].sort();
document.getElementById('legend').innerHTML = types.map(t=>{
  const c=(D.nodes.find(n=>n.type===t)||{}).color;
  return `<span class="tag"><i class="dot" style="background:${c}"></i>${t}</span>`}).join('');

// ---- force-directed layout
const cv=document.getElementById('c'), ctx=cv.getContext('2d');
let W,H,DPR=devicePixelRatio||1;
function size(){const r=cv.parentElement.getBoundingClientRect();
 W=r.width;H=Math.max(r.height,560);cv.width=W*DPR;cv.height=H*DPR;
 cv.style.height=H+'px';ctx.setTransform(DPR,0,0,DPR,0,0);}
size();addEventListener('resize',()=>{size();});

const idx={}, N=D.nodes.map((n,i)=>{idx[n.id]=i;
 return {...n,x:W/2+(Math.random()-.5)*260,y:H/2+(Math.random()-.5)*260,vx:0,vy:0,deg:0}});
const E=D.edges.filter(e=>idx[e.from]!=null&&idx[e.to]!=null)
 .map(e=>({s:idx[e.from],t:idx[e.to],type:e.type}));
E.forEach(e=>{N[e.s].deg++;N[e.t].deg++});
const R=n=>6+Math.min(n.deg,6)*1.2+Math.min((n.docs||[]).length,8)*0.9;

let sel=null,drag=null,ox=0,oy=0;

// each node occupies a LABEL BOX, not a point — overlapping text is the thing
// that makes these graphs unreadable, so collision is resolved on the box.
ctx.font='11px -apple-system,system-ui,sans-serif';
N.forEach(n=>{
  n.short = n.title.length>24 ? n.title.slice(0,23)+'…' : n.title;
  n.bw = Math.max(ctx.measureText(n.short).width, R(n)*2) + 16;
  n.bh = R(n)*2 + 20;
});

function step(){
  // long-range repulsion, scaled by how big each node's footprint is
  for(let i=0;i<N.length;i++)for(let j=i+1;j<N.length;j++){
    const a=N[i],b=N[j];let dx=b.x-a.x,dy=b.y-a.y,d2=dx*dx+dy*dy||1;
    if(d2>250000)continue;
    const f=(2600+(a.bw+b.bw)*7)/d2, d=Math.sqrt(d2);
    const fx=dx/d*f,fy=dy/d*f;a.vx-=fx;a.vy-=fy;b.vx+=fx;b.vy+=fy;}
  // springs, longer than before so clusters breathe
  E.forEach(e=>{const a=N[e.s],b=N[e.t];
    let dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-165)*.010;
    const fx=dx/d*f,fy=dy/d*f;a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;});
  // very weak centering — enough to stop drift, not enough to bunch
  N.forEach(n=>{n.vx+=(W/2-n.x)*.0011;n.vy+=(H/2-n.y)*.0011;
    n.vx*=.85;n.vy*=.85;
    if(n!==drag){n.x+=n.vx;n.y+=n.vy;}});
  separate();
  N.forEach(n=>{n.x=Math.max(n.bw/2+6,Math.min(W-n.bw/2-6,n.x));
                n.y=Math.max(18,Math.min(H-22,n.y));});
}

// hard box separation — run a few relaxation passes so labels never overlap
function separate(){
  for(let pass=0;pass<3;pass++){
    for(let i=0;i<N.length;i++)for(let j=i+1;j<N.length;j++){
      const a=N[i],b=N[j];
      const mx=(a.bw+b.bw)/2+10, my=(a.bh+b.bh)/2+6;
      const dx=b.x-a.x, dy=b.y-a.y;
      const ox2=mx-Math.abs(dx), oy2=my-Math.abs(dy);
      if(ox2>0&&oy2>0){
        if(ox2<oy2){const s=(dx<0?-1:1)*ox2/2;
          if(a!==drag)a.x-=s; if(b!==drag)b.x+=s;}
        else{const s=(dy<0?-1:1)*oy2/2;
          if(a!==drag)a.y-=s; if(b!==drag)b.y+=s;}
      }}}
}
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim()}
function draw(){
  ctx.clearRect(0,0,W,H);
  const rule=css('--rule'),ink=css('--ink'),mut=css('--mut');
  E.forEach(e=>{const a=N[e.s],b=N[e.t];
    const hot=sel!=null&&(e.s===sel||e.t===sel);
    ctx.strokeStyle=hot?css('--acc'):rule;ctx.lineWidth=hot?1.6:1;
    ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();});
  N.forEach((n,i)=>{
    const r=R(n),act=sel===i;
    ctx.beginPath();ctx.arc(n.x,n.y,r,0,7);ctx.fillStyle=n.color;
    ctx.globalAlpha=sel==null||act||E.some(e=>(e.s===sel&&e.t===i)||(e.t===sel&&e.s===i))?1:.28;
    ctx.fill();
    if(n.stale){ctx.strokeStyle=css('--crit');ctx.lineWidth=2;ctx.stroke();}
    if(act){ctx.strokeStyle=ink;ctx.lineWidth=2;ctx.stroke();}
    ctx.font=(act?'600 ':'')+'11px -apple-system,system-ui,sans-serif';
    ctx.textAlign='center';
    // halo so a label crossing an edge stays legible
    ctx.lineWidth=3; ctx.strokeStyle=css('--surface');
    ctx.strokeText(n.short,n.x,n.y+r+13);
    ctx.fillStyle=act?ink:mut;
    ctx.fillText(n.short,n.x,n.y+r+13);
    ctx.globalAlpha=1;});
}
let frames=0;
for(let i=0;i<420;i++)step();
(function loop(){if(frames++<600||drag)step();draw();requestAnimationFrame(loop)})();

function pick(x,y){for(let i=N.length-1;i>=0;i--){const n=N[i];
  if(Math.hypot(n.x-x,n.y-y)<R(n)+7)return i}return null}
function at(ev){const r=cv.getBoundingClientRect();return[ev.clientX-r.left,ev.clientY-r.top]}
cv.addEventListener('mousedown',ev=>{const[x,y]=at(ev),i=pick(x,y);
  if(i!=null){drag=N[i];ox=x-drag.x;oy=y-drag.y;show(i)}});
addEventListener('mousemove',ev=>{if(!drag)return;const[x,y]=at(ev);
  drag.x=x-ox;drag.y=y-oy;frames=0});
addEventListener('mouseup',()=>drag=null);

function show(i){
  sel=i;const n=N[i];
  const outs=E.filter(e=>e.s===i).map(e=>[e.type,N[e.t].title,'→']);
  const ins=E.filter(e=>e.t===i).map(e=>[e.type,N[e.s].title,'←']);
  const rels=[...outs,...ins];
  const docs = n.docs || [];
  const byRel = {};
  docs.forEach(d => (byRel[d.relation] = byRel[d.relation] || []).push(d));
  document.getElementById('detail').innerHTML =
    `<div class="nt">${esc(n.title)}${n.stale?'<span class="pill stale">stale</span>':''}</div>
     <div class="meta">${n.type} · ${n.status||'—'} · confidence ${n.confidence||'—'}<br>
     updated ${n.updated||'—'} · review by ${n.review_by||'never set'}<br>${esc(n.path)}</div>
     ${n.excerpt?`<div class="ex">${esc(n.excerpt)}…</div>`:''}
     <h2 style="margin-top:18px">Connections (${rels.length})</h2>
     ${rels.length?rels.map(([t,ti,d])=>`<div class="rel">${d} <b>${esc(t)}</b> ${esc(ti)}</div>`).join('')
      :'<div class="hint">None. Entities with no connections are rarely retrieved.</div>'}
     <h2 style="margin-top:18px">What's written about it (${docs.length})</h2>
     ${docs.length?Object.entries(byRel).map(([rel,ds])=>
        `<div class="rel" style="margin-top:8px"><b>${esc(rel)}</b></div>` +
        ds.map(d=>`<div class="doc"><span class="dt">${esc(d.type)}</span>
           ${esc(d.title)}${d.stale?' <span class="pill stale">stale</span>':''}
           <div class="dx">${esc(d.excerpt)}…</div></div>`).join('')).join('')
      :'<div class="hint">Nothing written about this yet — the graph knows it exists, the wiki knows nothing.</div>'}`;
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
</script></body></html>"""


# ---------------------------------------------------------------- missing

def cmd_missing():
    """Gaps: what the brain should know and doesn't. Mechanical checks only —
    the skill layers judgement on top (people named in sessions, etc.)."""
    nodes = load_nodes()
    if not nodes:
        print(f"No brain found at {BRAIN}.")
        return 1
    a = analyse(nodes)
    by = {}
    for n in nodes:
        by.setdefault(n.get("type"), []).append(n)
    ids = {n["id"] for n in nodes}
    out_edges = {n["id"]: [e for e in n.get("edges", []) if e.get("to") in ids] for n in nodes}

    def has(node, *etypes):
        return any(e.get("type") in etypes for e in out_edges.get(node["id"], []))

    # documents reach the graph through `about:` — never through edges
    written = {}
    for d in a["docs"]:
        for ref in d.get("about", []):
            written.setdefault(ref["entity"], []).append(d)
    task_types = {n["id"] for n in by.get("task_type", [])}
    # a project is just a task with children
    parents = {e["to"] for n in by.get("task", []) for e in out_edges[n["id"]]
               if e.get("type") == "part_of"}
    projects = [n for n in by.get("task", []) if n["id"] in parents]

    gaps = []

    # decisions with no rejected alternative recorded
    for n in by.get("decision", []):
        if "**Rejected" not in n["_body"] and not n.get("rejected_in_favour_of"):
            gaps.append(("decision has no rejected alternative", n["_path"],
                         "the most valuable half of a decision is what lost"))
    # task types with no playbook
    for n in by.get("task_type", []):
        if not any(d.get("type") == "playbook" for d in written.get(n["id"], [])):
            gaps.append(("task type has no playbook", n["_path"],
                         "recurring work with no written procedure"))
    # playbooks not about any task type
    for n in by.get("playbook", []):
        if not any(ref["entity"] in task_types for ref in n.get("about", [])):
            gaps.append(("playbook attached to no task type", n["_path"],
                         "will never be pulled in automatically"))
    # documents with no graph anchor
    for n in a["unanchored"]:
        gaps.append(("document has no graph anchor", n["_path"],
                     "no `about:` — only findable by search, not by walking from an entity"))
    # entities carrying no knowledge at all
    project_ids = {n["id"] for n in projects}
    for n in by.get("person", []) + by.get("task_type", []) + projects:
        if not a["doc_count"].get(n["id"]):
            kind = "project" if n["id"] in project_ids else n.get("type")
            gaps.append((f"{kind} has no documents", n["_path"],
                         "nothing is known about it beyond its own node"))
    # global preferences that may want scoping
    for n in by.get("preference", []):
        if is_global_preference(n):
            gaps.append(("preference is global", n["_path"],
                         "fires on every session — is that right?"))
    # projects with no owner
    for n in projects:
        if not has(n, "owned_by", "created_by"):
            gaps.append(("project has no owner", n["_path"], "no accountable person"))
    # risks past review
    for n in by.get("risk", []):
        d = as_date(n.get("review_by"))
        if d and d < TODAY:
            gaps.append(("risk past its review date", n["_path"],
                         f"due {n.get('review_by')} — resolve or re-date"))
    # people with no org
    for n in by.get("person", []):
        if not has(n, "works_at"):
            gaps.append(("person has no org", n["_path"], "can't answer 'who at X'"))
    # empty categories that the model expects
    for t, why in [("person", "no colleagues — drafts stay aimed at a generic reader"),
                   ("task_type", "no recurring work defined — nothing compounds"),
                   ("skill", "no skills mapped")]:
        if not by.get(t):
            gaps.append((f"no {t} nodes at all", "—", why))

    print(f"\n  MISSING INFORMATION · {BRAIN} · {TODAY}")
    print("  " + "-" * 62)
    if not gaps:
        print("  ✓ No structural gaps found.\n")
        return 0
    for what, where, why in gaps:
        print(f"  · {what}")
        print(f"      {where}")
        print(f"      {why}")
    print(f"\n  {len(gaps)} gap(s).\n")
    return 0


# ---------------------------------------------------------------- todo

def cmd_todo():
    nodes = load_nodes()
    open_tasks = [n for n in nodes if n.get("type") == "task"
                  and n.get("status") not in ("done",) + INACTIVE]
    live_risks = [n for n in nodes if n.get("type") == "risk" and n.get("status") == "active"]

    print(f"\n  TO DO · {TODAY}")
    print("  " + "-" * 62)
    for name, label in (("owed", "YOU OWE"), ("waiting-on", "WAITING ON")):
        commitments, rows = open_commitments(nodes, name), loop_rows(name)
        print(f"\n  {label}")
        for c in commitments:
            print("    " + commitment_line(c))
        for r in rows:
            print("    " + r)
        if not commitments and not rows:
            print("    (empty — the morning brief has nothing to show here)")
    if open_tasks:
        print("\n  OPEN TASKS")
        for n in open_tasks:
            print(f"    {n.get('title','?')}  [{n.get('status','?')}]"
                  f"{'  due ' + n['due'] if n.get('due') else ''}")
    if live_risks:
        print("\n  LIVE RISKS")
        for n in sorted(live_risks, key=lambda n: n.get("review_by", "")):
            d = as_date(n.get("review_by"))
            flag = "  ← PAST DUE" if d and d < TODAY else ""
            print(f"    {n.get('title','?')}  (review {n.get('review_by','—')}){flag}")
    print()
    return 0


# ---------------------------------------------------------------- connectors

def cmd_connectors():
    """Compare the connectors the skill just enumerated against ones already
    offered, so the daily check only ever surfaces genuinely new ones.
    Usage: brain.py connectors --seen slack,gmail,calendar"""
    store = BRAIN / "_index" / "connectors.json"
    store.parent.mkdir(exist_ok=True)
    known = json.loads(store.read_text()) if store.exists() else {"offered": []}

    seen = []
    if "--seen" in sys.argv:
        i = sys.argv.index("--seen")
        if i + 1 < len(sys.argv):
            seen = [s.strip() for s in sys.argv[i + 1].split(",") if s.strip()]

    new = [s for s in seen if s not in known["offered"]]
    if "--record" in sys.argv and seen:
        known["offered"] = sorted(set(known["offered"]) | set(seen))
        known["last_checked"] = str(TODAY)
        store.write_text(json.dumps(known, indent=2))
        print(f"Recorded {len(seen)} connector(s).")
        return 0

    print(json.dumps({
        "new": new,
        "already_offered": known["offered"],
        "last_checked": known.get("last_checked", "never"),
    }, indent=2))
    return 0


# ---------------------------------------------------------------- review

def inbox_items():
    """Proposals waiting for review, oldest first: (path, meta, body)."""
    box = BRAIN / "inbox"
    items = []
    for p in (sorted(box.glob("*.md")) if box.is_dir() else []):
        meta, body = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        items.append((p, meta, body))
    return items


def inbox_file(name):
    """A proposal by file name. Only a bare name inside inbox/ resolves, so a
    caller can never reach outside it."""
    name = Path(str(name)).name
    if name and not name.endswith(".md"):
        name += ".md"
    p = BRAIN / "inbox" / name
    if not name or not p.is_file():
        raise ValueError(f"No proposal named {name or '(empty)'} in inbox/.")
    return p


def _split(text):
    """Frontmatter lines and body, verbatim — approval files a proposal, it
    doesn't re-render it through a parser that only knows a subset of YAML."""
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if not lines or lines[0].strip() != "---" or end is None:
        raise ValueError("Proposal has no frontmatter.")
    return lines[1:end], "\n".join(lines[end + 1:]).strip()


def _set_field(fm, key, value):
    """Set a top-level scalar in frontmatter lines, or append it."""
    for i, line in enumerate(fm):
        if line[:1] not in ("", " ", "\t", "#") and line.partition(":")[0].strip() == key:
            fm[i] = f"{key}: {value}"
            return
    fm.append(f"{key}: {value}")


def _add_edge(path, etype, target):
    """Append one edge to an entity file's `edges:` block, creating the block if
    there is none. False if the edge is already there."""
    text = path.read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(text)
    if any(e.get("type") == etype and e.get("to") == target for e in meta.get("edges", [])):
        return False
    lines = text.splitlines()
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    new = [f"  - type: {etype}", f"    to: {target}"]
    for i in range(1, end):
        if lines[i][:1] not in ("", " ", "\t") and lines[i].partition(":")[0].strip() == "edges":
            lines[i] = "edges:"                        # `edges: []` becomes a block
            j = i + 1
            while j < end and (not lines[j].strip() or lines[j][:1] in (" ", "\t")):
                j += 1
            lines[j:j] = new
            break
    else:
        lines[end:end] = ["edges:"] + new
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def approve(name, content=None):
    """File a proposal into the brain. `content`, if given, replaces the body
    verbatim — the user's wording of their own preferences beats yours."""
    src = inbox_file(name)
    text = src.read_text(encoding="utf-8", errors="replace")
    meta, _ = parse_frontmatter(text)
    fm, body = _split(text)
    kind, nid = meta.get("type"), meta.get("id")
    if not nid:
        raise ValueError(f"{src.name} has no `id:` — it would be invisible once filed.")
    if kind != "profile" and kind not in FOLDER:
        raise ValueError(f"{src.name} has type {kind!r}, which isn't in the model. "
                         f"Use one of: profile, {', '.join(sorted(FOLDER))}.")
    nodes = load_nodes()
    known = {n["id"]: n for n in nodes}
    if nid in known:
        raise ValueError(f"`{nid}` already exists at {known[nid]['_path']}. Merge the "
                         f"proposal into it by hand, or change its id, then approve again.")
    if kind == "profile":
        dest = BRAIN / "graph" / "profile.md"
        if dest.exists():
            raise ValueError("graph/profile.md already exists. Merge the proposal into it by hand.")
    else:
        slug = nid[len(kind) + 1:] if nid.startswith(kind + "-") else nid
        dest, k = BRAIN / FOLDER[kind] / f"{slug}.md", 2
        while dest.exists():
            dest, k = BRAIN / FOLDER[kind] / f"{slug}-{k}.md", k + 1

    notes = []
    if content is not None and str(content).strip():
        body = str(content).strip()
        _set_field(fm, "updated", str(TODAY))
        notes.append("body replaced with the user's wording")
    if not as_date(meta.get("review_by")):
        rv = add_months(TODAY, 6)
        _set_field(fm, "review_by", str(rv))
        notes.append(f"had no review_by — set to {rv}")
    for ref in meta.get("about", []):
        tgt = known.get(ref["entity"])
        if not tgt:
            notes.append(f"about → {ref['entity']} doesn't exist yet — health will flag it")
        elif not is_entity(tgt):
            notes.append(f"about → {ref['entity']} is a document; `about:` must name an entity")
    if kind in ENTITY_TYPES and meta.get("about"):
        notes.append("entities link through `edges:`; its `about:` is ignored")
    if kind not in ENTITY_TYPES and meta.get("edges"):
        notes.append("documents link through `about:`; its `edges:` are ignored — move them")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + body + "\n", encoding="utf-8")
    src.unlink()

    # the reciprocal half of any edge that has one, so walking works from both ends
    if kind in ENTITY_TYPES:
        for e in meta.get("edges", []):
            tgt = known.get(e.get("to"))
            if not tgt:
                notes.append(f"edge → {e.get('to')} doesn't exist yet — health will flag it")
                continue
            inv = INVERSE.get(e.get("type"))
            if inv and is_entity(tgt) and _add_edge(BRAIN / tgt["_path"], inv, nid):
                notes.append(f"added {tgt['id']} --{inv}--> {nid}")

    msg = f"Approved → {dest.relative_to(BRAIN)}"
    return msg + "".join(f"\n  · {n}" for n in notes)


def reject(name):
    p = inbox_file(name)
    meta, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
    p.unlink()
    return f"Rejected — deleted {p.name} ({meta.get('title') or 'untitled'})."


def cmd_inbox():
    items = inbox_items()
    print(f"\n  INBOX · {len(items)} proposal(s) waiting")
    print("  " + "-" * 62)
    if not items:
        print("  Nothing to review.\n")
        return 0
    for kind in sorted({m.get("type") or "?" for _, m, _ in items}):
        print(f"\n  {kind.upper()}")
        for p, m, _ in items:
            if (m.get("type") or "?") != kind:
                continue
            refs = [a["entity"] for a in m.get("about", [])] + [e["to"] for e in m.get("edges", [])]
            print(f"    {p.name}")
            print(f"        {m.get('title') or '(untitled)'} · {m.get('confidence') or '?'} "
                  f"confidence · {m.get('provenance') or 'no source'}")
            if refs:
                print(f"        → {', '.join(refs)}")
    print("\n  Approve:  brain.py approve <file>     Reject:  brain.py reject <file>\n")
    return 0


def cmd_approve():
    if len(sys.argv) < 3:
        print("usage: brain.py approve <inbox file>")
        return 1
    try:
        print(approve(sys.argv[2]))
    except ValueError as e:
        print(e)
        return 1
    return 0


def cmd_reject():
    if len(sys.argv) < 3:
        print("usage: brain.py reject <inbox file>")
        return 1
    try:
        print(reject(sys.argv[2]))
    except ValueError as e:
        print(e)
        return 1
    return 0


# ---------------------------------------------------------------- codex export

START = "<!-- keel:start — generated, do not edit by hand -->"
END = "<!-- keel:end -->"

CODEX_GUIDE = """
## Keel — the user's brain

A knowledge base at `{brain}` holds the user's preferences, decisions,
constraints, people and open loops. Their profile and global preferences are
inlined below — they are already loaded, don't re-read those files.

**If the `keel` MCP server is connected, use it:** `keel_recall` before
substantive work, `keel_remember` to capture. Otherwise work the files.

**Before substantive work**, pull what's relevant in two steps. First anchor in
the graph — which entities does this session touch? A task, a person, a kind of
work, the repo you're in. Read those files and follow their `edges:` one hop:

```
rg -l -i "<anchor>" {brain}/graph
```

Then pull the documents written about those entities:

```
rg -l "entity: <entity-id>" {brain}/wiki
```

Read constraints and scoped preferences first, then decisions, then the rest.
Skip `status: superseded` and `archived`. Budget a few thousand tokens; drop
whole documents by rank, never truncate one. Say what you loaded, so the user
can spot the brain feeding you something wrong.

**When something worth keeping appears** — a decision with its rejected
alternative, a constraint, a scoped preference, a risk with a review date, a
commitment with a date — write it to `{brain}/inbox/YYYY-MM-DD-<slug>.md`.
**Never write directly into the brain.** A memory that is 80% right is worse
than none, because it degrades every later output invisibly. The inbox is the
review gate.

Copy frontmatter from `{brain}/_templates/` rather than writing it from memory.
`review_by` is mandatory on every node.

**Useful commands:**

```
python3 {script} health    # fed? true? retrievable?
python3 {script} missing   # structural gaps
python3 {script} todo      # open loops, commitments, live risks
python3 {script} inbox     # proposals waiting for review
```

`{brain}/_index/brain.html` maps the user's private context including people
and commitments — never publish or upload it.
"""


def cmd_export_codex():
    """Write ~/.codex/AGENTS.md so the same brain works in Codex.

    Codex has no session-start hook, so its always-loaded file IS the hook:
    the profile and global preferences are inlined. Re-run whenever those change.
    """
    brain = BRAIN
    if not brain.is_dir():
        print(f"No brain at {brain}.")
        return 1

    chunks = []
    for p in hook_sources():
        try:
            t = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if t:
            chunks.append((p, f"### {p.relative_to(brain)}\n\n{t}"))
    if not chunks:
        print("Nothing to export — no profile or global preferences.")
        return 1

    script = pathlib_str(__file__)
    guide = CODEX_GUIDE.replace("{brain}", pathlib_str(brain)).replace("{script}", script)
    block = (f"{START}\n"
             f"<!-- regenerate: python3 {script} export-codex -->\n"
             f"{guide}\n"
             f"### Loaded automatically\n\n"
             f"Treat the following as how the user wants to be worked with, not as "
             f"background reading.\n\n"
             + "\n\n".join(c for _, c in chunks)
             + f"\n\n<!-- exported {TODAY} -->\n{END}")

    out = pathlib.Path.home() / ".codex" / "AGENTS.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    if out.exists():
        cur = out.read_text(encoding="utf-8")
        if START in cur and END in cur:
            head, _, rest = cur.partition(START)
            _, _, tail = rest.partition(END)
            new = head + block + tail
            action = "updated managed block in"
        else:
            new = cur.rstrip() + "\n\n" + block + "\n"
            action = "appended managed block to"
    else:
        new = block + "\n"
        action = "created"

    out.write_text(new, encoding="utf-8")

    stamp = brain / "_index" / "codex_export.json"
    stamp.parent.mkdir(exist_ok=True)
    stamp.write_text(json.dumps({"exported": str(TODAY), "target": str(out),
                                 "files": [str(p.relative_to(brain)) for p, _ in chunks]}, indent=2))

    profile = any(p == brain / "graph" / "profile.md" for p, _ in chunks)
    prefs = len(chunks) - profile
    print(f"{action} {out}")
    print(f"  {len(block)} chars — {'profile + ' if profile else 'no profile, '}"
          f"{prefs} global preference file(s)")
    print("  Re-run after changing profile.md or a global preference.")
    return 0


def pathlib_str(p):
    return str(pathlib.Path(p).resolve()).replace(str(pathlib.Path.home()), "~")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "health"
    fns = {
        "health": cmd_health,
        "missing": cmd_missing,
        "todo": cmd_todo,
        "inbox": cmd_inbox,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "connectors": cmd_connectors,
        "export-codex": cmd_export_codex,
    }
    if cmd == "view":
        sys.exit(cmd_view(auto_open="--no-open" not in sys.argv))
    elif cmd in fns:
        sys.exit(fns[cmd]())
    else:
        print(__doc__)
        sys.exit(1)
