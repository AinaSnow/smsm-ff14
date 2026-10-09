"""Register the pinned official Stagehand dev package while the client is stopped."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid
from manage_preview import encoded,write_atomic,running_game


def install(launcher,game,checked,fixtures,library,backup_root,baseline):
    if running_game(game):raise ValueError('Exit FF14 before editing Dalamud startup configuration')
    if hashlib.sha256(baseline.read_bytes()).hexdigest()!='4e8bd8172abbcdd411c739b76bcb6434a05ac7a5d00b18ea0c69dad2205e3914':
        raise ValueError('Frozen r10 package differs')
    report=json.loads((checked/'report.json').read_bytes())
    layouts=json.loads((checked/'installed-layouts.json').read_bytes())
    if not report['all_scanned_signatures_unique'] or not layouts['light_layout_matches_reviewed_source']:
        raise ValueError('M0 offline checks incomplete')
    if (game/'ffxivgame.ver').read_text().strip()!=report['client_build']:raise ValueError('Client build changed')
    package=(checked/'package').resolve();dll=package/'Stagehand.dll'
    for name,sha in report['package_files'].items():
        file=package/name
        if not file.resolve().is_relative_to(package) or file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=sha:
            raise ValueError('Official extracted package changed')
    config=launcher/'dalamudConfig.json';stage_config=launcher/'pluginConfigs/Stagehand.json'
    if stage_config.exists():raise ValueError('Existing Stagehand configuration; inspect before installation')
    before=config.read_bytes();value=json.loads(before.decode('utf-8-sig'))
    settings=value['DevPluginSettings'];locations=value['DevPluginLoadLocations']['$values']
    if any(Path(k).stem.lower()=='stagehand' for k in settings if k!='$type') or any(Path(l['Path']).stem.lower()=='stagehand' for l in locations):
        raise ValueError('Another Stagehand dev registration exists')
    if library.exists():raise ValueError('Use a new isolated M1 stage library')
    library.mkdir(parents=True);stage=library/'SMSM-M1-native-light.json'
    with stage.open('xb') as f:f.write((fixtures/stage.name).read_bytes())
    empty=json.loads(stage.read_bytes())
    if empty['Objects']:raise ValueError('Initial test stage must contain no lights')
    stage_bytes=encoded({'$type':'Stagehand.StagehandConfiguration, Stagehand','Version':0,
        'DefinitionLibraryPath':str(library.resolve()),'AutosavePath':str((library.parent/'autosaves').resolve()),
        'AutomaticShowConditions':{},'AssetLibraryPreviewMode':0})
    path=str(dll);settings[path]={'$type':'Dalamud.Configuration.Internal.DevPluginSettings, Dalamud',
        'StartOnBoot':True,'NotifyForErrors':True,'AutomaticReloading':False,'WorkingPluginId':str(uuid.uuid4()),
        'DismissedValidationProblems':{'$type':'System.Collections.Generic.List`1[[System.String, System.Private.CoreLib]], System.Private.CoreLib','$values':[]}}
    locations.append({'$type':'Dalamud.Configuration.DevPluginLocationSettings, Dalamud','Path':path,'IsEnabled':True,'Nickname':'Stagehand M1 official 0.5.5'})
    after=encoded(value);backup=backup_root/uuid.uuid4().hex;backup.mkdir(parents=True)
    (backup/'dalamudConfig.before.json').write_bytes(before)
    receipt={'schema':1,'state':'prepared','plugin':path,'stage_library':str(library.resolve()),
        'config':str(config),'stage_config':str(stage_config),'config_before_sha256':hashlib.sha256(before).hexdigest(),
        'config_after_sha256':hashlib.sha256(after).hexdigest(),'stage_config_sha256':hashlib.sha256(stage_bytes).hexdigest(),
        'default_lights':0,'automatic_show_conditions':0,'r10_preserved':True,'game_dlls_changed':False}
    receipt_path=backup/'receipt.json';write_atomic(receipt_path,encoded(receipt))
    if running_game(game) or config.read_bytes()!=before:raise ValueError('Client/config changed during preparation')
    try:
        write_atomic(stage_config,stage_bytes);write_atomic(config,after)
        if config.read_bytes()!=after or stage_config.read_bytes()!=stage_bytes:raise RuntimeError('Registration verification failed')
        receipt['state']='installed_not_yet_loaded'
    except BaseException:
        # Restore only our exact writes; never overwrite another editor's changes.
        if config.exists() and config.read_bytes()==after:write_atomic(config,before)
        if stage_config.exists() and stage_config.read_bytes()==stage_bytes:stage_config.unlink()
        receipt['state']='failed_restored';write_atomic(receipt_path,encoded(receipt));raise
    write_atomic(receipt_path,encoded(receipt))
    print(json.dumps({'state':receipt['state'],'backup':str(backup),'default_lights':0,'r10_preserved':True}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('launcher','game','checked','fixtures','library','backup-root','baseline'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();install(a.launcher,a.game,a.checked,a.fixtures,a.library,a.backup_root,a.baseline)
