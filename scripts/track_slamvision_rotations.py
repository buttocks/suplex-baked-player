#!/usr/bin/env python3
"""Observe upstream dial and stable-ID changes, including WHEN they were seen.

Read-only with respect to player pages, existing schedules, and catalog. The
workflow commits observation state/history to a SEPARATE Git branch, avoiding
a Pages rebuild on every 30-minute heartbeat.
"""
import argparse
import datetime as dt
import difflib
import json
import pathlib
import re
import time
import urllib.request
from zoneinfo import ZoneInfo

API = "https://ring-channel-tv.emergent.host/api/channels"
EASTERN = ZoneInfo("America/Toronto")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,90}$")


def iso(moment):
    return moment.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def observe(raw, minimum=20):
    if not isinstance(raw, list) or len(raw) < minimum:
        raise ValueError("Incomplete upstream lineup; refusing to log false removals")
    by_id, by_dial = {}, {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Invalid upstream feed")
        feed = item["id"]
        if not SAFE_ID.fullmatch(feed) or feed in by_id:
            raise ValueError("Invalid or duplicate feed ID " + repr(feed))
        dial = item.get("number")
        if isinstance(dial, bool) or not isinstance(dial, int) or not 1 <= dial <= 100000:
            raise ValueError("Invalid dial for " + feed)
        if str(dial) in by_dial:
            raise ValueError("Duplicate channel number " + str(dial))
        record = {"id": feed, "number": dial,
                  "name": str(item.get("name") or feed),
                  "callsign": str(item.get("callsign") or ""),
                  "category": str(item.get("category") or "")}
        by_id[feed] = record
        by_dial[str(dial)] = feed
    return by_id, by_dial


def get_lineup():
    request = urllib.request.Request(API, headers={
        "Accept": "application/json", "User-Agent": "SlamVision-RotationObserver/1.0"
    })
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as result:
                return json.load(result)
        except (OSError, ValueError) as exc:
            last = exc
            if attempt < 2:
                time.sleep(2 + attempt)
    raise RuntimeError("Cannot read lineup; last successful snapshot retained: " + str(last))


def candidate_replacements(old, new_ids, new_dials):
    """Unverified hints only; NEVER automatically edit a player ID."""
    result = []
    for item in new_ids:
        ratio = difflib.SequenceMatcher(
            None, old["name"].casefold(), item["name"].casefold()).ratio()
        same_dial = item["number"] == old["number"]
        if ratio >= 0.78 or (same_dial and ratio >= 0.5):
            result.append({"id": item["id"], "name": item["name"],
                           "number": item["number"], "name_similarity": round(ratio, 3),
                           "same_dial": same_dial, "verified": False})
    result.sort(key=lambda r: (r["same_dial"], r["name_similarity"]), reverse=True)
    return result[:3]


def record_event(kind, observed, last, **data):
    return {"type": kind, "first_detected_utc": observed,
            "last_confirmed_prior_utc": last,
            "time_accuracy": "observed between checks, not exact upstream change time",
            **data}


def compare(previous, now_ids, now_dials, at):
    """Generate both ID-centric movement and number-centric occupancy changes."""
    if not previous or not previous.get("last_successful_scan_utc"):
        return []
    before_ids = previous["channels_by_id"]
    before_dials = previous["dial_to_id"]
    last = previous["last_successful_scan_utc"]
    when = iso(at)
    events = []
    common = sorted(before_ids.keys() & now_ids.keys())
    for feed in common:
        past, current = before_ids[feed], now_ids[feed]
        if past["number"] != current["number"]:
            events.append(record_event(
                "feed_moved", when, last, id=feed, name=current["name"],
                old_number=past["number"], new_number=current["number"],
                previous_destination_occupant=before_dials.get(str(current["number"])),
                new_occupant_at_old_number=now_dials.get(str(past["number"]))))
        if past["name"] != current["name"] or past["callsign"] != current["callsign"]:
            events.append(record_event(
                "feed_renamed", when, last, id=feed, number=current["number"],
                old_name=past["name"], new_name=current["name"],
                old_callsign=past["callsign"], new_callsign=current["callsign"]))
    for number in sorted(set(before_dials) | set(now_dials), key=int):
        before, after = before_dials.get(number), now_dials.get(number)
        if before == after:
            continue
        events.append(record_event(
            "dial_changed", when, last, number=int(number), old_id=before,
            new_id=after,
            old_name=before_ids.get(before, {}).get("name") if before else None,
            new_name=now_ids.get(after, {}).get("name") if after else None,
            old_id_new_number=now_ids.get(before, {}).get("number") if before else None,
            new_id_previous_number=before_ids.get(after, {}).get("number") if after else None))
    gone = sorted(before_ids.keys() - now_ids.keys())
    added = [now_ids[id] for id in sorted(now_ids.keys() - before_ids.keys())]
    for feed in gone:
        old = before_ids[feed]
        events.append(record_event(
            "feed_disappeared", when, last, id=feed, name=old["name"],
            old_number=old["number"],
            dial_now_holds=now_dials.get(str(old["number"])),
            possible_new_ids=candidate_replacements(old, added, now_dials)))
    for item in added:
        events.append(record_event(
            "feed_appeared", when, last, id=item["id"], name=item["name"],
            number=item["number"],
            dial_previously_held=before_dials.get(str(item["number"]))))
    return events


def transition(state, history, lineup, when, min_count=20):
    current, dials = observe(lineup, minimum=min_count)
    previous = state or {}
    prev_ids = previous.get("channels_by_id", {})
    if prev_ids and len(current) < max(20 if min_count >= 20 else 1, int(len(prev_ids) * 0.65)):
        raise ValueError("Suspicious lineup collapse; preserving previous observation")
    changes = compare(previous, current, dials, when)
    when_utc = iso(when)
    local = when.astimezone(EASTERN)
    activity = dict(previous.get("checks_by_local_hour", {}))
    hour = str(local.weekday()) + ":" + str(local.hour)
    activity[hour] = activity.get(hour, 0) + 1
    day = local.date().isoformat()
    days = dict(previous.get("checks_by_local_day", {}))
    days[day] = days.get(day, 0) + 1
    new_state = {
        "schema": 1, "first_successful_scan_utc":
            previous.get("first_successful_scan_utc", when_utc),
        "last_successful_scan_utc": when_utc,
        "successful_scan_count": previous.get("successful_scan_count", 0) + 1,
        "total_feeds": len(current),
        "channels_by_id": current, "dial_to_id": dials,
        "checks_by_local_hour": activity, "checks_by_local_day": days,
        "last_scan_change_count": len(changes),
    }
    old_events = (history or {}).get("events", [])
    new_history = {"schema": 1, "events": old_events + changes}
    return new_state, new_history, changes


def save_json(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def scan(directory, dry_run=False):
    old_state_file = directory / "state.json"
    old_history_file = directory / "events.json"
    current_state = json.loads(old_state_file.read_text()) if old_state_file.is_file() else {}
    current_history = json.loads(old_history_file.read_text()) if old_history_file.is_file() else {"schema": 1, "events": []}
    now = dt.datetime.now(dt.timezone.utc)
    state, history, events = transition(current_state, current_history, get_lineup(), now)
    print("SCAN", iso(now), "| Eastern", now.astimezone(EASTERN).isoformat(timespec="seconds"),
          "| total feeds", state["total_feeds"], "| changes", len(events), flush=True)
    for item in events[:70]:
        print("CHANGE", json.dumps(item, ensure_ascii=False, separators=(",", ":")), flush=True)
    if len(events) > 70:
        print("CHANGE additional", len(events)-70, "events in history file", flush=True)
    if dry_run:
        print("DRY RUN: observation files unchanged", flush=True)
        return
    save_json(old_state_file, state)
    if events or not old_history_file.exists():
        save_json(old_history_file, history)
    print("SAVED observation at", state["last_successful_scan_utc"],
          "| total historical events", len(history["events"]), flush=True)


def self_test():
    t = dt.datetime(2026, 11, 18, 6, 0, tzinfo=dt.timezone.utc)
    original = [
        {"id": "njpw", "number": 1, "name": "NJPW", "callsign": "NJ"},
        {"id": "wwf", "number": 52, "name": "WWF", "callsign": "WWF"},
        {"id": "old-show", "number": 12, "name": "NJPW TV", "callsign": "NJTV"},
    ]
    one, h, events = transition({}, {}, original, t, min_count=0)
    assert not events and one["successful_scan_count"] == 1
    after = [
        {"id": "njpw", "number": 63, "name": "NJPW", "callsign": "NJ"},
        {"id": "wwf", "number": 52, "name": "WWF Classic", "callsign": "WWF"},
        {"id": "new-show", "number": 1, "name": "NJPW TV", "callsign": "NJTV"},
    ]
    two, h2, changes = transition(one, h, after, t + dt.timedelta(minutes=30), min_count=0)
    kinds = [x["type"] for x in changes]
    assert "feed_moved" in kinds and "feed_renamed" in kinds
    assert "feed_disappeared" in kinds and "feed_appeared" in kinds
    moved = next(x for x in changes if x["type"]=="feed_moved")
    assert (moved["id"], moved["old_number"], moved["new_number"]) == ("njpw", 1, 63)
    assert moved["last_confirmed_prior_utc"] == iso(t)
    switched = next(x for x in changes if x["type"]=="dial_changed" and x["number"]==1)
    assert (switched["old_id"], switched["new_id"]) == ("njpw","new-show")
    gone = next(x for x in changes if x["type"]=="feed_disappeared")
    assert gone["possible_new_ids"][0]["id"] == "new-show"
    assert not gone["possible_new_ids"][0]["verified"]
    three, h3, changes3 = transition(two, h2, after, t + dt.timedelta(hours=1), min_count=0)
    assert not changes3 and len(h3["events"]) == len(h2["events"])
    assert three["successful_scan_count"] == 3
    assert sum(three["checks_by_local_hour"].values()) == 3
    try:
        observe(original + [original[0]], minimum=0)
    except ValueError:
        pass
    else:
        raise AssertionError("Repeated feed must fail, not invent changes")
    try:
        observe([{"id": "a", "number": 1}, {"id": "b", "number": 1}],minimum=0)
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate dial must fail, not invent changes")
    print("PASS: initial baseline, first/last timing window, feed moves, dial replacement,"
          " disappeared/appeared related IDs, renames, no duplicate events, hourly sample stats")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--state-dir", default="tracking-state")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.scan:
        scan(pathlib.Path(args.state_dir), dry_run=args.dry_run)
    else:
        parser.error("Use --self-test or --scan")
