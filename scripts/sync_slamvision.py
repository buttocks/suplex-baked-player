#!/usr/bin/env python3
"""Cache only the public NJPW broadcast data required for GitHub Pages players."""
import json, pathlib, urllib.request, datetime, sys
ROOT=pathlib.Path(__file__).resolve().parent.parent
OUT=ROOT/'slamvision'
BASE='https://ring-channel-tv.emergent.host/api/'
CHANNELS={'njpw':'01','njpw-tv':'12'}  # Preserve both existing NJPW feeds
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
    ajpw=next((ch for ch in channels if ch.get('number')==5),None)
    if not ajpw: raise RuntimeError('SlamVision Channel 05 missing')
    ch100=next((ch for ch in channels if ch.get('number')==100),None)
    if not ch100: raise RuntimeError('SlamVision Channel 100 missing')
    print('Channel 100 identified: '+ch100['id']+' — '+ch100.get('name',''),flush=True)
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
    response=read('channels/'+ajpw['id']+'/now')
    if response.get('current') is None: raise RuntimeError('No active program for AJPW Channel 05')
    ajpw_current=program(response['current'])
    if not ajpw_current['stream_url']: raise RuntimeError('Missing AJPW stream URL')
    ajpw_data={
      'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'channels':{'05':{
       'id':ajpw['id'],'name':ajpw.get('name','All Japan Pro Wrestling'),
       'current':ajpw_current,
       'up_next':[program(x) for x in response.get('up_next',[])[:8]],
       'guide':[program(x) for x in byguide.get(ajpw['id'],{}).get('slots',[])],
       'server_time':response.get('server_time')}}}
    response100=read('channels/'+ch100['id']+'/now')
    if response100.get('current') is None: raise RuntimeError('No active Channel 100 program')
    p100=program(response100['current'])
    if not p100['stream_url']: raise RuntimeError('Missing Channel 100 stream URL')
    data100={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'channels':{'100':{'id':ch100['id'],'name':ch100.get('name','Channel 100'),
       'current':p100,'up_next':[program(x) for x in response100.get('up_next',[])[:8]],
       'guide':[program(x) for x in byguide.get(ch100['id'],{}).get('slots',[])],
       'server_time':response100.get('server_time')}}}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'channel-100-live.json').write_text(json.dumps(data100,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'ajpw-live.json').write_text(json.dumps(ajpw_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'njpw-live.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print('Mirrored NJPW channels '+', '.join(CHANNELS.values())+' and AJPW Channel 05 ('+ajpw['id']+')',flush=True)
if __name__=='__main__': main()
