#!/usr/bin/env python3
"""Cache only the public NJPW broadcast data required for GitHub Pages players."""
import json, pathlib, urllib.request, datetime, sys
ROOT=pathlib.Path(__file__).resolve().parent.parent
OUT=ROOT/'slamvision'
BASE='https://ring-channel-tv.emergent.host/api/'
CHANNELS={'njpw':'01','njpw-tv':'12'}
def read(path):
    req=urllib.request.Request(BASE+path,headers={'User-Agent':'Mozilla/5.0 (compatible; NJPW-Baked-Viewer/1.0)','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as resp:
        return json.load(resp)
def program(slot):
    if not slot: return None
    p=slot.get('program') or {}
    return {'title':p.get('title') or 'Untitled program','episode':p.get('episode') or '',
            'stream_url':p.get('stream_url') or '', 'start':slot.get('start'),
            'end':slot.get('end'), 'id':p.get('id') or '', 'block':slot.get('block')}
def main():
    data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    channels=read('channels')
    byid={c['id']:c for c in channels}
    guide=read('guide?hours=4')
    byguide={r['channel']['id']:r for r in guide.get('rows',[])}
    for channel_id,number in CHANNELS.items():
        if channel_id not in byid: raise RuntimeError('Missing channel '+channel_id)
        response=read('channels/'+channel_id+'/now')
        if response.get('current') is None: raise RuntimeError('No active program on '+channel_id)
        current=program(response.get('current'))
        upcoming=[program(x) for x in response.get('up_next',[])[:8]]
        if current and not current['stream_url']: raise RuntimeError('Missing stream URL on '+channel_id)
        data['channels'][number]={
            'id':channel_id,'name':byid[channel_id].get('name','NJPW-TV'),
            'current':current,'up_next':upcoming,
            'guide': [program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
            'server_time': response.get('server_time')
        }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'njpw-live.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print('Mirrored NJPW channels '+', '.join(CHANNELS.values()),flush=True)
if __name__=='__main__': main()
