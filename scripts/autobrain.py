#!/usr/bin/env python3
"""Keel automatic capture pass.

    autobrain.py scan              activity table: what you worked on, how long, is it in the brain
    autobrain.py promote           what would be promoted/refreshed (dry run)
    autobrain.py promote --apply   write it
    autobrain.py session-start     hook payload: profile + preferences + live topics

Reads Claude Code and Codex transcripts from disk. Standard library only.
Topics are DERIVED from the graph and inbox, plus discovered n-grams, so a
project nobody registered still shows up. Nothing leaves the machine.
"""
import json, os, re, sys, glob, argparse, collections, contextlib, fcntl, time
import datetime as dt
from pathlib import Path

BRAIN = Path(os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain")))
STATE = BRAIN / "_index" / "autobrain.json"
LIVE  = BRAIN / "_index" / "live.json"      # cached topic table
TCACHE = BRAIN / "_index" / "transcripts.json"   # parsed sessions, keyed by mtime+size
LOCK  = BRAIN / "_index" / "brain.lock"
LIVE_TTL_HOURS = 12

# Promotion thresholds: repetition AND time must both clear.
MIN_DAYS, MIN_SESSIONS, MIN_HOURS = 3, 3, 2.0
MIN_CAPTURES = 3           # independent captures before a document self-approves
GAP_CAP_MIN = 5.0          # inter-event gap counted as active work
STOP = set("""the and for with that this from have has was were will would you your not but
are its it's about into what when which who how why all any can could should just like get
make made use used using need needs want file files code project work working now then than
one two new old more most some only also very much many take takes let lets please thanks""".split())

RE_SR  = re.compile(r"<system-reminder>.*?</system-reminder>", re.S | re.I)
RE_CMD = re.compile(r"<command-(message|name|args)>.*?</command-\1>", re.S | re.I)
RE_FM  = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
RE_WORD = re.compile(r"[a-z][a-z0-9\-]{2,}")


# Blocks that arrive as "user" turns but are machine-injected, not typed.
INJECTED = ("base directory for this skill:", "caveat: the messages below",
            "<local-command-stdout>", "<command-name>", "# files pasted by the user:",
            "<user-prompt-submit-hook>", "result of calling the", "# environment",
            "<system-reminder>", "this session is being continued from")


def is_human(t):
    """A typed prompt, not an injection, a paste, or tool output."""
    ls = t.strip().lower()
    if not ls or len(t) > 3000:          # long blocks are pastes/injections
        return False
    return not any(ls.startswith(m) or m in ls[:400] for m in INJECTED)


@contextlib.contextmanager
def brain_lock(timeout=20):
    """Serialise writes across the nightly pass, session hooks and the MCP server.
    Without this, a capture landing mid-rewrite is silently lost."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK, "w")
    waited = 0.0
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except OSError:
            time.sleep(0.2); waited += 0.2
            if waited >= timeout:
                fh.close(); raise TimeoutError("brain locked by another process")
    try:
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()


def clean(t):
    """Strip injected context so we measure what the user actually said."""
    return RE_CMD.sub(" ", RE_SR.sub(" ", t)).lower()


def pts(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def active_minutes(ts):
    ts = sorted(ts); tot = 0.0
    for a, b in zip(ts, ts[1:]):
        g = (b - a).total_seconds() / 60
        if g > 0:
            tot += min(g, GAP_CAP_MIN)
    return tot


# ---------------------------------------------------------------- transcripts
def _cache_load():
    try:
        return json.loads(TCACHE.read_text())
    except Exception:
        return {}


def _cache_save(c):
    try:
        TCACHE.parent.mkdir(parents=True, exist_ok=True)
        TCACHE.write_text(json.dumps(c))
    except OSError:
        pass


def read_sessions(since_days=45, use_cache=True):
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)
    cache = _cache_load() if use_cache else {}
    fresh, out = {}, []

    def cached(p):
        try:
            st = os.stat(p)
        except OSError:
            return None, None
        key = f"{p}:{int(st.st_mtime)}:{st.st_size}"
        hit = cache.get(key)
        return key, hit

    def keep(key, rec):
        if key:
            fresh[key] = rec
        if rec and rec["end"] >= cutoff.isoformat():
            out.append({"client": rec["client"],
                        "start": dt.datetime.fromisoformat(rec["start"]),
                        "end": dt.datetime.fromisoformat(rec["end"]),
                        "mins": rec["mins"], "text": rec["text"]})
    _out_marker = None
    for p in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        key, hit = cached(p)
        if hit is not None:
            keep(key, hit); continue
        ts, tx = [], []
        try:
            for line in open(p, errors="ignore"):
                try: d = json.loads(line)
                except Exception: continue
                if d.get("isSidechain"):      # subagents aren't the user working
                    continue
                t = pts(d.get("timestamp"))
                if t: ts.append(t)
                if d.get("type") == "user":
                    c = (d.get("message") or {}).get("content")
                    if isinstance(c, list):
                        tx += [b["text"] for b in c
                               if isinstance(b, dict) and b.get("type") == "text"
                               and is_human(b["text"])]
                    elif isinstance(c, str) and is_human(c):
                        tx.append(c)
        except OSError:
            continue
        rec = ({"client": "claude", "start": min(ts).isoformat(), "end": max(ts).isoformat(),
                "mins": active_minutes(ts), "text": clean(" ".join(dict.fromkeys(tx)))}
               if ts else None)
        keep(key, rec)
    for p in glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/*.jsonl")):
        key, hit = cached(p)
        if hit is not None:
            keep(key, hit); continue
        ts, tx = [], []
        try:
            for line in open(p, errors="ignore"):
                try: d = json.loads(line)
                except Exception: continue
                pl = d.get("payload") or {}
                t = pts(d.get("timestamp") or pl.get("timestamp"))
                if t: ts.append(t)
                if pl.get("role") == "user":
                    tx += [b["text"] for b in (pl.get("content") or [])
                           if isinstance(b, dict) and b.get("text")
                           and is_human(b["text"])]
        except OSError:
            continue
        rec = ({"client": "codex", "start": min(ts).isoformat(), "end": max(ts).isoformat(),
                "mins": active_minutes(ts), "text": clean(" ".join(dict.fromkeys(tx)))}
               if ts else None)
        keep(key, rec)
    if use_cache:
        _cache_save(fresh)
    return out


# ------------------------------------------------------------------- the brain
def load_md(path):
    try: raw = path.read_text(errors="ignore")
    except OSError: return {}, ""
    m = RE_FM.match(raw)
    if not m: return {}, raw
    fm, body = {}, m.group(2)
    key = None
    for line in m.group(1).splitlines():
        if re.match(r"^\s*-\s", line) and key:
            fm.setdefault(key + "_list", []).append(line.strip()[2:])
        elif ":" in line and not line.startswith(" "):
            key, _, v = line.partition(":")
            key = key.strip(); fm[key] = v.strip()
    return fm, body


def brain_entities():
    ents = []
    for p in sorted((BRAIN / "graph").rglob("*.md")):
        fm, body = load_md(p)
        if not fm.get("id"): continue
        tags = re.findall(r"[\w\-]+", fm.get("tags", ""))
        ents.append({"path": p, "id": fm["id"], "type": fm.get("type", ""),
                     "title": fm.get("title", p.stem), "updated": fm.get("updated", ""),
                     "status": fm.get("status", "active"), "tags": tags, "body": body})
    return ents


def inbox_items():
    out = []
    for p in sorted((BRAIN / "inbox").glob("*.md")):
        fm, body = load_md(p)
        out.append({"path": p, "type": fm.get("type", "note"),
                    "title": fm.get("title", p.stem),
                    "tags": re.findall(r"[\w\-]+", fm.get("tags", "")),
                    "created": fm.get("created", p.stem[:10]), "fm": fm, "body": body})
    return out


def profile_ref():
    """(id, display name) of the profile node — never hardcode a person."""
    for cand in ((BRAIN / "graph" / "profile.md"), (BRAIN / "graph" / "self.md")):
        if cand.exists():
            fm, _ = load_md(cand)
            return fm.get("id", "profile-self"), fm.get("title", "")
    return "profile-self", ""


def slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


# -------------------------------------------------------------------- lexicon
def build_lexicon(ents, inbox, sessions):
    """Topic -> keywords. Derived from the brain, then extended by discovery."""
    lex = collections.defaultdict(set)
    trusted = set()          # names taken from the graph itself, exempt from the IDF cut
    for e in ents:
        if e["type"] in ("person", "profile"):     # people aren't work topics
            continue
        key = slug(re.sub(r"^(task|project|task_type|skill|org)-", "", e["id"]))
        for term in (key.replace("-", " "), e["title"].lower()):
            if len(term) >= 5 or " " in term:
                lex[key].add(term); trusted.add(term)
        for t in e["tags"]:                       # multiword tags only; bare tags are noise
            if "-" in t and t not in STOP: lex[key].add(t.replace("-", " "))
    for it in inbox:
        for t in it["tags"]:
            if t in STOP or "-" not in t: continue        # only multiword tags carry topic
            term = t.replace("-", " ")
            host = next((k for k in lex if term in lex[k] or t == k), None)
            lex[host or t].add(term)
    # Curated aliases: the vocabulary the user actually types, maintained by the
    # nightly pass. Trusted, because a human or a reviewing model put them here.
    try:
        data = json.loads((BRAIN / "_index" / "lexicon.json").read_text())
        for topic, phrases in (data.get("topics") or {}).items():
            for ph in phrases:
                lex[topic].add(ph.lower()); trusted.add(ph.lower())
    except Exception:
        pass

    # IDF cut. A keyword present in a large share of sessions cannot discriminate
    # between topics — that is how the tag "product" silently merged three projects.
    n = max(len(sessions), 1)
    out = {}
    for topic, kws in lex.items():
        keep = set()
        for k in kws:
            if k in trusted:
                keep.add(k); continue
            df = sum(1 for s in sessions if k in s["text"]) / n
            if df <= (0.45 if " " in k else 0.20):
                keep.add(k)
        if keep: out[topic] = sorted(keep)
    return out


def session_digest(s, n=180):
    """First human sentences of a session — enough for a model to name the topic."""
    t = re.sub(r"\s+", " ", s["text"]).strip()
    return t[:n]




def score(sessions, lexicon):
    """Split each session's active time across the topics it actually touches."""
    agg = collections.defaultdict(lambda: {"mins": 0.0, "sessions": 0, "days": set(),
                                           "last": None, "first": None, "clients": set()})
    unmatched = 0.0
    for s in sessions:
        hits = {}
        for topic, kws in lexicon.items():
            h = sum(s["text"].count(k) for k in kws)
            need = 1 if any(" " in k for k in kws) else 2
            if h >= need: hits[topic] = h
        if not hits:
            unmatched += s["mins"]; continue
        tot = sum(hits.values())
        for topic, h in hits.items():
            a = agg[topic]
            a["mins"] += s["mins"] * h / tot
            a["sessions"] += 1
            a["days"].add(s["start"].date())
            a["clients"].add(s["client"])
            a["last"] = max(a["last"], s["end"]) if a["last"] else s["end"]
            a["first"] = min(a["first"], s["start"]) if a["first"] else s["start"]
    return agg, unmatched


def match_entity(topic, ents):
    try:
        pin = (json.loads((BRAIN / "_index" / "lexicon.json").read_text())
               .get("entity_map") or {}).get(topic)
        if pin:
            for e in ents:
                if e["id"] == pin: return e
    except Exception:
        pass
    for e in ents:
        base = slug(re.sub(r"^(task|project|task_type|skill|org)-", "", e["id"]))
        if base == topic or topic in base or base in topic: return e
        if slug(e["title"]) == topic: return e
    return None


# ---------------------------------------------------------------------- report
def analyse(args):
    sessions = read_sessions(args.days)
    ents, inbox = brain_entities(), inbox_items()
    lexicon = build_lexicon(ents, inbox, sessions)
    agg, unmatched = score(sessions, lexicon)
    now = dt.datetime.now(dt.timezone.utc)

    rows = []
    for topic, v in agg.items():
        if v["mins"] < 20 or v["sessions"] < 2: continue
        e = match_entity(topic, ents)
        upd = pts((e["updated"] + "T00:00:00+00:00") if e and e.get("updated") else None)
        caps = [i for i in inbox
                if any(t == topic or t in topic or topic in t for t in i["tags"])
                or topic.replace("-", " ") in i["title"].lower()]
        hot = (len(v["days"]) >= MIN_DAYS and v["sessions"] >= MIN_SESSIONS
               and v["mins"] / 60 >= MIN_HOURS)
        if e is None:
            action = "create" if hot else "watch"
        elif upd and v["last"] and v["last"].date() > upd.date():
            action = "refresh"
        else:
            action = "ok"
        rows.append({"topic": topic, "hours": round(v["mins"] / 60, 1),
                     "sessions": v["sessions"], "days": len(v["days"]),
                     "clients": sorted(v["clients"]),
                     "last": v["last"].date().isoformat() if v["last"] else None,
                     "first": v["first"].date().isoformat() if v["first"] else None,
                     "entity": e["id"] if e else None,
                     "entity_path": str(e["path"]) if e else None,
                     "entity_updated": e["updated"] if e else None,
                     "stale_days": (now.date() - upd.date()).days if upd else None,
                     "captures": [str(c["path"]) for c in caps],
                     "action": action, "hot": hot})
    rows.sort(key=lambda r: -r["hours"])

    # inbox clustering: a claim repeated across independent captures is evidence
    clusters = collections.defaultdict(list)
    for i in inbox:
        k = (i["type"], tuple(sorted(t for t in i["tags"] if t not in STOP))[:2])
        clusters[k].append(i)
    promo = []
    for (typ, tags), items in clusters.items():
        days = {i["created"][:10] for i in items}
        if len(items) >= MIN_CAPTURES and len(days) >= 2:
            promo.append({"type": typ, "tags": list(tags), "count": len(items),
                          "days": len(days), "paths": [str(i["path"]) for i in items]})
    promo.sort(key=lambda p: -p["count"])
    gated = []
    for path in sorted(list((BRAIN / "graph").rglob("*.md"))):
        fm, _ = load_md(path)
        if fm.get("directive") in ("confirm", "verify") and fm.get("id"):
            gated.append({"id": fm["id"],
                          "note": (fm.get("state_note", "") or fm.get("relevance", "")).strip('"')})
    return {"gated": gated, "rows": rows, "unmatched_hours": round(unmatched / 60, 1),
            "sessions": len(sessions), "inbox_total": len(inbox),
            "inbox_clusters": promo, "lexicon_size": len(lexicon)}


def cmd_scan(args):
    r = analyse(args)
    if args.json:
        print(json.dumps(r, indent=2)); return
    print(f"{r['sessions']} sessions, last {args.days} days   "
          f"({r['unmatched_hours']}h unmatched, {r['lexicon_size']} topics known)\n")
    mark = {"create": "NEW ", "refresh": "STALE", "watch": "· ", "ok": "ok "}
    print(f"{'':6}{'TOPIC':<22}{'hrs':>6}{'sess':>6}{'days':>6}  {'last':<11}{'in brain'}")
    for x in r["rows"]:
        where = x["entity"] or "—"
        if x["action"] == "refresh":
            where += f"  ({x['stale_days']}d stale)"
        print(f"{mark[x['action']]:<6}{x['topic']:<22}{x['hours']:>6}{x['sessions']:>6}"
              f"{x['days']:>6}  {x['last']:<11}{where}")
    if r["inbox_clusters"]:
        print(f"\nrepeated captures in inbox ({r['inbox_total']} waiting):")
        for c in r["inbox_clusters"]:
            print(f"  {c['count']}x {c['type']:<12}{','.join(c['tags']) or '(untagged)':<28}"
                  f"over {c['days']} days")


TEMPLATE = """---
id: {eid}
type: task
title: {title}
status: active
confidence: medium
scope: personal
provenance: autobrain:{today} ({sessions} sessions, {hours}h active, {days} days)
created: {today}
updated: {today}
review_by: {review}
auto: true
tags: [{tag}]
edges:
  - type: owned_by
    to: {owner}
---

**Auto-created from sustained activity** — {hours}h of active work across
{sessions} sessions on {days} separate days ({first} to {last}), in {clients}.
Promoted because it cleared the repetition and time thresholds while having no
node in the graph.

This body is a stub. It records *that* the work is happening, not what was
decided — a future session should fill that in, or fold in the related captures
below.
{caps}
"""


def cmd_promote(args):
    r = analyse(args)
    today = dt.date.today()
    review = (today + dt.timedelta(days=180)).isoformat()
    creates = [x for x in r["rows"] if x["action"] == "create"]
    refresh = [x for x in r["rows"] if x["action"] == "refresh"]
    if not creates and not refresh and not r["inbox_clusters"]:
        print("nothing above threshold."); return

    for x in creates:
        eid = f"task-{x['topic']}"
        dest = BRAIN / "graph" / "tasks" / f"{x['topic']}.md"
        caps = ""
        if x["captures"]:
            caps = "\n**Related captures waiting in the inbox:**\n" + "".join(
                f"- `{Path(c).name}`\n" for c in x["captures"])
        body = TEMPLATE.format(owner=profile_ref()[0], eid=eid, title=x["topic"].replace("-", " ").title(),
                               today=today, review=review, sessions=x["sessions"],
                               hours=x["hours"], days=x["days"], first=x["first"],
                               last=x["last"], clients=" and ".join(x["clients"]),
                               tag=x["topic"], caps=caps)
        if args.apply:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body)
            print(f"created  {dest.relative_to(BRAIN)}  ({x['hours']}h, {x['sessions']} sessions)")
        else:
            print(f"would create  graph/tasks/{x['topic']}.md  "
                  f"({x['hours']}h, {x['sessions']} sessions, {x['days']} days)")

    for x in refresh:
        p = Path(x["entity_path"])
        if args.apply:
            raw = p.read_text()
            raw = re.sub(r"^updated:.*$", f"updated: {today}", raw, count=1, flags=re.M)
            if "stale_since:" not in raw:
                raw = re.sub(r"^(updated:.*)$", rf"\1\nneeds_review: true",
                             raw, count=1, flags=re.M)
            note = (f"\n\n<!-- autobrain {today}: {x['hours']}h of activity on this topic "
                    f"since updated:{x['entity_updated']} ({x['stale_days']}d). "
                    f"Body may contradict reality — a session should rewrite it and move "
                    f"superseded text into a dated history block. -->\n")
            if "autobrain" not in raw:
                raw += note
            p.write_text(raw)
            print(f"flagged  {p.relative_to(BRAIN)}  ({x['stale_days']}d stale, "
                  f"{x['hours']}h since)")
        else:
            print(f"would flag  {p.relative_to(BRAIN)}  ({x['stale_days']}d stale, "
                  f"{x['hours']}h of activity since)")

    for c in r["inbox_clusters"]:
        dest = {"decision": "decisions", "preference": "preferences", "risk": "risks",
                "constraint": "constraints", "playbook": "playbooks",
                "note": "notes", "task": "tasks"}.get(c["type"], "notes")
        for src in c["paths"]:
            s = Path(src); d = BRAIN / "wiki" / dest / s.name[11:]
            if args.apply:
                d.parent.mkdir(parents=True, exist_ok=True)
                txt = s.read_text()
                if "auto:" not in txt:
                    txt = re.sub(r"^(updated:.*)$", rf"\1\nauto: true",
                                 txt, count=1, flags=re.M)
                d.write_text(txt); s.unlink()
                print(f"promoted {d.relative_to(BRAIN)}  ({c['count']} independent captures)")
            else:
                print(f"would promote  wiki/{dest}/{s.name[11:]}  "
                      f"({c['count']}x {c['type']}, {c['days']} days)")

    if args.apply:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        LIVE.write_text(json.dumps(analyse(argparse.Namespace(days=14, json=False)),
                                   indent=2, default=str))
        STATE.write_text(json.dumps({"last_run": dt.datetime.now().isoformat(),
                                     "created": len(creates), "flagged": len(refresh),
                                     "promoted": sum(c["count"] for c in r["inbox_clusters"])},
                                    indent=2))


CONTEXT_BUDGET = 6000   # chars (~1.5k tokens): a preference file that grows
                        # unbounded must not quietly tax every session.


def build_context(days=14):
    """Profile + preferences + live topics. Shared by the hook and the Codex export."""
    chunks, used, skipped = [], 0, 0
    paths = [BRAIN / "graph" / "profile.md"]
    paths += sorted((BRAIN / "wiki" / "preferences").glob("*.md"))
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        if used + len(text) > CONTEXT_BUDGET:
            skipped += 1
            continue
        chunks.append(text)
        used += len(text)

    live_block = ""
    try:
        r = None
        if LIVE.exists():
            age = (dt.datetime.now().timestamp() - LIVE.stat().st_mtime) / 3600
            newest = max((p.stat().st_mtime for p in (BRAIN / "graph").rglob("*.md")),
                         default=0)
            if age < LIVE_TTL_HOURS and LIVE.stat().st_mtime >= newest:
                r = json.loads(LIVE.read_text())
        if r is None:
            r = analyse(argparse.Namespace(days=days, json=False))
            LIVE.parent.mkdir(parents=True, exist_ok=True)
            LIVE.write_text(json.dumps(r, indent=2, default=str))
        live = [x for x in r["rows"] if x["hours"] >= 1][:6]
        if live:
            lines = [f"\n## Live topics (last {days} days, measured from your own sessions)\n"]
            for x in live:
                flag = ""
                if x["action"] == "refresh":
                    flag = f"  ⚠ node {x['stale_days']}d stale — verify before relying on it"
                elif x["action"] == "create":
                    flag = "  ⚠ no node yet"
                lines.append(f"- **{x['topic']}** — {x['hours']}h over {x['days']} days"
                             f" (last {x['last']}){flag}")
            lines.append(
                "\nIf this session's work matches one of these, say in one line what you "
                "loaded from the brain.")
            try:
                gated = [x for x in r.get("gated", [])]
                if gated:
                    lines.append("\n**Needs your confirmation before use** — quiet long "
                                 "enough that it may have moved on:")
                    for g in gated[:6]:
                        lines.append(f"- `{g['id']}` ({g['note']})")
            except Exception:
                pass
            live_block = "\n".join(lines)
    except Exception:
        pass
    return DIRECTIVE_LEGEND + "\n" + "\n\n".join(chunks) + live_block, skipped


def cmd_session_start(args):
    """SessionStart hook. Emits the hook JSON envelope; never blocks a session."""
    body, skipped = build_context(args.days)
    if not body.strip():
        return
    if getattr(args, "raw", False):
        print(body); return
    header = (f"Loaded automatically from the brain at {BRAIN} — profile, standing "
              "preferences, and what has actually been worked on lately. Treat these as "
              "how this person wants to be worked with, not as background reading. "
              "Don't re-read these files; they are already here.")
    if skipped:
        header += (f" ({skipped} preference file(s) skipped — over the {CONTEXT_BUDGET}-char "
                   "budget; run health to see what has grown.)")
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": "SessionStart",
                               "additionalContext": header + "\n\n" + body},
        "suppressOutput": True,
    }))


# ---------------------------------------------------------------- state engine
# Nothing is deleted and nothing waits for approval. Everything carries keywords
# saying how much weight a session should give it. Two INDEPENDENT axes, because
# a thing can be recent but unproven, or old but certain, and those need
# different answers. The stricter directive wins.

CURRENT_DAYS, FADING_DAYS = 14, 60
# Identity does not decay with disuse — a colleague's role is not made uncertain
# by a quiet fortnight. Only work state decays. Global preferences and the profile
# are loaded every session by the hook; gating them behind `confirm` is absurd.
NO_DECAY_TYPES = {"profile", "person", "org", "skill"}
STRICTNESS = {"use": 0, "cite": 1, "confirm": 2, "verify": 3, "ignore": 4}
MANAGED = ("last_activity", "relevance", "evidence", "directive", "state_note")

DIRECTIVE_LEGEND = """\
How to read the `directive:` on anything in this brain:
- `use`     — apply it; no need to mention it
- `cite`    — apply it, but say it is unconfirmed (inferred from 1-2 sessions)
- `confirm` — ASK before relying on it; the work has moved on (15-60 days quiet)
- `verify`  — the content may be false; newer activity contradicts it, check first
- `ignore`  — do not load unless explicitly asked; retained, never deleted
"""


def relevance_band(days):
    if days is None:
        return "unknown", "cite"
    if days <= CURRENT_DAYS:
        return "current", "use"
    if days <= FADING_DAYS:
        return "fading", "confirm"
    return "dormant", "ignore"


def evidence_band(fm, captures, contradicted):
    if fm.get("status") == "superseded" or fm.get("superseded_by"):
        return "superseded", "ignore"
    if contradicted:
        return "contradicted", "verify"
    if (fm.get("confidence", "") or "").lower() == "high" and fm.get("auto") != "true":
        return "stated", "use"          # written because the user said so
    if captures >= MIN_CAPTURES:
        return "observed", "use"
    if captures >= 1 or fm.get("auto") == "true":
        return "inferred", "cite"
    return "stated", "use"


def strictest(*directives):
    return max(directives, key=lambda d: STRICTNESS.get(d, 0))


def set_frontmatter(path, values, note=None):
    """Upsert scalar keys after the `type:` line, leaving lists untouched."""
    raw = path.read_text()
    m = RE_FM.match(raw)
    if not m:
        return False
    fm, body = m.group(1), m.group(2)
    lines = [l for l in fm.splitlines()
             if not any(re.match(rf"^{k}:", l) for k in MANAGED)]
    block = [f"{k}: {v}" for k, v in values.items() if v is not None]
    if note:
        block.append(f"state_note: {note}")
    out, done = [], False
    for l in lines:
        out.append(l)
        if not done and re.match(r"^type:", l):
            out.extend(block); done = True
    if not done:
        out.extend(block)
    path.write_text("---\n" + "\n".join(out) + "\n---\n" + body)
    return True


def raw_fm(path):
    m = RE_FM.match(path.read_text())
    return m.group(1) if m else ""


def topic_of(text, lexicon):
    best, score = None, 0
    low = text.lower()
    for topic, kws in lexicon.items():
        h = sum(low.count(k) for k in kws)
        if h > score:
            best, score = topic, h
    return best


def cmd_state(args):
    sessions = read_sessions(90)
    ents, inbox = brain_entities(), inbox_items()
    lexicon = build_lexicon(ents, inbox, sessions)
    agg, _ = score(sessions, lexicon)
    today = dt.date.today()

    cap_count = collections.Counter()
    for it in inbox:
        t = topic_of(" ".join(it["tags"]) + " " + it["title"] + " " + it["body"][:400], lexicon)
        if t:
            cap_count[t] += 1

    changed, rows = 0, []
    for path in sorted(list((BRAIN / "graph").rglob("*.md"))
                       + list((BRAIN / "wiki").rglob("*.md"))):
        fm, body = load_md(path)
        if not fm.get("id"):
            continue
        topic = topic_of(f"{fm.get('title','')} {fm.get('tags','')} {path.stem} {body[:600]}",
                         lexicon)
        owner_pre = match_entity(topic, ents) if topic else None
        inherits = bool(owner_pre and owner_pre["id"] == fm["id"]) or \
            path.parent.name in ("decisions", "preferences", "constraints", "risks",
                                 "playbooks", "notes", "tasks")
        act = agg.get(topic, {}).get("last") if (topic and inherits) else None
        act_date = act.date() if act else None
        upd = None
        try:
            upd = dt.date.fromisoformat(fm.get("updated", "")[:10])
        except Exception:
            pass
        ref = act_date or upd
        days = (today - ref).days if ref else None
        rel, d_rel = relevance_band(days)
        is_global_pref = (fm.get("type") == "preference" and "about:" not in raw_fm(path))
        if fm.get("type") in NO_DECAY_TYPES or is_global_pref:
            rel, d_rel = ("standing", "use")
        # An explicit judgement outranks a day count. Something marked paused is
        # paused whether it went quiet yesterday or last month.
        if fm.get("status") == "paused":
            rel, d_rel = ("paused", "confirm")
        elif fm.get("status") in ("archived", "superseded"):
            rel, d_rel = (fm["status"], "ignore")
        # Only the topic's OWN node can be contradicted by activity on it. A
        # person who merely mentions a project is not invalidated by work on it.
        owner = match_entity(topic, ents) if topic else None
        is_own = bool(owner and owner["id"] == fm["id"])
        contradicted = bool(is_own and act_date and upd and act_date > upd
                            and (today - upd).days > CURRENT_DAYS)
        ev, d_ev = evidence_band(fm, cap_count.get(topic, 0), contradicted)
        directive = strictest(d_rel, d_ev)
        note = None
        if directive == "confirm":
            note = (f'"{days}d since activity on {topic or "this"} - confirm with the user '
                    f'before taking this as a reference"')
        elif directive == "verify":
            note = f'"work continued after this was written - verify before relying on it"'
        elif directive == "ignore":
            note = f'"quiet {days}d - retained, not loaded unless asked for"'
        if set_frontmatter(path, {"last_activity": ref or "unknown", "relevance": rel,
                                  "evidence": ev, "directive": directive}, note) if args.apply else True:
            changed += 1
        rows.append((directive, rel, ev, topic or "-", str(path.relative_to(BRAIN))))

    order = sorted(rows, key=lambda r: -STRICTNESS.get(r[0], 0))
    counts = collections.Counter(r[0] for r in rows)
    print(("wrote state on " if args.apply else "would set state on ") + f"{changed} files")
    print("  " + "  ".join(f"{k}:{v}" for k, v in
                           sorted(counts.items(), key=lambda x: STRICTNESS.get(x[0], 0))))
    if args.verbose:
        print()
        for d, rel, ev, topic, p in order[:args.limit]:
            print(f"  {d:<8}{rel:<12}{ev:<14}{topic:<18}{p}")


DOC_DIRS = {"decision": "decisions", "preference": "preferences", "risk": "risks",
            "constraint": "constraints", "playbook": "playbooks", "note": "notes",
            "task": "tasks"}
ENT_DIRS = {"task_type": "task_types", "person": "people", "org": "orgs",
            "project": "tasks", "skill": "skills", "system": "systems"}


def cmd_absorb(args):
    """Dissolve the inbox into the brain. Nothing is rejected; state does the gating.

    A review queue nobody walks through is not a safety mechanism, it is a queue
    that rots. Everything enters and carries a directive saying how much weight
    to give it — `cite` for a single capture, `confirm` once it goes quiet.
    """
    moved = []
    for it in inbox_items():
        typ = it["type"]
        if typ in ENT_DIRS:
            dest = BRAIN / "graph" / ENT_DIRS[typ] / it["path"].name[11:]
        else:
            dest = BRAIN / "wiki" / DOC_DIRS.get(typ, "notes") / it["path"].name[11:]
        if dest.exists():
            print(f"skip     {dest.relative_to(BRAIN)} (already there)")
            continue
        if args.apply:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(it["path"].read_text())
            it["path"].unlink()
        moved.append((typ, str(dest.relative_to(BRAIN))))
    verb = "absorbed" if args.apply else "would absorb"
    print(f"{verb} {len(moved)} proposals — none rejected, state decides their weight")
    for typ, d in sorted(moved):
        print(f"  {typ:<11}{d}")


def cmd_sync(args):
    """Fast end-of-session pass: absorb, promote, re-state, refresh both exports.

    This is what removes the day-long lag. The nightly pass used to be the only
    thing that moved work into the brain, so two sessions on the same day could
    not see each other. Session end is the natural moment — the work just
    happened, and the transcript cache makes a full pass sub-second.
    """
    t0 = time.time()
    quiet = args.quiet
    try:
        with brain_lock(timeout=5):
            out = []
            for fn, a in ((cmd_absorb, {"apply": True, "days": args.days}),
                          (cmd_promote, {"apply": True, "days": args.days}),
                          (cmd_state, {"apply": True, "days": 90, "verbose": False,
                                       "limit": 0})):
                import io, contextlib as _c
                buf = io.StringIO()
                with _c.redirect_stdout(buf):
                    fn(argparse.Namespace(json=False, **a))
                out.append(buf.getvalue().strip())
            LIVE.write_text(json.dumps(analyse(argparse.Namespace(days=14, json=False)),
                                       indent=2, default=str))
            buf = io.StringIO()
            with _c.redirect_stdout(buf):
                cmd_export_codex(argparse.Namespace(days=14, json=False))
    except TimeoutError:
        if not quiet:
            print("skipped — another pass is running")
        return
    if not quiet:
        print(f"synced in {time.time() - t0:.1f}s")
        for chunk in out:
            for line in chunk.splitlines():
                if line.strip() and "nothing above threshold" not in line:
                    print("  " + line)


def cmd_digest(args):
    """Sessions no topic claims — the raw material for proposing new topics."""
    sessions = read_sessions(args.days)
    ents, inbox = brain_entities(), inbox_items()
    lexicon = build_lexicon(ents, inbox, sessions)
    rows = []
    for s in sessions:
        if any(sum(s["text"].count(k) for k in kws) >= (1 if any(" " in k for k in kws) else 2)
               for kws in lexicon.values()):
            continue
        if s["mins"] < 10:
            continue
        rows.append({"date": s["start"].date().isoformat(), "client": s["client"],
                     "mins": round(s["mins"]), "opening": session_digest(s)})
    rows.sort(key=lambda r: -r["mins"])
    if args.json:
        print(json.dumps(rows, indent=2)); return
    print(f"{len(rows)} unclaimed sessions "
          f"({round(sum(r['mins'] for r in rows) / 60, 1)}h) — name these to extend "
          f"the lexicon\n")
    for r in rows[:args.limit]:
        print(f"{r['date']}  {r['client']:<7}{r['mins']:>4}m  {r['opening'][:110]}")


CODEX_AGENTS = Path(os.path.expanduser("~/.codex/AGENTS.md"))
MARK_A, MARK_B = "<!-- keel:start -->", "<!-- keel:end -->"


def cmd_export_codex(args):
    """Codex has no session hook, so AGENTS.md is its always-loaded surface."""
    body, _ = build_context(args.days)
    who = profile_ref()[1]
    title = f"Keel — {who}'s persistent context" if who else "Keel — persistent context"
    block = (f"{MARK_A}\n<!-- generated by keel autobrain on "
             f"{dt.date.today()} — edits inside this block are overwritten -->\n\n"
             f"# {title}\n\n{body.strip()}\n\n{MARK_B}")
    CODEX_AGENTS.parent.mkdir(parents=True, exist_ok=True)
    cur = CODEX_AGENTS.read_text() if CODEX_AGENTS.exists() else ""
    if MARK_A in cur and MARK_B in cur:
        new = re.sub(re.escape(MARK_A) + r".*?" + re.escape(MARK_B), lambda m: block,
                     cur, flags=re.S)
    else:
        new = (cur.rstrip() + "\n\n" + block + "\n") if cur.strip() else block + "\n"
    CODEX_AGENTS.write_text(new)
    print(f"wrote {CODEX_AGENTS}  ({len(block)} chars in the keel block, "
          f"{len(new)} total — anything outside the markers was preserved)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "promote", "session-start", "digest", "export-codex", "state", "absorb", "sync"):
        s = sub.add_parser(name)
        s.add_argument("--days", type=int, default=45)
        s.add_argument("--json", action="store_true")
        if name == "promote":
            s.add_argument("--apply", action="store_true")
        if name == "digest":
            s.add_argument("--limit", type=int, default=30)
        if name == "session-start":
            s.add_argument("--raw", action="store_true")
        if name == "sync":
            s.add_argument("--quiet", action="store_true")
        if name == "absorb":
            s.add_argument("--apply", action="store_true")
        if name == "state":
            s.add_argument("--apply", action="store_true")
            s.add_argument("--verbose", action="store_true")
            s.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    {"scan": cmd_scan, "promote": cmd_promote, "session-start": cmd_session_start,
     "digest": cmd_digest, "export-codex": cmd_export_codex,
     "state": cmd_state, "absorb": cmd_absorb, "sync": cmd_sync}[a.cmd](a)


if __name__ == "__main__":
    main()
