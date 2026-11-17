#!/usr/bin/env python3
"""Audit every catalog entry against legacy and universal shared backups."""
import json
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sync_slamvision as mod

def check():
    catalog=json.loads(mod.CATALOG.read_text(encoding="utf-8"))
    groups=mod.planned_groups(catalog)
    assert len(mod.GROUPS)==14
    assert len(groups)==15
    active=[c for c in catalog['channels'] if c.get('availability','available')=='available']
    ids=[c['id'] for c in active]
    assert len(ids)==len(set(ids))
    legacy={v for grp in mod.GROUPS.values() for v in grp.values()}
    shared=groups['shared']
    new=[c for c in active if c['id'] not in legacy]
    assert len(shared)==len(new)
    assert set(shared)=={c['id'] for c in new}
    assert all(item['player_type']=='shared' for item in new)
    assert all(item['player_type'] in ('legacy','shared') for item in active)
    assert all(item['id'] in legacy or item['id'] in shared for item in active)
    assert not (set(shared)&legacy)
    assert len(active)>=35 and len(shared)>=1, ('Suspicious or empty inventory', len(active),len(shared))
    # Confirm that all new IDs join automatically, without code edits.
    additions=deepcopy_catalog(catalog)
    additions['channels'].append({
      'id':'new-wrestling-demo','name':'New wrestling broadcast',
      'tube':'Needs Review','player_type':'shared','availability':'available',
      'embed_url':'https://buttocks.github.io/suplex-baked-player/slamvision-feed.html?id=new-wrestling-demo'
    })
    assert mod.planned_groups(additions)['shared']['new-wrestling-demo']=='new-wrestling-demo'
    # A temporarily unavailable channel remains configured in catalog but isn't requested
    # again until the lineup watcher restores it.
    offline=deepcopy_catalog(catalog)
    gone=next(c for c in offline['channels'] if c['id'] in shared)
    gone['availability']='unavailable'
    assert gone['id'] not in mod.planned_groups(offline)['shared']
    # Identity collisions can never enter the cache.
    duplicated=deepcopy_catalog(catalog)
    duplicated['channels'].append(dict(duplicated['channels'][0]))
    try:
        mod.planned_groups(duplicated)
    except RuntimeError as e:
        assert 'Duplicate' in str(e)
    else:
        raise AssertionError('Duplicate ID accepted')
    # Program schedules from an old dial must not be assigned to another stable ID.
    assert mod.cached_if_active('does-not-exist','x',0,'wrong') is None
    by={}
    for c in new:
        by.setdefault(c['tube'],[]).append(c['id'])
    print('PASS: catalog',len(active),'active feeds;',len(legacy & set(ids)),
          'already in legacy backups;',len(shared),'newly covered;',len(legacy-set(ids)),
          'absent legacy IDs',flush=True)
    for tube, ids in by.items():
        print('BACKUP_AUDIT',tube, len(ids), ','.join(ids),flush=True)
    print('PASS: automatic new-ID discovery, removed-ID handling, exact matching and duplicate rejection',flush=True)


def deepcopy_catalog(obj):
    return json.loads(json.dumps(obj))

if __name__=='__main__':
    check()
