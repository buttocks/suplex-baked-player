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


def reconcile_alert(errors, warnings, summary, token):
    issue = open_incident(token)
    if errors:
        if issue:
            print("OUTAGE STILL OPEN: Issue #" + str(issue["number"]) +
                  "; duplicate notifications suppressed", flush=True)
            return 0
        body = (
            "The published GitHub Pages JSON is unhealthy. This monitor checks "
            "the 24 working SlamVision channels; it intentionally excludes 11 "
            "known missing/repurposed upstream feeds.\n\n"
            + "**Detected:** " + dt.datetime.now(dt.timezone.utc).isoformat() + "\n\n"
            + "**Summary:** " + summary + "\n\n"
            + "**Problems:**\n" +
            "\n".join("- " + p for p in errors[:50]) + "\n\n"
            + "**Warnings:**\n" +
            ("\n".join("- " + w for w in warnings[:30]) if warnings else "- None") +
            "\n\n"
            + "Investigate the refresh workflow and Pages deployment. "
            + "This issue will close after the monitor verifies recovery.\n"
        )
        created = github("POST", "/issues", token,
                         {"title": ISSUE_TITLE, "body": body, "assignees": ["buttocks"]})
        print("NEW OUTAGE: Opened issue #" + str(created["number"]) +
              " and failing this FIRST run to trigger a GitHub Actions email.", flush=True)
        return 1
    if issue:
        number = issue["number"]
        github("POST", "/issues/" + str(number) + "/comments", token, {
            "body": "Automatic recovery verified at " +
                    dt.datetime.now(dt.timezone.utc).isoformat() +
                    ". " + summary
        })
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
    print("PASS: 7 offline health-monitor scenarios")


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
    problems, warnings, summary = inspect(snapshots, time.time())
    errors.extend(problems)
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
