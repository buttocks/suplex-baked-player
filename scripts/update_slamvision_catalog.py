#!/usr/bin/env python3
"""SlamVision catalog updater. Tracks stable IDs; never edits live embed URLs."""
import argparse
import csv
import datetime as dt
import difflib
import io
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "research"
CURRENT = RESEARCH / "slamvision-current.json"
BASELINE = RESEARCH / "slamvision-by-tube-2026-11-17.json"
HISTORY = RESEARCH / "slamvision-change-log.json"
API = "https://ring-channel-tv.emergent.host/api/"
PAGES = "https://buttocks.github.io/suplex-baked-player/"
ALLOWED = re.compile(r"^[a-z0-9][a-z0-9-]{0,90}$")
FIELDS = ("number", "name", "callsign", "category", "tagline", "archived")
RULES = [
    ("NJPW Tube", r"njpw|new japan|antonio inoki"),
    ("AJPW Tube", r"ajpw|all japan pro|stan hansen|giant baba|three pillars"),
    ("Lucha Tube", r"lucha|cmll|aaa\b|rey mysterio|arena mexico"),
    ("Joshi Tube", r"joshi|stardom|tjpw|marigold|io shirai|iyo sky"),
    ("WCW Tube", r"\bwcw\b|world championship wrestling|nitro|clash of the champions|halloween havoc|superbrawl"),
    ("ECW Tube", r"\becw\b|extreme championship wrestling|hardcore tv"),
    ("AEW Tube", r"\baew\b|all elite wrestling|kenny omega|all in"),
    ("ROH Tube", r"\broh\b|ring of honor"),
    ("TNA / Impact Tube", r"\btna\b|impact wrestling|total nonstop action"),
    ("NOAH Tube", r"\bnoah\b"),
    ("DDT Tube", r"\bddt\b|dramatic dream team"),
    ("WWF / WWE Tube", r"\bwwf\b|\bwwe\b|world wrestling federation|wrestlemania|attitude ppv|john cena|hulk hogan|roman reigns|hart family|andre the giant"),
    ("Shoot / MMA Tube", r"\bmma\b|\bshoot\b|bloodsport|pancrase|uwfi"),
    ("Other Japanese Wrestling Tube", r"big japan|bjw|michinoku|kaientai|osaka pro|dragon gate|dragongate|frontier martial|battlarts|great muta|fmw\b"),
    ("Indies / Hardcore Tube", r"\bgcw\b|\bczw\b|combat zone|game changer|juggalo|pwg|guerrilla|chikara|euromat|wcpw|wrestling society x|\bmlw\b|maple leaf pro|deathmatch"),
    ("Territories / Classic US Tube", r"territories|memphis|\bawa\b|american wrestling association|mid.south"),
    ("Years / Mixed Wrestling Tube", r"^year-\d{4}|wrestling in \d{4}|monday night wars|random wrestling|tag team"),
]


def fromfile(path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fallback


def fetch(endpoint):
    req = urllib.request.Request(API + endpoint, headers={
        "Accept": "application/json", "User-Agent": "SlamVision-Catalog/1.0"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=23) as response:
                return json.load(response)
        except (OSError, ValueError) as exc:
            last = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError("Upstream " + endpoint + " unavailable: " + str(last))


def parse_time(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def guide_programs(slots, now):
    def brief(slot):
        program = slot.get("program") or {}
        return {"title": program.get("title") or "", "episode": program.get("episode") or "",
                "start": slot.get("start"), "end": slot.get("end"), "stream_url": ""}
    valid = [s for s in slots if isinstance(s, dict) and parse_time(s.get("start"))
             and parse_time(s.get("end"))]
    live = next((s for s in valid if parse_time(s["start"]) <= now < parse_time(s["end"])), None)
    future = sorted((s for s in valid if parse_time(s["start"]) > now), key=lambda s: s["start"])
    return brief(live) if live else None, [brief(s) for s in future[:2]]


# Explicit destination choices: these stable IDs should never fall into Needs Review.
TUBE_BY_STABLE_ID = {
    "nwa-crockett": "Territories / Classic US Tube",
    "revpro": "Indies / Hardcore Tube",
}


def classify(channel):
    chosen = TUBE_BY_STABLE_ID.get(channel.get("id"))
    if chosen:
        return chosen
    haystack = " ".join(str(channel.get(k) or "") for k in ("id", "name", "callsign", "tagline"))
    for tube, regex in RULES:
        if re.search(regex, haystack, re.I):
            return tube
    return "Needs Review"


def indexed(channels, prev):
    if not isinstance(channels, list):
        raise RuntimeError("Upstream lineup is not a list")
    by_id = {}
    for row in channels:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise RuntimeError("Invalid upstream record")
        ident = row["id"]
        if not ALLOWED.fullmatch(ident) or ident in by_id:
            raise RuntimeError("Duplicate or unsafe upstream feed ID: " + ident)
        by_id[ident] = row
    old_count = sum(c.get("availability", "available") == "available" for c in prev["channels"])
    if len(by_id) < (max(35, int(old_count * 0.65)) if old_count >= 35 else 1):
        raise RuntimeError("Suspicious lineup drop to " + str(len(by_id)) +
                           "; preserving last published snapshot")
    return by_id


def related(missing, active):
    name = str(missing.get("name") or "").lower()
    hits = []
    for c in active:
        score = difflib.SequenceMatcher(None, name, str(c.get("name") or "").lower()).ratio()
        if missing.get("tube") == c.get("tube"):
            score += 0.12
        if score >= 0.73:
            hits.append((score, c["id"]))
    return [id for score, id in sorted(hits, reverse=True)[:3]]


def rebuild(prev, upstream, guide, now):
    incoming = indexed(upstream, prev)
    rows = (guide or {}).get("rows") or []
    guide_by_id = {r["channel"]["id"]: r.get("slots") or [] for r in rows
                   if isinstance(r, dict) and isinstance(r.get("channel"), dict)
                   and r["channel"].get("id")}
    changes = {k: [] for k in ("added", "missing", "removed", "restored",
                              "renamed", "renumbered", "details_changed", "recategorized", "review")}
    entries = []
    for old in prev["channels"]:
        c = dict(old)
        new = incoming.pop(c["id"], None)
        if new is None:
            misses = min(2, int(c.get("missing_scans") or 0) + 1)
            status = "unavailable" if misses == 2 else "temporarily_missing"
            if status != c.get("availability", "available"):
                changes["removed" if misses == 2 else "missing"].append(c["id"])
            c["availability"], c["missing_scans"] = status, misses
        else:
            if c.get("availability", "available") != "available":
                changes["restored"].append(c["id"])
            if c.get("number") != new.get("number"):
                changes["renumbered"].append(c["id"])
            if (c.get("name"), c.get("callsign")) != (new.get("name"), new.get("callsign")):
                changes["renamed"].append(c["id"])
            if any(c.get(k) != new.get(k) for k in ("tagline", "category", "archived")):
                changes["details_changed"].append(c["id"])
            c.update({k: new.get(k) for k in FIELDS})
            # Promote previously unclassified feeds without changing stable IDs or embeds.
            if c.get("tube") == "Needs Review":
                proposed = classify(c)
                if proposed != "Needs Review":
                    c["tube"] = proposed
                    changes["recategorized"].append(c["id"])
            c["availability"], c["missing_scans"] = "available", 0
            if c["id"] in guide_by_id:
                now_show, upcoming = guide_programs(guide_by_id[c["id"]], now)
                c.update({"now": now_show, "next": upcoming[0] if upcoming else None,
                          "next2": upcoming[1] if len(upcoming) > 1 else None,
                          "guide_slots": len(guide_by_id[c["id"]])})
        entries.append(c)
    for id, new in incoming.items():
        tube = classify(new)
        if tube == "Needs Review":
            changes["review"].append(id)
        current, upcoming = guide_programs(guide_by_id.get(id, []), now)
        url = PAGES + "slamvision-feed.html?id=" + urllib.parse.quote(id, safe="")
        iframe = ('<iframe src="' + url +
                  '" width="1280" height="720" frameborder="0" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>')
        entries.append({
            **{k: new.get(k) for k in FIELDS}, "id": id, "tube": tube,
            "now": current, "next": upcoming[0] if upcoming else None,
            "next2": upcoming[1] if len(upcoming) > 1 else None,
            "guide_slots": len(guide_by_id.get(id, [])),
            "existing_embed": False, "legacy_channel_number": None,
            "player_type": "shared", "embed_url": url, "embed_html": iframe,
            "availability": "available", "missing_scans": 0,
        })
        changes["added"].append(id)
    active = [c for c in entries if c["availability"] == "available"]
    tube_order = list(prev["destination_tubes"])
    for entry in entries:
        if entry["tube"] not in tube_order:
            tube_order.append(entry["tube"])
        if entry["availability"] != "available":
            entry["suggested_replacements"] = related(entry, active)
        else:
            entry.pop("suggested_replacements", None)
    entries.sort(key=lambda c: (tube_order.index(c["tube"]),
                c["availability"] != "available", int(c.get("number") or 9999), c["id"]))
    tube_counts = {t: sum(c["tube"] == t and c["availability"] == "available" for c in entries)
                   for t in tube_order}
    changed = any(changes.values())
    stamp = now.isoformat()
    result = {
        "snapshot_utc": stamp if changed else prev.get("snapshot_utc", stamp),
        "last_updated_utc": stamp if changed else prev.get("last_updated_utc", prev.get("snapshot_utc", stamp)),
        "total": len(active), "tracked_total": len(entries),
        "destination_tubes": tube_counts, "channels": entries,
        "embed_ready_count": len(active),
        "legacy_embed_count": sum(c.get("player_type") == "legacy" for c in active),
        "new_shared_player_count": sum(c.get("player_type") == "shared" for c in active),
        "player_page": PAGES + "slamvision-feed.html",
        "change_report": changes if changed else prev.get("change_report", {}),
    }
    return result, changes, changed


def export(data, changes, now):
    RESEARCH.mkdir(parents=True, exist_ok=True)
    files = {CURRENT: json.dumps(data, indent=2, ensure_ascii=False) + "\n"}
    csvfile = io.StringIO()
    writer = csv.writer(csvfile)
    writer.writerow(("tube", "upstream_number", "stable_id", "name", "description",
                     "availability", "now_at_snapshot", "embed_url", "embed_html"))
    md = ["# SlamVision channel embeds by Baked.live tube", "",
          "Last catalog update: " + data["last_updated_utc"], "",
          "Active: " + str(data["total"]) + " · Tracked: " + str(data["tracked_total"]), "",
          "Provider dials change; iframe URLs use stable feed IDs.", ""]
    snippets = ["SlamVision iframe snippets by Baked.live tube", ""]
    for tube, count in data["destination_tubes"].items():
        md.extend(["## " + tube + " (" + str(count) + " active)", "",
                   "| Feed · Stable ID | Upstream # | Availability | Player |",
                   "|---|---:|---|---|"])
        snippets.append("=== " + tube + " ===")
        for c in (x for x in data["channels"] if x["tube"] == tube):
            status = c.get("availability", "available")
            label = str(c.get("name") or c["id"]).replace("|", "\\|")
            md.append("| " + label + " (" + c["id"] + ") | " + str(c.get("number") or "—") +
                      " | " + status + " | [Open](" + c["embed_url"] + ") |")
            writer.writerow((tube, c.get("number"), c["id"], c.get("name"), c.get("tagline"),
                            status, (c.get("now") or {}).get("title"), c["embed_url"], c["embed_html"]))
            if status == "available":
                snippets.extend([label + " (" + c["id"] + ")", c["embed_html"], ""])
        md.append("")
        snippets.append("")
    files[RESEARCH / "slamvision-current.csv"] = csvfile.getvalue()
    files[RESEARCH / "slamvision-current.md"] = "\n".join(md) + "\n"
    files[RESEARCH / "slamvision-current-iframes.txt"] = "\n".join(snippets) + "\n"
    history = fromfile(HISTORY, {"events": []})
    history["events"] = ([{"at": now.isoformat(), "changes": changes,
                          "active": data["total"], "tracked": data["tracked_total"]}]
                         + history.get("events", []))[:100]
    files[HISTORY] = json.dumps(history, indent=2) + "\n"
    path = RESEARCH / "slamvision-snapshots" / (now.strftime("%Y-%m-%dT%H-%M-%SZ") + ".json")
    files[path] = files[CURRENT]
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print("CATALOG UPDATED:", len(files), "files", flush=True)


def self_test():
    original_url = PAGES + "njpw-slamvision.html?channel=01"
    base = {"snapshot_utc": "2026-11-17T00:00:00+00:00",
            "destination_tubes": {"NJPW Tube": 1, "WCW Tube": 1},
            "channels": [
                {"id": "njpw", "number": 1, "name": "New Japan", "tube": "NJPW Tube",
                 "embed_url": original_url, "embed_html": "<iframe></iframe>",
                 "player_type": "legacy", "availability": "available"},
                {"id": "wcw", "number": 2, "name": "WCW", "tube": "WCW Tube",
                 "embed_url": PAGES + "wcw-slamvision.html", "embed_html": "<iframe></iframe>",
                 "player_type": "legacy", "availability": "available"}]}
    now = dt.datetime(2026, 11, 17, 20, tzinfo=dt.timezone.utc)
    lineup = [{"id": "njpw", "number": 63, "name": "New Japan"},
              {"id": "njpw-g1climax", "number": 65, "name": "NJPW G1 Climax"}]
    a, delta, flag = rebuild(base, lineup, None, now)
    by_id = {x["id"]: x for x in a["channels"]}
    assert flag and delta["added"] == ["njpw-g1climax"] and delta["renumbered"] == ["njpw"]
    assert delta["missing"] == ["wcw"] and by_id["wcw"]["availability"] == "temporarily_missing"
    assert by_id["njpw"]["embed_url"] == original_url and by_id["njpw"]["tube"] == "NJPW Tube"
    assert by_id["njpw-g1climax"]["tube"] == "NJPW Tube"
    assert by_id["njpw-g1climax"]["embed_url"].endswith("id=njpw-g1climax")
    b, delta2, _ = rebuild(a, lineup, None, now)
    assert delta2["removed"] == ["wcw"]
    c, delta3, flag3 = rebuild(b, lineup, None, now)
    assert not flag3 and not any(delta3.values())
    d, delta4, _ = rebuild(c, lineup + [{"id": "wcw", "number": 92, "name": "WCW"}], None, now)
    assert delta4["restored"] == ["wcw"]
    assert {x["id"]: x for x in d["channels"]}["wcw"]["embed_url"] == base["channels"][1]["embed_url"]
    for feed, expected in [("njpw-wk", "NJPW Tube"), ("ajpw-summer", "AJPW Tube"),
                           ("cmll-new", "Lucha Tube"), ("marigold", "Joshi Tube"),
                           ("nwa-crockett", "Territories / Classic US Tube"),
                           ("revpro", "Indies / Hardcore Tube"),
                           ("mystery-show", "Needs Review")]:
        assert classify({"id": feed, "name": feed}) == expected
    # Regression: classify a formerly unknown feed while preserving its iframe.
    review_url = PAGES + "slamvision-feed.html?id=mystery-show"
    review_base = {"destination_tubes": {"Needs Review": 1},
                   "channels": [{"id": "mystery-show", "name": "Mystery Show",
                                 "number": 99, "tube": "Needs Review",
                                 "embed_url": review_url, "availability": "available"}]}
    promoted, promoted_changes, promoted_flag = rebuild(
        review_base,
        [{"id": "mystery-show", "number": 99, "name": "NJPW Wrestling Classics"}],
        None, now)
    assert promoted_flag and promoted_changes["recategorized"] == ["mystery-show"]
    assert promoted["channels"][0]["tube"] == "NJPW Tube"
    assert promoted["channels"][0]["embed_url"] == review_url
    rerun, repeat_changes, repeat_flag = rebuild(
        promoted, [{"id": "mystery-show", "number": 99, "name": "NJPW Wrestling Classics"}],
        None, now)
    assert not repeat_flag and not any(repeat_changes.values())
    try:
        indexed([{"id": "njpw"}, {"id": "njpw"}], {"channels": []})
    except RuntimeError:
        pass
    else:
        raise AssertionError("Duplicate feed ID not rejected")
    print("PASS: stable IDs, 2-scan removal, recovery, preserve legacy URL, recategorization, no-change repeat, unknown review, 7 category tests")


def scan(dry_run):
    previous = fromfile(CURRENT) or fromfile(BASELINE)
    if not previous or not isinstance(previous.get("channels"), list):
        raise RuntimeError("No previous inventory; refusing unsafe overwrite")
    upstream = fetch("channels")
    try:
        guide = fetch("guide?hours=4")
    except RuntimeError as exc:
        print("WARNING: guide fetch failed, keeping prior program details:", exc)
        guide = None
    now = dt.datetime.now(dt.timezone.utc)
    data, delta, changed = rebuild(previous, upstream, guide, now)
    note = ", ".join(k + "=" + str(len(v)) for k, v in delta.items() if v) or "no changes"
    print("SCAN:", now.isoformat(), "live", data["total"], "tracked", data["tracked_total"],
          note, flush=True)
    if dry_run:
        print("DRY RUN: no files changed")
    elif changed or not CURRENT.exists():
        export(data, delta, now)
    else:
        print("NO LINEUP CHANGE: no files written or commit needed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.scan:
        scan(args.dry_run)
    else:
        parser.error("use --self-test or --scan [--dry-run]")
