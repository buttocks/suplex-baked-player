#!/usr/bin/env python3
"""Read-only SlamVision Pages health monitor, with one GitHub issue per outage.

Check the live GitHub Pages JSON, not merely the repo's newest commit.
Expected channels are the 24 independently verified working on 2026-11-16.
The 11 legacy missing/reassigned channels are excluded until deliberately restored.
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

PAGE_ROOT = "https://buttocks.github.io/suplex-baked-player/slamvision/"
REPO = "buttocks/suplex-baked-player"
ISSUE_TITLE = "[SlamVision] Published schedules need attention"
EARLY_RISK_AFTER_SECONDS = 7 * 60
EARLY_RISK_HORIZON_SECONDS = 10 * 60
STALE_AFTER_SECONDS = 12 * 60
USER_AGENT = "SlamVision-Health-Monitor/1.0"
EXPECTED = {
    "njpw": {"01": "njpw"},
    "ajpw": {"05": "ajpw"},
    "joshi": {"11": "joshi"},
    "lucha": {"16": "100-lucha", "54": "lu-tv"},
    "roh": {"15": "roh-tv", "56": "croh"},
    "noah": {"20": "noah-tv"},
    "independent": {"22": "gcw-tv", "48": "death", "49": "czw-tv", "72": "pwg"},
    "dragongate": {"37": "dgtv"},
    "puro": {"47": "bjw"},
    "shoot": {"29": "tsn", "32": "mma-tv"},
    "ecw": {"10": "ecw-tv"},
    "wwf": {"14": "wwf", "25": "wwe", "52": "wwf-90-00", "64": "wwwf"},
    "tna": {"17": "tna", "19": "iw"},
    "wcw": {"02": "wcw"},
}
EXPECTED_COUNT = 24


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


def inspect_with_browser_fallback(snapshots, now, fetch_live=None):
    """Alert only if both Pages and the real browser fallback are insufficient.

    The original inspect() is retained for baseline regression tests. The
    production monitor uses this full availability check after the player
    acquired direct browser fallback support.
    """
    live = fetch_live or fetch_direct_coverage
    watched = [(group, dial, source_id)
               for group, channels in EXPECTED.items()
               for dial, source_id in channels.items()]
    cached = {}
    tasks = []
    stale_groups = 0
    for group in EXPECTED:
        group_data = snapshots.get(group) or {}
        stamp = iso_to_seconds(group_data.get("generated_at"))
        age = now - stamp if stamp is not None else float("inf")
        if age > STALE_AFTER_SECONDS or age < -180:
            stale_groups += 1
        entries = group_data.get("channels") or {}
        for dial, source_id in EXPECTED[group].items():
            item = entries.get(dial) if isinstance(entries, dict) else None
            if not isinstance(item, dict) or item.get("id") != source_id:
                item = None
            until = covered_until(item, now) if item else None
            cached[(group, dial)] = (until, age)
            # A recently refreshed, fully current Pages show needs no probe.
            if until is None or age > STALE_AFTER_SECONDS or age < -180 or until - now < EARLY_RISK_HORIZON_SECONDS:
                tasks.append((group, dial, source_id))
    live_results = {}
    if tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
            futures = {pool.submit(live, source_id, now): (group, dial)
                       for group, dial, source_id in tasks}
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    live_results[key] = (future.result(), None)
                except Exception as exc:
                    live_results[key] = (None, str(exc))
    errors, warnings = [], []
    playable = 0
    direct_count = 0
    shortest = None
    for group, dial, source_id in watched:
        until, age = cached[(group, dial)]
        upstream_until, upstream_error = live_results.get((group, dial), (None, None))
        coverage = max(x for x in (until, upstream_until) if x is not None) if (
            until is not None or upstream_until is not None) else None
        if upstream_until is not None:
            direct_count += 1
        if coverage is None:
            errors.append("CH " + dial + " (" + source_id +
                          "): no playable Pages slot AND direct upstream failed" +
                          (": " + upstream_error if upstream_error else ""))
            continue
        playable += 1
        remaining = coverage - now
        shortest = remaining if shortest is None else min(shortest, remaining)
        if upstream_error:
            if remaining < EARLY_RISK_HORIZON_SECONDS:
                errors.append("CH " + dial + " (" + source_id +
                              "): live upstream unreachable and cached show ends in " +
                              str(round(remaining / 60, 1)) + "m")
            else:
                warnings.append("CH " + dial + " (" + source_id +
                                "): live upstream unavailable; saved program still covers " +
                                str(round(remaining / 60, 1)) + "m")
    if len(watched) != EXPECTED_COUNT:
        errors.append("Monitor watchlist count changed unexpectedly")
    summary = ("Playable channels " + str(playable) + "/" + str(EXPECTED_COUNT) +
               " | verified via direct API " + str(direct_count) +
               " | stale Pages groups " + str(stale_groups) + "/" + str(len(EXPECTED)) +
               " | shortest remaining " +
               ("unknown" if shortest is None else str(round(shortest / 60, 1)) + "m"))
    if stale_groups and not errors:
        warnings.append("GitHub Pages JSON is delayed, but the client-side live API fallback is playable.")
    return errors, warnings, summary


def inspect(snapshots, now):
    """Return (problems, warnings, summary) from already-loaded channel snapshots."""
    errors, warnings = [], []
    fresh = 0
    youngest = None
    shortest = None
    for category, watched in EXPECTED.items():
        data = snapshots.get(category)
        if not isinstance(data, dict):
            errors.append(category + ": no published JSON / network failure")
            continue
        gen = iso_to_seconds(data.get("generated_at"))
        if gen is None:
            errors.append(category + ": missing/invalid generated_at")
            continue
        age = now - gen
        if age < -180:
            errors.append(category + ": schedule timestamp is in the future")
        if age > STALE_AFTER_SECONDS:
            errors.append(category + ": published schedule " + str(round(age / 60, 1)) + "m old (threshold 12m)")
        if youngest is None or age > youngest:
            youngest = age
        channels = data.get("channels")
        if not isinstance(channels, dict):
            errors.append(category + ": malformed channels object")
            continue
        for dial, expected_id in watched.items():
            item = channels.get(dial)
            if not isinstance(item, dict):
                errors.append("CH " + dial + " (" + expected_id + ") missing from " + category)
                continue
            if item.get("id") != expected_id:
                errors.append("CH " + dial + " changed from " + expected_id + " to " + str(item.get("id")))
                continue
            until = covered_until(item, now)
            if until is None:
                errors.append("CH " + dial + " (" + expected_id + ") has no playable program RIGHT NOW")
                continue
            fresh += 1
            remaining = until - now
            shortest = remaining if shortest is None else min(shortest, remaining)
            # Short windows are normal *if the refresh is fresh*.
            if remaining < EARLY_RISK_HORIZON_SECONDS:
                if age >= EARLY_RISK_AFTER_SECONDS:
                    errors.append("CH " + dial + " (" + expected_id + ") expires in " +
                                  str(round(remaining / 60, 1)) + "m; update already " +
                                  str(round(age / 60, 1)) + "m old")
                else:
                    warnings.append("CH " + dial + " (" + expected_id + ") only " +
                                    str(round(remaining / 60, 1)) + "m covered; upstream refresh expected")
    if sum(map(len, EXPECTED.values())) != EXPECTED_COUNT:
        errors.append("Monitor configuration count changed unexpectedly")
    summary = ("Playable channels " + str(fresh) + "/" + str(EXPECTED_COUNT) +
               " | oldest snapshot " +
               ("unknown" if youngest is None else str(round(youngest / 60, 1)) + "m") +
               " | shortest remaining " +
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
            "The published GitHub Pages JSON needs attention. This monitor watches "
            "24 working SlamVision channels, excluding 11 known missing or reassigned "
            "upstream feeds.\n\n"
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
    # Deterministic fixture cases, no network and no GitHub writes.
    now = 1_800_000_000
    def fmt(sec):
        return dt.datetime.fromtimestamp(sec, dt.timezone.utc).isoformat()
    def fixture(age=120, coverage=3600):
        return {group: {
            "generated_at": fmt(now - age),
            "channels": {dial: {"id": ident, "current": {
                "stream_url": "https://archive.org/test.mp4",
                "start": fmt(now - 100), "end": fmt(now + coverage)},
                "up_next": []}
                for dial, ident in watches.items()}
            } for group, watches in EXPECTED.items()}
    data = fixture()
    assert not inspect(data, now)[0], "Healthy snapshots should pass"
    data = fixture(age=900)
    assert any("12m" in p for p in inspect(data, now)[0]), "Stale data must alert"
    data = fixture(age=480, coverage=360)
    assert any("expires" in p for p in inspect(data, now)[0]), "Early expiry must alert"
    data = fixture(age=120, coverage=360)
    assert not inspect(data, now)[0], "Fresh short schedules should not alarm"
    data = fixture()
    data["wwf"]["channels"].pop("52")
    assert any("CH 52" in p for p in inspect(data, now)[0]), "Missing working channel must alert"
    data = fixture()
    data["wwf"]["channels"]["52"]["id"] = "wrong-feed"
    assert any("changed" in p for p in inspect(data, now)[0]), "Misassigned channel must alert"
    data = fixture()
    data["wwf"]["channels"]["52"]["current"]["end"] = fmt(now - 1)
    assert any("RIGHT NOW" in p for p in inspect(data, now)[0]), "No current slot must alert"
    # Avoid false silence when refresh itself succeeds but GitHub Pages stays stale.
    def fake_run(age, event="schedule", status="completed", conclusion="success"):
        return {"created_at": fmt(now - age), "event": event,
                "status": status, "conclusion": conclusion}
    assert should_dispatch([fake_run(40)], now) == (False, False, True)
    assert should_dispatch([fake_run(180)], now) == (False, False, False)
    assert should_dispatch([fake_run(700)], now)[0]
    assert should_dispatch([fake_run(300, "workflow_dispatch")], now)[1]
    # Browser-aware tests: old Pages data is not an outage if direct API works.
    stale = fixture(age=3600, coverage=-60)
    def live_ok(source_id, at):
        return at + 3600
    def live_down(source_id, at):
        raise RuntimeError("API offline")
    assert not inspect_with_browser_fallback(stale, now, live_ok)[0], "Live API should recover stale Pages"
    assert len(inspect_with_browser_fallback(stale, now, live_down)[0]) == EXPECTED_COUNT, "Both sources unavailable must alert"
    current_stale = fixture(age=3600, coverage=3600)
    assert not inspect_with_browser_fallback(current_stale, now, live_down)[0], "Cached current shows are still playable"
    nearly_ended = fixture(age=3600, coverage=240)
    assert any("ends in" in x for x in inspect_with_browser_fallback(nearly_ended, now, live_down)[0]), "Warn before losing last playable cached show"
    assert not inspect_with_browser_fallback(fixture(age=60), now, live_down)[0], "Fresh Pages should not require live API"
    print("PASS: 16 offline health-monitor scenarios")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read live Pages and report only; never mutate GitHub")
    parser.add_argument("--alert", action="store_true",
                        help="Open/close one issue per incident; fail on first alert only")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not (args.dry_run or args.alert):
        parser.error("Use --dry-run or --alert")
    snapshots = {}
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        for category, data, error in pool.map(fetch_group, EXPECTED):
            if error:
                errors.append(category + ": " + error)
            elif not isinstance(data, dict):
                errors.append(category + ": invalid JSON response")
            else:
                snapshots[category] = data
    problems, warnings, summary = inspect_with_browser_fallback(snapshots, time.time())
    # Pages outages are informational when direct fallback proves playable.
    warnings.extend('Pages fetch: ' + error for error in errors)
    errors = problems
    print("MONITOR: " + summary)
    for warning in warnings:
        print("NOTICE: " + warning)
    for error in errors:
        print("ALERT: " + error)
    print("RESULT: " + ("UNHEALTHY (" + str(len(errors)) + " findings)" if errors else "HEALTHY"))
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write("## SlamVision published schedule check\n\n" + summary + "\n\n")
            handle.write("**Status:** " + ("UNHEALTHY" if errors else "HEALTHY") + "\n\n")
            handle.write("\n".join("- " + e for e in errors[:50]) + "\n\n" if errors else "")
            handle.write("\n".join("- Note: " + w for w in warnings[:30]) + "\n" if warnings else "")
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
