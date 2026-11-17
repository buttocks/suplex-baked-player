#!/usr/bin/env python3
"""Patch the 34 legacy SlamVision iframe pages without changing their embed URLs."""
import argparse
import pathlib
import re
import subprocess
from sync_slamvision import GROUPS

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAYER_FILES = sorted(ROOT.glob("*-slamvision.html"))
COUNT = 34
OLD_FETCH = re.compile(
    r"  // Same-origin cached API data avoids cross-site CORS restrictions\.\n"
    r"  const response=await fetch\('\./slamvision/([a-z]+)-live\.json\?t='\+Date\.now\(\),\{cache:'no-store'\}\);\n"
    r"  if\(!response\.ok\)throw Error\('Schedule returned '\+response\.status\);\n"
    r"  const next=await response\.json\(\);\n"
)
KEY = re.compile(r"const key='baked-([a-z]+)-'\+channel\+'-';")
SIMPLE = re.compile(r"const channel='([0-9]{2})';")
SRC = '<script src="./slamvision-direct-fallback.js"></script>\n'


def inspect(path):
    data = path.read_text(encoding="utf-8")
    group = KEY.search(data)
    if not group:
        raise RuntimeError(path.name + ": unable to identify snapshot group")
    category = group.group(1)
    if category not in GROUPS:
        raise RuntimeError(path.name + ": unrecognized group " + category)
    if path.name == "njpw-slamvision.html":
        if "params.get('channel')==='12'?'12':'01'" not in data:
            raise RuntimeError("NJPW 01/12 selector changed unexpectedly")
        feed = "channel==='12'?'njpw-tv':'njpw'"
    else:
        match = SIMPLE.search(data)
        if not match:
            raise RuntimeError(path.name + ": missing single channel dial")
        dial = match.group(1)
        if dial not in GROUPS[category]:
            raise RuntimeError(path.name + ": unexpected dial " + dial)
        feed = repr(GROUPS[category][dial])
    return data, category, feed


def transform(path):
    data, group, feed = inspect(path)
    if SRC in data:
        # Idempotence and validation of subsequent runs.
        if data.count(SRC) != 1 or data.count("window.SlamVisionDirect.resolve({") != 1:
            raise RuntimeError(path.name + ": partially applied / conflicting patch")
        return data, False
    match = OLD_FETCH.search(data)
    if not match or match.group(1) != group:
        raise RuntimeError(path.name + ": original refresher block changed unexpectedly")
    if len(OLD_FETCH.findall(data)) != 1 or data.count("<script>\n(()=>{") != 1:
        raise RuntimeError(path.name + ": duplicate blocks or unexpected scripts")
    replacement = (
        "  // Use cached Pages schedule while fresh; otherwise query the feed by stable ID.\n"
        "  const next=await window.SlamVisionDirect.resolve({\n"
        f"    cachedUrl:'./slamvision/{group}-live.json?t='+Date.now(),\n"
        "    channel:channel,\n"
        f"    sourceId:{feed}\n"
        "  });\n"
    )
    data = data[:match.start()] + replacement + data[match.end():]
    data = data.replace("<script>\n(()=>{", SRC + "<script>\n(()=>{", 1)
    return data, True


def check_js(path, html):
    body = html.split("<script>\n", 1)[1].split("\n</script>", 1)[0]
    result = subprocess.run(["node", "--check", "-"], input=body, text=True,
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(path.name + " JavaScript invalid: " + result.stderr[-800:])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not (args.apply or args.check):
        parser.error("Specify --apply or --check")
    if len(PLAYER_FILES) != COUNT:
        raise RuntimeError(f"Expected {COUNT} players, got {len(PLAYER_FILES)}")
    changed = 0
    for path in PLAYER_FILES:
        content, updated = transform(path)
        if args.check and updated:
            raise RuntimeError(path.name + ": missing fallback patch")
        if content.count(SRC) != 1:
            raise RuntimeError(path.name + ": shared helper not loaded exactly once")
        if content.count("window.SlamVisionDirect.resolve({") != 1:
            raise RuntimeError(path.name + ": live loader missing or duplicated")
        check_js(path, content)
        if updated and args.apply:
            path.write_text(content, encoding="utf-8")
            changed += 1
        print(("UPDATED " if updated else "VERIFIED ") + path.name)
    print(f"PASS: {len(PLAYER_FILES)} original embed pages validated; {changed} patched")


if __name__ == "__main__":
    main()
