"""Freeze a minimal M2 bridge package; never bundle the Dalamud runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def package(output):
    output.mkdir(parents=True,exist_ok=False)
    build=ROOT/'plugins/StagehandBridge/bin/Release'
    official=ROOT/'artifacts/stagehand-m0/checked-v2'
    audit=json.loads((official/'report.json').read_bytes())
    names=['SMSM.StagehandBridge.dll','SMSM.StagehandBridge.json','SMSM.StagehandBridge.deps.json','Stagehand.Api.dll','Stagehand.Definitions.dll']
    for name in names:
        data=(build/name).read_bytes()
        if name.startswith('Stagehand.') and hashlib.sha256(data).hexdigest()!=audit['package_files'][name]:raise ValueError('Official API dependency mismatch')
        (output/name).write_bytes(data)
    manifest=json.loads((output/'SMSM.StagehandBridge.json').read_bytes())
    if manifest['DalamudApiLevel']!=15 or manifest['InternalName']!='SMSM.StagehandBridge':raise ValueError('Bridge identity mismatch')
    shutil.copy2(ROOT/'plugins/StagehandBridge/NOTICE.md',output/'NOTICE.md')
    shutil.copy2(ROOT/'artifacts/stagehand-upstream-m0/LICENSE.md',output/'LICENSE-AGPL-3.0.md')
    result={'schema':1,'bridge_version':manifest['AssemblyVersion'],'dalamud_api':15,'stagehand_version':'0.5.5.0','required_ipc':'1.2',
            'manual_start_only':True,'default_light_count':0,'presets':['Off','Warm','Cool'],'maximum_captures':4,'legacy_run_captures':3,'probe_presets':['Off','Warm','Cool','Off'],'lifecycle_max_seconds':60,'lifecycle_captures':0,
            'native_addon_target':'e86f0d4916054deb','live_verified':False,
            'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir())}}
    (output/'package.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);package(p.parse_args().output)
