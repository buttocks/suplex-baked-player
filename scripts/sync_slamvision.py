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
    print('LUCHA CANDIDATES: '+json.dumps([{'number':c.get('number'),'id':c.get('id'),'name':c.get('name'),'callsign':c.get('callsign')} for c in channels if any(t in (str(c.get('id',''))+' '+str(c.get('name',''))+' '+str(c.get('callsign',''))).lower() for t in ('lucha','cmll','aaa'))]),flush=True)
    ajpw=next((ch for ch in channels if ch.get('number')==5),None)
    if not ajpw: raise RuntimeError('SlamVision Channel 05 missing')
    joshi=next((ch for ch in channels if ch.get('number')==11),None)
    if not joshi: raise RuntimeError('SlamVision Channel 11 (Joshi) missing')
    print('Channel 11: '+str(joshi.get('id'))+' / '+str(joshi.get('name')),flush=True)
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
    response11=read('channels/'+joshi['id']+'/now')
    if response11.get('current') is None: raise RuntimeError('No active Joshi Channel 11 program')
    joshi_current=program(response11['current'])
    if not joshi_current['stream_url']: raise RuntimeError('Missing Joshi Channel 11 stream URL')
    joshi_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'channels':{'11':{'id':joshi['id'],'name':joshi.get('name','Joshi Puroresu'),
       'current':joshi_current,'up_next':[program(x) for x in response11.get('up_next',[])[:8]],
       'guide':[program(x) for x in byguide.get(joshi['id'],{}).get('slots',[])],
       'server_time':response11.get('server_time')}}}
    lucha=next((ch for ch in channels if ch.get('id')=='100-lucha' and ch.get('number')==16),None)
    if not lucha: raise RuntimeError('100% Lucha Channel 16 missing')
    lucha_now=read('channels/'+lucha['id']+'/now')
    lucha_current=program(lucha_now.get('current'))
    if not lucha_current or not lucha_current['stream_url']: raise RuntimeError('No playable 100% Lucha current program')
    lucha_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'channels':{'16':{'id':lucha['id'],'name':lucha.get('name','100% Lucha'),
      'current':lucha_current,'up_next':[program(x) for x in lucha_now.get('up_next',[])[:8]],
      'guide':[program(x) for x in byguide.get(lucha['id'],{}).get('slots',[])],
      'server_time':lucha_now.get('server_time')}}}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'lucha-live.json').write_text(json.dumps(lucha_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'joshi-live.json').write_text(json.dumps(joshi_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'ajpw-live.json').write_text(json.dumps(ajpw_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'njpw-live.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print('Mirrored NJPW channels '+', '.join(CHANNELS.values())+' and AJPW Channel 05 ('+ajpw['id']+')',flush=True)
if __name__=='__main__': main()
