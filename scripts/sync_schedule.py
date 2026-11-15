#!/usr/bin/env python3
"""Mirror public Spelunkr schedule JSON for a browser-safe GitHub Pages player."""
import json, pathlib, urllib.request, time, sys
ROOT=pathlib.Path(__file__).resolve().parent.parent
OUT=ROOT/"broadcast"
BASES=[
"https://jbuopkuluyfjwgsrigry.supabase.co/storage/v1/object/public/broadcast/",
"https://spelunkr.tv/broadcast/",
]
def fetch(path):
    for base in BASES:
        try:
            req=urllib.request.Request(base+path,headers={"User-Agent":"SUPLEX-Baked-Player/1.0","Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=25) as resp:
                data=resp.read()
            value=json.loads(data)
            return data,value,base
        except Exception as exc:
            print(f"Unable to fetch {base}{path}: {exc}",file=sys.stderr)
    raise RuntimeError("All sources unavailable for "+path)
def save(path,blob):
    target=OUT/path
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(blob)
def valid(path):
    return isinstance(path,str) and path.endswith(".json") and not path.startswith("/") and ".." not in path.split("/") and path.startswith(("manifests/","platform/","details/"))
def main():
    blob,lineup,source=fetch("lineup.json")
    channels=lineup.get("channels") or []
    channel=next((c for c in channels if "suplex" in str(c.get("name","")).lower() or "suplex" in str(c.get("id","")).lower()),None)
    if not channel: raise RuntimeError("SUPLEX missing from lineup; leaving existing cache in place")
    required={}
    for pointer in channel.get("versions",[]):
        path=pointer.get("manifest")
        if not valid(path):raise RuntimeError("Bad manifest path "+str(path))
        required[path]=True
    fetched={}
    for path in required:
        b,manifest,_=fetch(path);fetched[path]=b
        platform=manifest.get("platform")
        if platform:
            if not valid(platform):raise RuntimeError("Bad platform path "+str(platform))
            required[platform]=True
    for path in required:
        if path not in fetched: fetched[path]=fetch(path)[0]
    for path,b in fetched.items(): save(path,b)
    save("lineup.json",blob)
    print(f"SUPLEX mirrored {len(fetched)} assets from {source} at {time.ctime()}")
if __name__=="__main__":main()
