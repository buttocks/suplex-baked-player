#!/usr/bin/env python3
"""Read-only health monitor for every active SlamVision feed in the rolling catalog.

All channel IDs are handled equally. Stable IDs, not changing upstream dials,
identify the feed; legacy player pages and shared embeds use the same checks.
"""
import argparse
import concurrent.futures
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

PAGES_ROOT = "https://buttocks.github.io/suplex-baked-player/"
PAGE_ROOT = PAGES_ROOT + "slamvision/"
CATALOG_URL = PAGES_ROOT + "research/slamvision-current.json"
LOCAL_CATALOG = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "research", "slamvision-current.json")
REPO = "buttocks/suplex-baked-player"
ISSUE_TITLE = "[SlamVision] Published schedules need attention"
EARLY_RISK_AFTER_SECONDS = 7 * 60
EARLY_RISK_HORIZON_SECONDS = 10 * 60
STALE_AFTER_SECONDS = 12 * 60
USER_AGENT = "SlamVision-Health-Monitor/2.0"
GROUPS = ("njpw", "ajpw", "joshi", "lucha", "roh", "noah", "independent",
          "dragongate", "puro", "shoot", "ecw", "wwf", "tna", "wcw", "shared")


def iso_to_seconds(value):
    if not value or not isinstance(value, str):
        return None
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return stamp.timestamp()
    except (ValueError, OverflowError):
        return None


def get_json(url, token=None):
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers.update({
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
        })
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=13) as result:
        return json.load(result)


def fetch_group(name):
    # The timestamp bypasses an old browser/CDN cache; the file is still on Pages.
    url = PAGE_ROOT + name + "-live.json?check=" + str(int(time.time()))
    last = None
    for attempt in range(2):
        try:
            return name, get_json(url), None
        except (OSError, ValueError) as exc:
            last = str(exc)
            if attempt == 0:
                time.sleep(1.5)
    return name, None, last


def covered_until(channel, now):
    """Find continuous playback coverage from now (allow <= 1s timestamp roundoff)."""
    raw = [channel.get("current"), *(channel.get("up_next") or [])]
    slots = []
    for obj in raw:
        if not isinstance(obj, dict) or not obj.get("stream_url"):
            continue
        start, end = iso_to_seconds(obj.get("start")), iso_to_seconds(obj.get("end"))
        if start is not None and end is not None and end > start:
            slots.append((start, end))
    slots.sort()
    active = [end for start, end in slots if start <= now < end]
    if not active:
        return None
    until = max(active)
    for start, end in slots:
        if start > until + 1:
            break
        if end > until:
            until = end
    return until



def fetch_direct_coverage(source_id, now):
    """Check the same browser-accessible upstream endpoint used by the player."""
    from urllib.parse import quote
    url = ("https://ring-channel-tv.emergent.host/api/channels/" +
           quote(source_id, safe="") + "/now")
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={
                "Origin": "https://buttocks.github.io",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            })
            with urllib.request.urlopen(req, timeout=12) as response:
                allow = response.headers.get("Access-Control-Allow-Origin")
                if allow not in ("*", "https://buttocks.github.io"):
                    raise RuntimeError("Upstream browser CORS access is unavailable")
                raw = json.load(response)
            if raw.get("channel", {}).get("id") != source_id:
                raise RuntimeError("Upstream returned the wrong feed")
            def program(slot):
                if not isinstance(slot, dict):
                    return None
                p = slot.get("program") or {}
                return {"start": slot.get("start"), "end": slot.get("end"),
                        "stream_url": p.get("stream_url") or ""}
            candidate = {
                "current": program(raw.get("current")),
                "up_next": [program(slot) for slot in (raw.get("up_next") or [])[:8]],
            }
            until = covered_until(candidate, now)
            if until is None:
                raise RuntimeError("No playable program from live upstream")
            return until
        except (OSError, ValueError, RuntimeError) as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                break
            if attempt == 0:
                time.sleep(1.5)
    raise RuntimeError(str(last))



def active_catalog(raw):
    """Validate and return ALL currently active stable IDs, without player tiers."""
    import re
    if not isinstance(raw, dict) or not isinstance(raw.get("channels"), list):
        raise ValueError("Malformed channel catalog")
    active = []
    seen = set()
    for row in raw["channels"]:
        if not isinstance(row, dict):
            raise ValueError("Malformed catalog channel")
        if row.get("availability", "available") != "available":
            continue
        ident = row.get("id")
        url = row.get("embed_url")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,90}", ident):
            raise ValueError("Unsafe active channel ID: " + str(ident))
        if ident in seen:
            raise ValueError("Duplicate active channel ID: " + ident)
        if not isinstance(url, str) or not url.startswith(PAGES_ROOT):
            raise ValueError("Missing or invalid embed URL: " + ident)
        seen.add(ident)
        active.append({"id": ident, "name": str(row.get("name") or ident),
                       "embed_url": url})
    if len(active) < 35:
        raise ValueError("Suspicious active channel count: " + str(len(active)))
    if raw.get("total") is not None and int(raw["total"]) != len(active):
        raise ValueError("Active catalog total disagrees with channel list")
    return active


def load_active_catalog():
    """Prefer the published catalog; preserve local inventory during a Pages outage."""
    local = None
    local_error = None
    try:
        with open(LOCAL_CATALOG, encoding="utf-8") as fh:
            local = active_catalog(json.load(fh))
    except (OSError, ValueError, TypeError) as exc:
        local_error = str(exc)
    try:
        published = active_catalog(get_json(CATALOG_URL + "?check=" + str(int(time.time()))))
        # Guard against a temporarily partial Pages deployment dropping monitoring.
        if local is not None and len(published) < int(len(local) * 0.65):
            raise ValueError("Published catalog unexpectedly shrank to " +
                             str(len(published)) + " active feeds")
        return published, []
    except (OSError, ValueError, TypeError) as exc:
        if local is None:
            raise RuntimeError("No valid published or local channel catalog: " +
                               str(exc) + "; local: " + str(local_error)) from exc
        return local, ["Published catalog unavailable or incomplete; using checked-out " +
                       "active inventory (" + str(len(local)) + " feeds): " + str(exc)]


def inspect_all(snapshots, active, now, fetch_live=None):
    """Every active ID gets identical cache/fallback/coverage validation."""
    live = fetch_live or fetch_direct_coverage
    ids = {item["id"] for item in active}
    by_id = {}
    duplicate_ids = set()
    stale_groups = 0
    for group in GROUPS:
        snapshot = snapshots.get(group)
        if not isinstance(snapshot, dict):
            stale_groups += 1
            continue
        stamp = iso_to_seconds(snapshot.get("generated_at"))
        age = now - stamp if stamp is not None else float("inf")
        if age > STALE_AFTER_SECONDS or age < -180:
            stale_groups += 1
        entries = snapshot.get("channels")
        if not isinstance(entries, dict):
            continue
        for dial, item in entries.items():
            if not isinstance(item, dict) or item.get("id") not in ids:
                continue
            ident = item["id"]
            previous = by_id.get(ident)
            if previous is not None:
                duplicate_ids.add(ident)
            # Prefer the latest matching ID snapshot, not a potentially reassigned dial.
            if previous is None or age < previous[1]:
                by_id[ident] = (item, age)

    tasks = []
    cached = {}
    for channel in active:
        ident = channel["id"]
        item, age = by_id.get(ident, (None, float("inf")))
        until = covered_until(item, now) if item else None
        cached[ident] = until
        if (until is None or age > STALE_AFTER_SECONDS or age < -180 or
                until - now < EARLY_RISK_HORIZON_SECONDS):
            tasks.append(ident)

    live_results = {}
    if tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            futures = {pool.submit(live, ident, now): ident for ident in tasks}
            for future in concurrent.futures.as_completed(futures):
                ident = futures[future]
                try:
                    live_results[ident] = (future.result(), None)
                except Exception as exc:
                    live_results[ident] = (None, str(exc))

    errors, warnings = [], []
    if duplicate_ids:
        warnings.append("Duplicate cache snapshots for " +
                        ", ".join(sorted(duplicate_ids)[:10]) +
                        "; selected latest matching stable IDs")
    playable, direct_count, shortest = 0, 0, None
    for channel in active:
        ident, name = channel["id"], channel["name"]
        until = cached[ident]
        upstream_until, upstream_error = live_results.get(ident, (None, None))
        if upstream_until is not None:
            direct_count += 1
        coverage = max((value for value in (until, upstream_until) if value is not None),
                       default=None)
        if coverage is None:
            errors.append(name + " (" + ident +
                          "): no playable published schedule or direct upstream" +
                          (": " + upstream_error if upstream_error else ""))
            continue
        playable += 1
        remaining = coverage - now
        shortest = remaining if shortest is None else min(shortest, remaining)
        if upstream_error:
            if remaining < EARLY_RISK_HORIZON_SECONDS:
                errors.append(name + " (" + ident +
                              "): live upstream unreachable and cached show ends in " +
                              str(round(remaining / 60, 1)) + "m")
            else:
                warnings.append(name + " (" + ident +
                                "): live upstream unavailable; cached program covers " +
                                str(round(remaining / 60, 1)) + "m")

    if playable != len(active) and not errors:
        errors.append("Channel coverage count mismatch")
    if stale_groups and not errors:
        warnings.append("Some published schedule files are delayed; checked upstream " +
                        "where required.")
    summary = ("Playable channels " + str(playable) + "/" + str(len(active)) +
               " | direct API verified " + str(direct_count) + "/" + str(len(tasks)) +
               " probed | stale/missing Pages groups " + str(stale_groups) +
               "/" + str(len(GROUPS)) + " | shortest remaining " +
               ("unknown" if shortest is None else str(round(shortest / 60, 1)) + "m"))
    return errors, warnings, summary


def github(method, path, token, payload=None):
    url = "https://api.github.com/repos/" + REPO + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": USER_AGENT,
                 **({"Content-Type": "application/json"} if data else {})},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def open_incident(token):
    issues = github("GET", "/issues?state=open&per_page=100", token)
    return next((i for i in issues if i.get("title") == ISSUE_TITLE
                 and "pull_request" not in i), None)


def github_dispatch_refresh(token):
    """Request main's refresh workflow (204 No Content on success)."""
    url = ("https://api.github.com/repos/" + REPO +
           "/actions/workflows/refresh-njpw-slamvision.yml/dispatches")
    request = urllib.request.Request(
        url, data=json.dumps({"ref": "main"}).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 204:
            raise RuntimeError("Refresh dispatch returned HTTP " + str(response.status))


def latest_refresh_runs(token):
    result = github(
        "GET",
        "/actions/workflows/refresh-njpw-slamvision.yml/runs?branch=main&per_page=15",
        token)
    return result.get("workflow_runs", [])


def should_dispatch(runs, now):
    """Avoid a storm of recovery jobs; don't shadow a recently successful schedule job."""
    recent_manual = False
    newest_age = None
    newest_result = None
    for run in runs:
        created = iso_to_seconds(run.get("created_at"))
        if created is None:
            continue
        age = now - created
        if run.get("event") == "workflow_dispatch" and -60 <= age < 15 * 60:
            recent_manual = True
        if newest_age is None or age < newest_age:
            newest_age = age
            newest_result = run
    # A recent scheduled refresh should be allowed to publish. A recent manual
    # recovery attempt is the dedupe state, not a reason to keep alerts silent.
    recently_refreshing = (
        newest_result is not None and newest_age is not None and
        -60 <= newest_age < 7 * 60 and
        newest_result.get("status") in ("queued", "pending", "in_progress"))
    recent_success = (
        newest_result is not None and newest_age is not None and
        -60 <= newest_age < 10 * 60 and
        newest_result.get("conclusion") == "success")
    # Don't hide a real Pages deployment failure indefinitely behind a steady
    # stream of successful refresh jobs. Only grant a 90-second deploy grace.
    deploy_grace = recent_success and newest_age < 90
    return (not recent_manual and not recently_refreshing and not recent_success,
            recent_manual, recently_refreshing or deploy_grace)


def reconcile_alert(errors, warnings, summary, token):
    issue = open_incident(token)
    if errors:
        auto_repair_requested = False
        wait_for_refresh = False
        try:
            now = time.time()
            runs = latest_refresh_runs(token)
            dispatch, recent_manual, just_refreshed = should_dispatch(runs, now)
            if dispatch:
                github_dispatch_refresh(token)
                auto_repair_requested = True
                print("AUTO-REPAIR: Requested a main-branch schedule refresh.", flush=True)
            elif just_refreshed:
                wait_for_refresh = True
                print("AUTO-REPAIR: Recent refresh is running or deploying.", flush=True)
            elif recent_manual:
                print("AUTO-REPAIR: Recovery already requested recently.", flush=True)
        except Exception as exc:
            print("WARNING: Automatic refresh request failed: " + str(exc), flush=True)

        if issue:
            print("OUTAGE STILL OPEN: Issue #" + str(issue["number"]) +
                  "; no duplicate notifications.", flush=True)
            return 0
        if auto_repair_requested or wait_for_refresh:
            print("EARLY WARNING: Holding the first notification while recovery runs.", flush=True)
            return 0

        body = (
            "The published GitHub Pages JSON needs attention. This monitor watches every feed marked active in the rolling "
            "SlamVision catalog, without distinguishing old and new embeds.\n\n"
            + "**Detected:** " + dt.datetime.now(dt.timezone.utc).isoformat() + "\n\n"
            + "**Summary:** " + summary + "\n\n"
            + "**Problems:**\n" +
            "\n".join("- " + p for p in errors[:50]) + "\n\n"
            + "**Warnings:**\n" +
            ("\n".join("- " + w for w in warnings[:30]) if warnings else "- None") +
            "\n\n"
            + "The monitor has already checked for recent refresh jobs. "
            + "It will close this issue after verifying recovery.\n"
        )
        # Creating an issue produces a single GitHub issue notification for
        # subscribers. Do not also assign the owner or fail the workflow.
        created = github("POST", "/issues", token,
                         {"title": ISSUE_TITLE, "body": body})
        print("NEW OUTAGE: Opened issue #" + str(created["number"]) +
              " (no assignment, no intentional Actions failure).", flush=True)
        return 0
    if issue:
        number = issue["number"]
        # Close without posting an extra comment/email.
        github("PATCH", "/issues/" + str(number), token, {"state": "closed"})
        print("RECOVERED: Closed issue #" + str(number), flush=True)
    return 0


def self_test():
    """Offline regression tests, including 125 equal-priority live channels."""
    now = 1_800_000_000
    def stamp(value):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()
    active = [{"id": "test-feed-" + str(i), "name": "Channel " + str(i),
               "embed_url": PAGES_ROOT + "slamvision-feed.html?id=test-feed-" + str(i)}
              for i in range(125)]
    doc = {"total": len(active), "channels": [
        {"id": x["id"], "name": x["name"], "embed_url": x["embed_url"],
         "availability": "available"} for x in active]}
    assert len(active_catalog(doc)) == 125
    doc["channels"].append({"id": "offline", "availability": "temporarily_missing"})
    assert len(active_catalog(doc)) == 125
    try:
        active_catalog({"total": 125, "channels": doc["channels"] + [doc["channels"][0]]})
    except ValueError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("Duplicate active ID accepted")
    def fixture(age=120, duration=3600):
        data = {g: {"generated_at": stamp(now-age), "channels": {}} for g in GROUPS}
        for index, channel in enumerate(active):
            group = GROUPS[index % len(GROUPS)]
            data[group]["channels"][str(index)] = {
                "id": channel["id"],
                "current": {"start": stamp(now-100), "end": stamp(now+duration),
                            "stream_url": "https://archive.org/stream.mp4"},
                "up_next": []}
        return data
    calls = []
    def live_ok(ident, at):
        calls.append(ident)
        return at+3600
    def live_down(ident, at):
        calls.append(ident)
        raise RuntimeError("upstream unavailable")
    errors, _, summary = inspect_all(fixture(), active, now, live_down)
    assert not errors and "125/125" in summary and not calls
    stale = fixture(age=3600, duration=-1)
    calls.clear()
    assert not inspect_all(stale, active, now, live_ok)[0] and len(calls) == 125
    calls.clear()
    assert len(inspect_all(stale, active, now, live_down)[0]) == 125
    data = fixture()
    data[GROUPS[0]]["channels"].pop("0")
    calls.clear()
    assert not inspect_all(data, active, now, live_ok)[0] and calls == [active[0]["id"]]
    data = fixture()
    data[GROUPS[0]]["channels"]["0"]["id"] = "wrong-channel"
    calls.clear()
    assert not inspect_all(data, active, now, live_ok)[0] and calls == [active[0]["id"]]
    data = fixture(age=3600, duration=240)
    assert len(inspect_all(data, active, now, live_down)[0]) == 125
    data = fixture(age=3600, duration=3600)
    assert not inspect_all(data, active, now, live_down)[0]
    def fake_run(age, event="schedule", status="completed", conclusion="success"):
        return {"created_at": stamp(now - age), "event": event,
                "status": status, "conclusion": conclusion}
    assert should_dispatch([fake_run(40)], now) == (False, False, True)
    assert should_dispatch([fake_run(180)], now) == (False, False, False)
    assert should_dispatch([fake_run(700)], now)[0]
    assert should_dispatch([fake_run(300, "workflow_dispatch")], now)[1]
    print("PASS: 125 equal-priority channels, dynamic catalog, stable IDs, "
          "missing caches, upstream recovery, expiration and alert dedupe")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Inspect live sources; never mutate GitHub")
    parser.add_argument("--alert", action="store_true",
                        help="Open/close one incident for all active feeds")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not (args.dry_run or args.alert):
        parser.error("Use --dry-run or --alert")
    try:
        active, catalog_warnings = load_active_catalog()
    except Exception as exc:
        active, catalog_warnings = [], []
        errors = ["Catalog cannot be verified: " + str(exc)]
    else:
        errors = []
    snapshots = {}
    fetch_errors = []
    if active:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for category, data, error in pool.map(fetch_group, GROUPS):
                if error:
                    fetch_errors.append(category + ": " + error)
                elif not isinstance(data, dict):
                    fetch_errors.append(category + ": invalid JSON response")
                else:
                    snapshots[category] = data
        problems, warnings, summary = inspect_all(snapshots, active, time.time())
        errors.extend(problems)
    else:
        warnings, summary = [], "Playable channels 0/unknown; catalog unavailable"
    warnings.extend(catalog_warnings)
    warnings.extend("Pages fetch: " + issue for issue in fetch_errors)
    print("MONITOR: " + summary)
    for warning in warnings:
        print("NOTICE: " + warning)
    for error in errors:
        print("ALERT: " + error)
    print("RESULT: " + ("UNHEALTHY (" + str(len(errors)) + " findings)" if errors else "HEALTHY"))
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write("## SlamVision all-active-feed monitor\n\n" + summary + "\n\n")
            handle.write("**Status:** " + ("UNHEALTHY" if errors else "HEALTHY") + "\n\n")
            if errors:
                handle.write("\n".join("- " + e for e in errors[:80]) + "\n\n")
            if warnings:
                handle.write("\n".join("- Note: " + w for w in warnings[:30]) + "\n")
    if args.dry_run:
        print("DRY RUN: No issues created or modified.")
        return 0
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN missing, cannot manage incident state.", file=sys.stderr)
        return 1
    try:
        return reconcile_alert(errors, warnings, summary, token)
    except Exception as exc:
        print("ERROR: Incident tracking failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
