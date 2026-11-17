#!/usr/bin/env python3
"""Independent, resilient refresh of SlamVision's existing channel JSON snapshots."""
import concurrent.futures
import datetime
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "slamvision"
CATALOG = ROOT / "research" / "slamvision-current.json"
SAFE_FEED_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
BASE = "https://ring-channel-tv.emergent.host/api/"
TIMEOUT = 15
ATTEMPTS = 3
GROUPS = {
    "njpw": {"01": "njpw", "12": "njpw-tv",
             "64": "njpw-destructi", "65": "njpw-g1climax", "66": "njpw-starrcade",
             "67": "njpw-wp", "68": "njpw-wk", "69": "njpw-wrestling", "31": "ain"},
    "ajpw": {"05": "ajpw"},
    "joshi": {"11": "joshi"},
    "lucha": {"16": "100-lucha", "54": "lu-tv", "60": "cmll", "62": "aaa", "93": "universal-lucha-libre"},
    "roh": {"15": "roh-tv", "56": "croh"},
    "noah": {"20": "noah-tv"},
    "independent": {"22": "gcw-tv", "48": "death", "49": "czw-tv", "72": "pwg"},
    "dragongate": {"37": "dgtv"},
    "puro": {"43": "ddt", "44": "dream-graps", "46": "dramatic-graps", "47": "bjw",
             "33": "battlarts", "36": "big-japan", "52": "kaientai-dojo",
             "60": "michinoku-pro", "71": "osaka-pro", "82": "muta", "63": "fmw"},
    "shoot": {"29": "tsn", "32": "mma-tv"},
    "ecw": {"10": "ecw-tv", "30": "ecw-tv2"},
    "wwf": {"14": "wwf", "25": "wwe", "52": "wwf-90-00", "64": "wwwf"},
    "tna": {"17": "tna", "18": "tna-tv", "19": "iw"},
    "wcw": {"02": "wcw", "23": "wcw-tv", "31": "wcw-ppv"},
}

def shared_feed_ids(catalog=None):
    """Discover every active shared player not already backed up by a legacy group.

    The rolling catalog is already maintained by the independent six-hour
    lineup watcher. New feed IDs automatically enter this list next refresh.
    """
    if catalog is None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("channels"), list):
        raise RuntimeError("Missing or malformed current catalog; refusing to drop cached channels")
    existing = {source_id for group in GROUPS.values() for source_id in group.values()}
    feeds = {}
    seen = set()
    for item in catalog["channels"]:
        if not isinstance(item, dict):
            raise RuntimeError("Invalid catalog channel")
        ident = item.get("id")
        if not isinstance(ident, str) or not SAFE_FEED_ID.fullmatch(ident):
            raise RuntimeError("Unsafe or invalid catalog feed ID")
        if ident in seen:
            raise RuntimeError("Duplicate catalog feed ID: " + ident)
        seen.add(ident)
        if item.get("player_type") != "shared":
            continue
        if item.get("availability", "available") != "available" or ident in existing:
            continue
        feeds[ident] = ident
    if not feeds:
        raise RuntimeError("No active uncached shared feeds in catalog; preserving existing backup")
    return feeds

def planned_groups(catalog=None):
    # Keep the 14 established legacy group files and their embed URLs intact.
    # A 15th 'shared' group covers every remaining stable-ID player.
    return {**GROUPS, "shared": shared_feed_ids(catalog)}


def read(path):
    last = None
    for attempt in range(ATTEMPTS):
        try:
            request = urllib.request.Request(
                BASE + path,
                headers={"User-Agent": "Mozilla/5.0 (compatible; NJPW-Baked-Viewer/1.0)",
                         "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.load(response)
        except (OSError, ValueError) as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                break
            if attempt + 1 < ATTEMPTS:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError("Request failed for " + path + ": " + str(last))

def program(slot):
    if not slot:
        return None
    p = slot.get("program") or {}
    return {"title": p.get("title") or "Untitled program",
            "episode": p.get("episode") or "",
            "stream_url": p.get("stream_url") or "",
            "start": slot.get("start"), "end": slot.get("end"),
            "id": p.get("id") or "", "block": slot.get("block")}

def parse_time(value):
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None

def cached_if_active(category, dial, now, expected=None):
    """An old slot may be reused while CURRENT; never resurrect expired slots."""
    try:
        old = json.loads((OUT / (category + "-live.json")).read_text(encoding="utf-8"))
        item = old["channels"][dial]
        if expected is not None and item.get("id") != expected:
            return None
        slots = [item.get("current"), *(item.get("up_next") or [])]
        for slot in slots:
            if not isinstance(slot, dict) or not slot.get("stream_url"):
                continue
            start, end = parse_time(slot.get("start")), parse_time(slot.get("end"))
            if start is not None and end is not None and start <= now < end:
                return item
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None

def fetch_one(category, dial, expected, by_id, by_guide):
    # The stable feed ID identifies a broadcast. Upstream dial numbers are
    # presentation details and can be reassigned at any time.
    channel = by_id.get(expected)
    if not channel:
        raise RuntimeError("Original feed ID " + expected + " is missing upstream; cannot safely guess a replacement")
    actual = channel["id"]
    response = read("channels/" + urllib.parse.quote(str(actual), safe="") + "/now")
    # Never accept a different feed under a reused endpoint or alias.
    returned_id = (response.get("channel") or {}).get("id")
    if returned_id != expected:
        raise RuntimeError("Upstream returned " + str(returned_id) +
                           " instead of original feed " + expected)
    current = program(response.get("current"))
    if not current or not current["stream_url"]:
        raise RuntimeError("No playable current program for dial " + dial)
    end = parse_time(current.get("end"))
    if end is not None and end < time.time() - 60:
        raise RuntimeError("Upstream program already expired for dial " + dial)
    return {
        "id": actual, "name": channel.get("name") or expected,
        "current": current,
        "up_next": [program(slot) for slot in (response.get("up_next") or [])[:8]],
        "guide": [program(slot) for slot in
                  (by_guide.get(actual, {}).get("slots") or [])],
        "server_time": response.get("server_time"),
    }

def build_index(channels):
    # Exact stable IDs only. A title/name resemblance must never silently
    # substitute an unrelated wrestling feed.
    if not isinstance(channels, list):
        raise RuntimeError("Invalid upstream channel list")
    result = {}
    duplicates = set()
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        ident = channel.get("id")
        if not isinstance(ident, str) or not ident:
            continue
        if ident in result:
            duplicates.add(ident)
        else:
            result[ident] = channel
    # Ambiguous IDs cannot be trusted.
    for ident in duplicates:
        result.pop(ident, None)
    return result


def main():
    channels = read("channels")
    by_id = build_index(channels)
    try:
        guide = read("guide?hours=4")
        by_guide = {x["channel"]["id"]: x for x in guide.get("rows", [])
                    if isinstance(x, dict) and isinstance(x.get("channel"), dict)
                    and x["channel"].get("id")}
    except Exception as exc:
        print("WARNING: TV guide unavailable: " + str(exc), flush=True)
        by_guide = {}

    groups = planned_groups()
    tasks = [(group, dial, expected) for group, dials in groups.items()
             for dial, expected in dials.items()]
    snapshots = {group: {} for group in groups}
    problems = []
    fresh = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
        pending = {pool.submit(fetch_one, group, dial, expected, by_id, by_guide):
                   (group, dial, expected)
                   for group, dial, expected in tasks}
        for future in concurrent.futures.as_completed(pending):
            group, dial, expected = pending[future]
            try:
                result = future.result()
                snapshots[group][dial] = result
                fresh += 1
                upstream = by_id.get(expected, {}).get("number")
                moved = (" (upstream dial " + str(upstream) + ")") if upstream is not None and str(upstream).zfill(2) != dial else ""
                print("OK CH " + dial + " " + result["id"] + moved, flush=True)
            except Exception as exc:
                problems.append("CH " + dial + " (" + expected + "): " + str(exc))

    # Preserve only still-current fallbacks, never an expired program.
    used_cache = 0
    now = time.time()
    for group, dials in groups.items():
        for dial, expected in dials.items():
            if dial not in snapshots[group]:
                cached = cached_if_active(group, dial, now, expected)
                if cached:
                    snapshots[group][dial] = cached
                    used_cache += 1
                    print("CACHE CH " + dial + " (still active)", flush=True)

    if fresh == 0:
        raise RuntimeError("All upstream channels unavailable; existing snapshots preserved. "
                           + "; ".join(problems[:4]))

    OUT.mkdir(parents=True, exist_ok=True)
    stamped = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for group in groups:
        if not snapshots[group]:
            print("WARNING: " + group + " has no available channels; old file preserved", flush=True)
            continue
        path = OUT / (group + "-live.json")
        path.write_text(json.dumps(
            {"generated_at": stamped, "channels": snapshots[group]},
            ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for problem in problems:
        print("WARNING " + problem, flush=True)
    print("Shared feed backup coverage: " + str(len(groups["shared"])) + " catalog feeds", flush=True)
    print("Refreshed " + str(fresh) + "/" + str(len(tasks)) +
          " channels; " + str(used_cache) + " cached; " +
          str(len(problems)) + " unavailable", flush=True)

if __name__ == "__main__":
    main()
