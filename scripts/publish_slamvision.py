#!/usr/bin/env python3
"""Publish only newer SlamVision JSON snapshots, preserving unrelated Git changes.

No force pushes, no rebases. Any concurrent commit is handled by refetching
the current remote branch and applying only fresh generated files on top.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
FILES = ("slamvision/njpw-live.json", "slamvision/ajpw-live.json", "slamvision/joshi-live.json", "slamvision/lucha-live.json", "slamvision/roh-live.json", "slamvision/noah-live.json", "slamvision/independent-live.json", "slamvision/dragongate-live.json", "slamvision/puro-live.json", "slamvision/shoot-live.json", "slamvision/ecw-live.json", "slamvision/wwf-live.json", "slamvision/tna-live.json", "slamvision/wcw-live.json", "slamvision/shared-live.json")


def timestamp(blob, label):
    try:
        record = json.loads(blob)
        if not isinstance(record.get("channels"), dict):
            raise ValueError("channels must be an object")
        stamp = dt.datetime.fromisoformat(record["generated_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("generated_at must include timezone")
        return stamp.timestamp()
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise RuntimeError("Invalid snapshot in " + label + ": " + str(exc)) from exc


def git(*args, cwd=ROOT, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, text=True,
                            capture_output=True)
    if check and result.returncode:
        raise RuntimeError("git " + " ".join(args) + " failed: " +
                           (result.stderr or result.stdout)[-2000:])
    return result


def publish(saved, branch, cwd=ROOT, retries=4):
    if not branch or branch.startswith("-") or ".." in branch or " " in branch:
        raise ValueError("Invalid branch name")
    for attempt in range(retries):
        # Refetch the exact branch and rebuild our commit from its newest tip.
        # Do NOT rebase generated JSON files: they are one-line JSON and conflict.
        git("fetch", "--no-tags", "origin", "refs/heads/" + branch, cwd=cwd)
        git("reset", "--hard", "FETCH_HEAD", cwd=cwd)
        written, skipped = [], []
        for path, data in saved.items():
            target = cwd / path
            incoming = timestamp(data, path + " (generated)")
            # Newly generated files are untracked until their first publish.
            # git reset --hard leaves those local files in place. Treating
            # their own timestamp as the remote timestamp would skip publishing!
            tracked = git("ls-files", "--error-unmatch", "--", path,
                          cwd=cwd, check=False).returncode == 0
            if tracked and target.exists():
                current = timestamp(target.read_bytes(), path + " (remote)")
                if current >= incoming:
                    skipped.append(path + " (remote is newer or equal)")
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(path)
        if not written:
            print("Nothing to publish; remote snapshots are already as new or newer.", flush=True)
            return
        git("add", "--", *written, cwd=cwd)
        if not git("diff", "--cached", "--quiet", cwd=cwd, check=False).returncode:
            print("No file differences to publish.", flush=True)
            return
        git("commit", "-m", "Refresh SlamVision stream data (fresh snapshots only)", cwd=cwd)
        push = git("push", "origin", "HEAD:refs/heads/" + branch, cwd=cwd, check=False)
        if push.returncode == 0:
            print("Published " + str(len(written)) + " new snapshot files to " + branch +
                  "; skipped " + str(len(skipped)) + " older/equal files.", flush=True)
            return
        if attempt + 1 == retries:
            raise RuntimeError("Could not publish after " + str(retries) +
                               " fresh-branch retries: " + push.stderr[-1500:])
        print("Another commit landed during publish; retrying from latest branch tip.",
              flush=True)
        time.sleep(1 + attempt)


def self_test():
    now = dt.datetime(2026, 11, 16, tzinfo=dt.timezone.utc)
    def snap(minute):
        return json.dumps({"generated_at": (now + dt.timedelta(minutes=minute)).isoformat(),
                           "channels": {"52": {"id": "wwf-90-00"}}}).encode()
    assert timestamp(snap(1), "test") > timestamp(snap(0), "test")
    try:
        timestamp(b'{"generated_at":"bad","channels":{}}', "bad test")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Invalid timestamps must be rejected")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        remote, seed, older, latest = [base / part for part in ("remote.git", "seed", "older", "latest")]
        git("init", "--bare", str(remote), cwd=base)
        git("clone", str(remote), str(seed), cwd=base)
        git("checkout", "-b", "main", cwd=seed)
        git("config", "user.name", "Test Bot", cwd=seed)
        git("config", "user.email", "bot@example.invalid", cwd=seed)
        file = "slamvision/wwf-live.json"
        (seed / "slamvision").mkdir()
        (seed / file).write_bytes(snap(0))
        git("add", file, cwd=seed)
        git("commit", "-m", "seed", cwd=seed)
        git("push", "-u", "origin", "main", cwd=seed)
        git("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
        git("clone", str(remote), str(older), cwd=base)
        git("clone", str(remote), str(latest), cwd=base)
        for clone in (older, latest):
            git("config", "user.name", "Test Bot", cwd=clone)
            git("config", "user.email", "bot@example.invalid", cwd=clone)
        # Simulate a different run publishing a newer schedule.
        (latest / file).write_bytes(snap(20))
        git("add", file, cwd=latest)
        git("commit", "-m", "newer refresh", cwd=latest)
        git("push", "origin", "main", cwd=latest)
        # A delayed job must not overwrite the newer snapshot or fail.
        publish({file: snap(10)}, "main", cwd=older)
        assert (older / file).read_bytes() == snap(20), "A delayed job overwrote newer data"
        # It should still publish a genuinely newer update.
        publish({file: snap(30)}, "main", cwd=older)
        git("fetch", "origin", "main", cwd=latest)
        assert timestamp(git("show", "FETCH_HEAD:" + file, cwd=latest).stdout, file) == timestamp(snap(30), file)
        # Regression: a brand-new generated file remains UNTRACKED during the
        # runner's fetch/reset. It must still be added on first publish.
        fresh_file = "slamvision/shared-live.json"
        (older / fresh_file).write_bytes(snap(40))
        assert git("ls-files", "--error-unmatch", "--", fresh_file,
                   cwd=older, check=False).returncode != 0
        publish({fresh_file: snap(40)}, "main", cwd=older)
        git("fetch", "origin", "main", cwd=latest)
        assert timestamp(git("show", "FETCH_HEAD:" + fresh_file, cwd=latest).stdout,
                         fresh_file) == timestamp(snap(40), fresh_file), (
            "Newly generated untracked shared cache was never published")
    print("PASS: publishing protects newer remote data, publishes fresh snapshots, and adds untracked new files")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    branch = os.environ.get("GITHUB_REF_NAME") or git("branch", "--show-current").stdout.strip()
    saved = {}
    for path in FILES:
        source = ROOT / path
        if source.exists():
            data = source.read_bytes()
            timestamp(data, path)
            saved[path] = data
    if not saved:
        raise RuntimeError("No SlamVision JSON snapshots exist to publish")
    publish(saved, branch)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
