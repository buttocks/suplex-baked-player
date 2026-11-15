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
    print('INDIE CANDIDATES: '+json.dumps([{'number':x.get('number'),'id':x.get('id'),'name':x.get('name')} for x in channels if any(t in (str(x.get('id',''))+' '+str(x.get('name',''))+' '+str(x.get('callsign',''))).lower() for t in ('indie','independent','indy','gcw','pwg','czw','deathmatch'))]),flush=True)
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
    lucha_channels={'16':'100-lucha','54':'lu-tv','60':'cmll','62':'aaa','93':'universal-lucha-libre'}
    lucha_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    for number,channel_id in lucha_channels.items():
        ch=byid.get(channel_id)
        if not ch or ch.get('number')!=int(number):
            raise RuntimeError('Lucha channel mismatch: '+number+' '+channel_id)
        now=read('channels/'+channel_id+'/now')
        current=program(now.get('current'))
        if not current or not current['stream_url']:
            raise RuntimeError('No playable current program for '+channel_id)
        lucha_data['channels'][number]={
          'id':channel_id,'name':ch.get('name',channel_id),
          'current':current,'up_next':[program(x) for x in now.get('up_next',[])[:8]],
          'guide':[program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
          'server_time':now.get('server_time')
        }
    roh_channels={'15':'roh-tv','56':'croh'}
    roh_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    for number,channel_id in roh_channels.items():
        ch=byid.get(channel_id)
        if not ch or ch.get('number')!=int(number):
            raise RuntimeError('ROH channel mismatch '+number)
        now=read('channels/'+channel_id+'/now')
        current=program(now.get('current'))
        if not current or not current['stream_url']:
            raise RuntimeError('Missing ROH current stream '+channel_id)
        roh_data['channels'][number]={
          'id':channel_id,'name':ch.get('name',channel_id),'current':current,
          'up_next':[program(x) for x in now.get('up_next',[])[:8]],
          'guide':[program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
          'server_time':now.get('server_time')
        }
    noah=byid.get('noah-tv')
    if not noah or noah.get('number')!=20:
        raise RuntimeError('SlamVision NOAH-TV channel 20 unavailable')
    noah_now=read('channels/noah-tv/now')
    noah_current=program(noah_now.get('current'))
    if not noah_current or not noah_current['stream_url']:
        raise RuntimeError('No playable NOAH current program')
    noah_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'channels':{'20':{'id':'noah-tv','name':noah.get('name','NOAH-TV'),
      'current':noah_current,
      'up_next':[program(x) for x in noah_now.get('up_next',[])[:8]],
      'guide':[program(x) for x in byguide.get('noah-tv',{}).get('slots',[])],
      'server_time':noah_now.get('server_time')}}}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'noah-live.json').write_text(json.dumps(noah_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'roh-live.json').write_text(json.dumps(roh_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'lucha-live.json').write_text(json.dumps(lucha_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'joshi-live.json').write_text(json.dumps(joshi_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'ajpw-live.json').write_text(json.dumps(ajpw_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'njpw-live.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print('Mirrored NJPW, AJPW, Joshi and five lucha channels',flush=True)
if __name__=='__main__': main()
