#!/usr/bin/env python3
"""End-to-end fixture for SlamVision discovery and public catalog generation."""
import csv
import datetime as dt
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import update_slamvision_catalog as mod

def check():
    seed=json.loads((ROOT/"research/slamvision-current.json").read_text())
    assert len(seed["channels"])==116
    assert len({r["id"] for r in seed["channels"]})==116
    assert len({r["embed_url"] for r in seed["channels"]})==116
    assert sum(r.get("player_type")=="legacy" for r in seed["channels"])==24
    assert sum(r.get("player_type")=="shared" for r in seed["channels"])==92
    assert len(seed["destination_tubes"])==17
    now=dt.datetime(2026,11,17,20,30,tzinfo=dt.timezone.utc)
    upstream=[{"id":r["id"], **{k:r.get(k) for k in mod.FIELDS}} for r in seed["channels"] if r["id"]!="njpw"]
    upstream += [
        {"id":"lucha-new-show","number":222,"name":"CMLL Grand Prix"},
        {"id":"unknown-new-show","number":223,"name":"Mystery Grappling Club"},
    ]
    result, changes, changed=mod.rebuild(seed,upstream,None,now)
    assert changed
    assert changes["missing"]==["njpw"]
    assert set(changes["added"])=={"lucha-new-show","unknown-new-show"}
    by_id={r["id"]:r for r in result["channels"]}
    assert by_id["njpw"]["availability"]=="temporarily_missing"
    assert by_id["njpw"]["embed_url"]==next(x["embed_url"] for x in seed["channels"] if x["id"]=="njpw")
    assert by_id["lucha-new-show"]["tube"]=="Lucha Tube"
    assert by_id["unknown-new-show"]["tube"]=="Needs Review"
    assert by_id["lucha-new-show"]["embed_url"].endswith("slamvision-feed.html?id=lucha-new-show")
    assert len(result["channels"])==118
    assert result["total"]==117
    original=(mod.RESEARCH,mod.CURRENT,mod.HISTORY)
    try:
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"research"
            mod.RESEARCH=path
            mod.CURRENT=path/"slamvision-current.json"
            mod.HISTORY=path/"slamvision-change-log.json"
            mod.export(result,changes,now)
            generated=json.loads(mod.CURRENT.read_text())
            assert len(generated["channels"])==118
            assert (path/"slamvision-current.csv").exists()
            assert (path/"slamvision-current.md").exists()
            assert (path/"slamvision-current-iframes.txt").exists()
            assert len(list((path/"slamvision-snapshots").glob("*.json")))==1
            history=json.loads(mod.HISTORY.read_text())
            assert history["events"][0]["changes"]["added"]==changes["added"]
            with (path/"slamvision-current.csv").open(newline="") as f:
                assert len(list(csv.DictReader(f)))==118
            iframes=(path/"slamvision-current-iframes.txt").read_text()
            assert iframes.count("<iframe")==117
    finally:
        mod.RESEARCH,mod.CURRENT,mod.HISTORY=original
    catalog=(ROOT/"research/slamvision-tube-catalog.html").read_text()
    assert 'slamvision-current.json' in catalog
    assert "Latest lineup changes" in catalog
    assert "Copy all iframes in selected tube" in catalog
    assert 'channels.length!==116' not in catalog
    js=catalog.split("<script>",1)[1].split("</script>",1)[0]
    subprocess.run(["node","--check","-"],input=js,text=True,capture_output=True,check=True)
    print("PASS: 116 original links unchanged, 2 new auto-embeds, missing grace, Needs Review, CSV/MD/JSON/iframe/history/snapshot writes and UI syntax",flush=True)

if __name__=="__main__":
    check()
