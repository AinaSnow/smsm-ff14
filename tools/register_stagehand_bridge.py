"""Add only the verified M2 bridge dev entry; preserve Stagehand and other profiles."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid
from manage_preview import running_game,encoded,write_atomic


def register(launcher,game,package,backups,replace_package=None):
    if running_game(game):raise ValueError('Exit FF14 before changing developer plugin paths')
    meta=json.loads((package/'package.json').read_bytes())
    if meta['schema']!=1 or meta['manual_start_only'] is not True or meta['default_light_count']!=0:raise ValueError('Invalid bounded bridge package')
    for name,sha in meta['files'].items():
        p=package/name
        if Path(name).name!=name or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:raise ValueError('Bridge package changed')
    if (game/'ffxivgame.ver').read_text().strip()!='2026.09.15.0000.0000':raise ValueError('Client changed')
    config=launcher/'dalamudConfig.json';before=config.read_bytes();data=json.loads(before.decode('utf-8-sig'))
    settings=data['DevPluginSettings'];locations=data['DevPluginLoadLocations']['$values'];dll=str((package/'SMSM.StagehandBridge.dll').resolve())
    existing=[v for v in locations if Path(v['Path']).name=='SMSM.StagehandBridge.dll']
    if dll in settings:raise ValueError('Destination already registered')
    if replace_package is None:
        if existing:raise ValueError('Existing bridge registration; name its immutable package explicitly to upgrade')
        settings[dll]={'$type':'Dalamud.Configuration.Internal.DevPluginSettings, Dalamud','StartOnBoot':False,'NotifyForErrors':True,'AutomaticReloading':False,'WorkingPluginId':str(uuid.uuid4()),
                      'DismissedValidationProblems':{'$type':'System.Collections.Generic.List`1[[System.String, System.Private.CoreLib]], System.Private.CoreLib','$values':[]}}
        locations.append({'$type':'Dalamud.Configuration.DevPluginLocationSettings, Dalamud','Path':dll,'IsEnabled':True,'Nickname':'SMSM Stagehand M2 '+meta['bridge_version']})
    else:
        old_dll=str((replace_package/'SMSM.StagehandBridge.dll').resolve())
        if len(existing)!=1 or existing[0]['Path']!=old_dll or old_dll not in settings:raise ValueError('Expected single previous bridge registration')
        old_meta=json.loads((replace_package/'package.json').read_bytes())
        if hashlib.sha256(Path(old_dll).read_bytes()).hexdigest()!=old_meta['files']['SMSM.StagehandBridge.dll']:raise ValueError('Previous bridge package changed')
        settings[dll]=settings.pop(old_dll)
        settings[dll]['StartOnBoot']=False
        settings[dll]['AutomaticReloading']=False
        existing[0]['Path']=dll;existing[0]['Nickname']='SMSM Stagehand M2 '+meta['bridge_version']
    after=encoded(data);backup=backups/uuid.uuid4().hex;backup.mkdir(parents=True)
    (backup/'dalamudConfig.before.json').write_bytes(before)
    if running_game(game) or config.read_bytes()!=before:raise ValueError('Client/config changed during preparation')
    try:
        write_atomic(config,after)
        if config.read_bytes()!=after:raise RuntimeError('Bridge registration verification failed')
    except BaseException:
        if config.exists() and config.read_bytes()==after:write_atomic(config,before)
        raise
    (backup/'receipt.json').write_bytes(encoded({'plugin':dll,'manual_start_only':True,'start_on_boot':False,'profile_state_preserved':True,'other_entries_preserved':True,'game_dlls_changed':False}))
    print(json.dumps({'registered':True,'default_lights':0,'manual_start_only':True,'backup':str(backup)}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('launcher','game','package','backups'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--replace-package',type=Path)
    a=p.parse_args();register(a.launcher,a.game,a.package,a.backups,a.replace_package)
