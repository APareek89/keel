#!/usr/bin/env python3
"""
Keel brain tools.

    brain.py health          text report: staleness, orphans, capture rate, breakages
    brain.py view [--no-open] writes an HTML overview + knowledge graph and opens it

Reads ~/brain (override with BRAIN_DIR). Standard library only — no pip install,
no external assets, so the HTML works offline and nothing leaves the machine.
"""

import os
import sys
import json
import html
import subprocess
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


def is_entity(n):
    return n.get("type") in ENTITY_TYPES


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
        # a global preference (no applies_to) is loaded by the hook every session,
        # never retrieved by walking — it is correctly unanchored, not a gap.
        always_loaded = d.get("type") == "preference" and not any(
            a.get("relation") == "applies_to" for a in d.get("about", []))
        if not refs and not always_loaded:
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
    hook_src = [BRAIN / "graph" / "profile.md"] + list((BRAIN / "wiki" / "preferences").glob("*.md"))
    if not any(s.exists() for s in hook_src):
        problems.append("SessionStart hook has nothing to load — paths moved?")
        print("\n  ! The hook finds no profile or preferences. It is silently loading")
        print("    nothing into every session. Expected graph/profile.md and")
        print("    wiki/preferences/*.md")

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
            exported = as_date(json.loads(stamp.read_text()).get("exported"))
        except (ValueError, OSError):
            exported = None
        srcs = [BRAIN / "graph" / "profile.md"] + list((BRAIN / "wiki" / "preferences").glob("*.md"))
        newest = max((as_date(parse_frontmatter(s.read_text())[0].get("updated"))
                      for s in srcs if s.exists()), default=None)
        if exported and newest and newest > exported:
            problems.append("Codex export is stale — re-run export-codex")
            print(f"    ! Codex export is from {exported} but preferences changed "
                  f"{newest}. Codex is running on old preferences:")
            print("        python3 ~/.claude/skills/keel/scripts/brain.py export-codex")

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
    for name in ("owed", "waiting-on"):
        f = BRAIN / "loops" / f"{name}.md"
        if not f.exists():
            print(f"    ! loops/{name}.md missing.")
            continue
        rows = [l for l in f.read_text().splitlines()
                if l.strip().startswith("|") and "---" not in l
                and "_(empty" not in l and not l.strip().startswith("| Owed")
                and not l.strip().startswith("| Waiting")]
        if rows:
            print(f"    ✓ {name}: {len(rows)} item(s).")
        else:
            problems.append(f"loops/{name}.md is empty")
            print(f"    ! {name}: empty — this block of the brief will be blank.")

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
    if auto_open:
        try:
            subprocess.run(["open", str(target)], check=False)
        except Exception:
            pass
    return 0


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
    out_edges = {}
    for n in nodes:
        out_edges[n["id"]] = [e for e in n.get("edges", []) if e.get("to") in ids]

    gaps = []

    def has(node, etype):
        return any(e.get("type") == etype for e in out_edges.get(node["id"], []))

    # decisions with no rejected alternative recorded
    for n in by.get("decision", []):
        if "**Rejected" not in n["_body"] and not has(n, "rejected_in_favour_of"):
            gaps.append(("decision has no rejected alternative", n["_path"],
                         "the most valuable half of a decision is what lost"))
    # task types with no playbook
    for n in by.get("task_type", []):
        if not has(n, "documented_by"):
            gaps.append(("task type has no playbook", n["_path"],
                         "recurring work with no written procedure"))
    # playbooks not reachable from a task type
    tt_targets = {e["to"] for n in by.get("task_type", []) for e in out_edges.get(n["id"], [])}
    for n in by.get("playbook", []):
        if n["id"] not in tt_targets:
            gaps.append(("playbook attached to no task type", n["_path"],
                         "will never be pulled in automatically"))
    # documents with no graph anchor
    for n in a["unanchored"]:
        gaps.append(("document has no graph anchor", n["_path"],
                     "no `about:` — only findable by search, not by walking from an entity"))
    # entities carrying no knowledge at all
    for n in a["entities"]:
        if n.get("type") in ("person", "project", "task_type") and not a["doc_count"].get(n["id"]):
            gaps.append((f"{n.get('type')} has no documents", n["_path"],
                         "nothing is known about it beyond its own node"))
    # global preferences that may want scoping
    for n in by.get("preference", []):
        if not has(n, "applies_to"):
            gaps.append(("preference is global", n["_path"],
                         "fires on every session — is that right?"))
    # projects with no owner
    for n in by.get("project", []):
        if not has(n, "owned_by"):
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
    rows = []
    for name, label in (("owed", "YOU OWE"), ("waiting-on", "WAITING ON")):
        f = BRAIN / "loops" / f"{name}.md"
        if not f.exists():
            continue
        body = [l for l in f.read_text().splitlines()
                if l.strip().startswith("|") and "---" not in l
                and "_(empty" not in l and "| Owed to" not in l and "| Waiting on" not in l]
        rows.append((label, body))

    open_tasks = [n for n in nodes if n.get("type") == "task"
                  and n.get("status") not in ("done", "archived")]
    live_risks = [n for n in nodes if n.get("type") == "risk" and n.get("status") == "active"]

    print(f"\n  TO DO · {TODAY}")
    print("  " + "-" * 62)
    for label, body in rows:
        print(f"\n  {label}")
        if body:
            for b in body:
                print("    " + b.strip())
        else:
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


# ---------------------------------------------------------------- codex export

START = "<!-- keel:start — generated, do not edit by hand -->"
END = "<!-- keel:end -->"

CODEX_GUIDE = """
## Keel — the user's brain

A knowledge base at `~/brain` holds his preferences, decisions, constraints,
people and open loops. His profile and standing preferences are inlined below —
they are already loaded, don't re-read those files.

**Before substantive work**, pull what's relevant. Find anchors — a project,
person, task type, or the repo you're in — then read those files and follow
their `edges:` one hop:

```
rg -l -i "<anchor>" ~/brain --glob '!journal/*' --glob '!inbox/*' --glob '!_templates/*'
```

Always include anything in `~/brain/constraints/` — standing rules, violated
silently, are expensive. Skip nodes with `status: superseded` or `archived`.
Budget a few thousand tokens; cut by graph distance, never by truncating a file.
Say what you loaded, so he can spot the brain feeding you something wrong.

**When something worth keeping appears** — a decision with its rejected
alternative, a constraint, a scoped preference, a risk with a review date, a
commitment with a date — write it to `~/brain/inbox/YYYY-MM-DD-<slug>.md`.
**Never write directly into the brain.** A memory that is 80% right is worse
than none, because it degrades every later output invisibly. The inbox is the
review gate.

Copy frontmatter from `~/brain/_templates/` rather than writing it from memory.
`review_by` is mandatory on every node.

**Useful commands:**

```
python3 ~/.claude/skills/keel/scripts/brain.py health    # fed? true? retrievable?
python3 ~/.claude/skills/keel/scripts/brain.py missing   # structural gaps
python3 ~/.claude/skills/keel/scripts/brain.py todo      # open loops, live risks
```

`~/brain/_index/brain.html` maps his private context including people and
commitments — never publish or upload it.
"""


def cmd_export_codex():
    """Write ~/.codex/AGENTS.md so the same brain works in Codex.

    Codex has no session-start hook, so its always-loaded file IS the hook:
    profile and preferences are inlined. Re-run whenever those change.
    """
    brain = BRAIN
    if not brain.is_dir():
        print(f"No brain at {brain}.")
        return 1

    paths = [brain / "graph" / "profile.md"] + sorted((brain / "wiki" / "preferences").glob("*.md"))
    chunks = []
    for p in paths:
        try:
            t = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if t:
            chunks.append(f"### {p.relative_to(brain)}\n\n{t}")
    if not chunks:
        print("Nothing to export — no profile or preferences.")
        return 1

    block = (f"{START}\n"
             f"<!-- regenerate: python3 {pathlib_str(__file__)} export-codex -->\n"
             f"{CODEX_GUIDE}\n"
             f"### Loaded automatically\n\n"
             f"Treat the following as how he wants to be worked with, not as "
             f"background reading.\n\n"
             + "\n\n".join(chunks)
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
                                 "files": [str(p.relative_to(brain)) for p in paths]}, indent=2))

    print(f"{action} {out}")
    print(f"  {len(block)} chars — profile + {len(chunks)-1} preference file(s)")
    print("  Re-run after changing profile.md or anything in preferences/.")
    return 0


def pathlib_str(p):
    return str(pathlib.Path(p).resolve()).replace(str(pathlib.Path.home()), "~")


import pathlib  # noqa: E402  (used by the export helpers above)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "health"
    fns = {
        "health": cmd_health,
        "missing": cmd_missing,
        "todo": cmd_todo,
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
