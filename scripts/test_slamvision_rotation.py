#!/usr/bin/env python3
"""Offline regression tests: dial numbers rotate but stable broadcast IDs do not."""
import datetime
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sync_slamvision as mod

def current(source_id):
    now=datetime.datetime.now(datetime.timezone.utc)
    return {
        'channel':{'id':source_id,'number':112},
        'current':{'start':(now-datetime.timedelta(minutes=2)).isoformat(),
                   'end':(now+datetime.timedelta(minutes=35)).isoformat(),
                   'program':{'title':'Sample wrestling broadcast',
                              'id':'example', 'stream_url':'https://archive.org/download/test/show.mp4'}},
        'up_next':[], 'server_time':now.isoformat()
    }

def check():
    # The legacy Baked.live embed still asks for CH 01, even if the upstream
    # has reassigned number 01 to the "Wrestling in 1985" station.
    channels=[
        {'id':'year-1985','number':1,'name':'Wrestling in 1985'},
        {'id':'njpw','number':107,'name':'NJPW'},
        {'id':'wwf-90-00','number':112,'name':'WWF 1990-2000'},
    ]
    ids=mod.build_index(channels)
    assert ids['njpw']['number']==107
    assert ids['wwf-90-00']['number']==112
    original_read=mod.read
    try:
        mod.read=lambda path: current(path.split('/')[1]) if path.endswith('/now') else None
        got=mod.fetch_one('njpw','01','njpw',ids,{})
        assert got['id']=='njpw' and got['current']['title']=='Sample wrestling broadcast'
        got=mod.fetch_one('wwf','52','wwf-90-00',ids,{})
        assert got['id']=='wwf-90-00'
        mod.read=lambda _:current('year-1985')
        try:
            mod.fetch_one('njpw','01','njpw',ids,{})
        except RuntimeError as error:
            assert 'instead' in str(error)
        else: raise AssertionError('Wrong upstream identity was accepted')
        try:
            mod.fetch_one('njpw','12','njpw-tv',ids,{})
        except RuntimeError as error:
            assert 'cannot safely guess' in str(error)
        else: raise AssertionError('Missing feed silently substituted')
    finally:
        mod.read=original_read
    dup=mod.build_index([{'id':'njpw','number':1},{'id':'njpw','number':99}])
    assert 'njpw' not in dup,'Duplicate stable ID must be rejected'
    assert len(mod.GROUPS)==14 and sum(map(len,mod.GROUPS.values()))==42
    assert mod.GROUPS['njpw']=={
        '01':'njpw','12':'njpw-tv','64':'njpw-destructi','65':'njpw-g1climax',
        '66':'njpw-starrcade','67':'njpw-wp','68':'njpw-wk',
        '69':'njpw-wrestling','31':'ain'
    }
    print('PASS: rotated dial numbers preserve old embeds; wrong, missing, and duplicate IDs rejected')

if __name__=='__main__':check()
