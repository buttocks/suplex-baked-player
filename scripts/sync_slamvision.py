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
    print('NWA CANDIDATES: '+json.dumps([{'number':x.get('number'),'id':x.get('id'),'name':x.get('name')} for x in channels if any(t in (str(x.get('id',''))+' '+str(x.get('name',''))+' '+str(x.get('callsign',''))).lower() for t in ('nwa','national wrestling alliance','jim crockett','jcp'))]),flush=True)
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
    indie_channels={'22':'gcw-tv','48':'death','49':'czw-tv','72':'pwg'}
    indie_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    for number,channel_id in indie_channels.items():
        ch=byid.get(channel_id)
        if not ch or ch.get('number')!=int(number):
            raise RuntimeError('Independent wrestling channel mismatch '+number)
        now=read('channels/'+channel_id+'/now')
        current=program(now.get('current'))
        if not current or not current['stream_url']:
            raise RuntimeError('Missing independent wrestling stream '+channel_id)
        indie_data['channels'][number]={
          'id':channel_id,'name':ch.get('name',channel_id),'current':current,
          'up_next':[program(x) for x in now.get('up_next',[])[:8]],
          'guide':[program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
          'server_time':now.get('server_time')
        }
    dg=byid.get('dgtv')
    if not dg or dg.get('number')!=37:
        raise RuntimeError('SlamVision Dragon Gate channel 37 unavailable')
    dg_now=read('channels/dgtv/now')
    dg_current=program(dg_now.get('current'))
    if not dg_current or not dg_current['stream_url']:
        raise RuntimeError('No playable Dragon Gate current program')
    dg_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'channels':{'37':{'id':'dgtv','name':dg.get('name','Dragongate'),
      'current':dg_current,
      'up_next':[program(x) for x in dg_now.get('up_next',[])[:8]],
      'guide':[program(x) for x in byguide.get('dgtv',{}).get('slots',[])],
      'server_time':dg_now.get('server_time')}}}
    puro_channels={'43':'ddt','44':'dream-graps','46':'dramatic-graps','47':'bjw'}
    puro_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    for number,channel_id in puro_channels.items():
        ch=byid.get(channel_id)
        if not ch or ch.get('number')!=int(number):
            raise RuntimeError('Puroresu channel mismatch '+number)
        now=read('channels/'+channel_id+'/now')
        current=program(now.get('current'))
        if not current or not current['stream_url']:
            raise RuntimeError('Missing puroresu current stream '+channel_id)
        puro_data['channels'][number]={
          'id':channel_id,'name':ch.get('name',channel_id),'current':current,
          'up_next':[program(x) for x in now.get('up_next',[])[:8]],
          'guide':[program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
          'server_time':now.get('server_time')
        }
    shoot_channels={'29':'tsn','32':'mma-tv'}
    shoot_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    for number,channel_id in shoot_channels.items():
        ch=byid.get(channel_id)
        if not ch or ch.get('number')!=int(number):
            raise RuntimeError('Shoot channel mismatch '+number)
        now=read('channels/'+channel_id+'/now')
        current=program(now.get('current'))
        if not current or not current['stream_url']:
            raise RuntimeError('Missing shoot channel stream '+channel_id)
        shoot_data['channels'][number]={
          'id':channel_id,'name':ch.get('name',channel_id),'current':current,
          'up_next':[program(x) for x in now.get('up_next',[])[:8]],
          'guide':[program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
          'server_time':now.get('server_time')
        }
    ecw_channels={'10':'ecw-tv','30':'ecw-tv2'}
    ecw_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    for number,channel_id in ecw_channels.items():
        ch=byid.get(channel_id)
        if not ch or ch.get('number')!=int(number):
            raise RuntimeError('ECW channel mismatch '+number)
        now=read('channels/'+channel_id+'/now')
        current=program(now.get('current'))
        if not current or not current['stream_url']:
            raise RuntimeError('Missing ECW current stream '+channel_id)
        ecw_data['channels'][number]={
          'id':channel_id,'name':ch.get('name',channel_id),'current':current,
          'up_next':[program(x) for x in now.get('up_next',[])[:8]],
          'guide':[program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
          'server_time':now.get('server_time')
        }
    wwf_channels={'14':'wwf','25':'wwe','52':'wwf-90-00','64':'wwwf'}
    wwf_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    for number,channel_id in wwf_channels.items():
        ch=byid.get(channel_id)
        if not ch or ch.get('number')!=int(number):
            raise RuntimeError('WWF channel mismatch '+number)
        now=read('channels/'+channel_id+'/now')
        current=program(now.get('current'))
        if not current or not current['stream_url']:
            raise RuntimeError('Missing WWF stream '+channel_id)
        wwf_data['channels'][number]={
          'id':channel_id,'name':ch.get('name',channel_id),'current':current,
          'up_next':[program(x) for x in now.get('up_next',[])[:8]],
          'guide':[program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
          'server_time':now.get('server_time')
        }
    tna_channels={'17':'tna','18':'tna-tv','19':'iw'}
    tna_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    for number,channel_id in tna_channels.items():
        ch=byid.get(channel_id)
        if not ch or ch.get('number')!=int(number):
            raise RuntimeError('TNA channel mismatch '+number)
        now=read('channels/'+channel_id+'/now')
        current=program(now.get('current'))
        if not current or not current['stream_url']:
            raise RuntimeError('Missing TNA current stream '+channel_id)
        tna_data['channels'][number]={
          'id':channel_id,'name':ch.get('name',channel_id),'current':current,
          'up_next':[program(x) for x in now.get('up_next',[])[:8]],
          'guide':[program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
          'server_time':now.get('server_time')
        }
    wcw_channels={'02':'wcw','23':'wcw-tv','31':'wcw-ppv'}
    wcw_data={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'channels':{}}
    for number,channel_id in wcw_channels.items():
        ch=byid.get(channel_id)
        if not ch or ch.get('number')!=int(number):
            raise RuntimeError('WCW channel mismatch '+number)
        now=read('channels/'+channel_id+'/now')
        current=program(now.get('current'))
        if not current or not current['stream_url']:
            raise RuntimeError('Missing WCW stream '+channel_id)
        wcw_data['channels'][number]={
          'id':channel_id,'name':ch.get('name',channel_id),'current':current,
          'up_next':[program(x) for x in now.get('up_next',[])[:8]],
          'guide':[program(x) for x in byguide.get(channel_id,{}).get('slots',[])],
          'server_time':now.get('server_time')
        }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'wcw-live.json').write_text(json.dumps(wcw_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'tna-live.json').write_text(json.dumps(tna_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'wwf-live.json').write_text(json.dumps(wwf_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'ecw-live.json').write_text(json.dumps(ecw_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'shoot-live.json').write_text(json.dumps(shoot_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'puro-live.json').write_text(json.dumps(puro_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'dragongate-live.json').write_text(json.dumps(dg_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'independent-live.json').write_text(json.dumps(indie_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'noah-live.json').write_text(json.dumps(noah_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'roh-live.json').write_text(json.dumps(roh_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'lucha-live.json').write_text(json.dumps(lucha_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'joshi-live.json').write_text(json.dumps(joshi_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'ajpw-live.json').write_text(json.dumps(ajpw_data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'njpw-live.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print('Mirrored NJPW, AJPW, Joshi and five lucha channels',flush=True)
if __name__=='__main__': main()
