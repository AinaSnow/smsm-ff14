"""Update an explicitly unloaded developer bridge; preserve its prior complete package.

The registered folder becomes the deployment copy. Immutable build candidates and
the archived prior package remain separate. Never changes Dalamud config or game DLLs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import uuid
from manage_preview import write_atomic, encoded

ROOT = Path(__file__).resolve().parents[1]
NAME = 'SMSM.StagehandBridge.dll'


def package(folder):
    folder = folder.resolve(strict=True)
    if not folder.is_relative_to((ROOT/'artifacts').resolve()) or folder.is_symlink():
        raise ValueError('Expected a workspace artifact directory')
    meta = json.loads((folder/'package.json').read_bytes())
    if meta['manual_start_only'] is not True or meta['default_light_count'] != 0:
        raise ValueError('Expected default-off bridge package')
    result = {'package.json': (folder/'package.json').read_bytes()}
    for name, sha in meta['files'].items():
        if Path(name).name != name or (folder/name).is_symlink(): raise ValueError('Unexpected package path')
        raw = (folder/name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha: raise ValueError('Package integrity failure')
        result[name] = raw
    return meta, result


def check_unloaded(launcher, target):
    config = json.loads((launcher/'dalamudConfig.json').read_text(encoding='utf-8-sig'))
    matches = [x for x in config['DevPluginLoadLocations']['$values'] if Path(x['Path']).name == NAME]
    if len(matches) != 1 or Path(matches[0]['Path']).resolve() != target/NAME:
        raise ValueError('Target is not the single registered bridge')
    lines = (launcher/'dalamud.log').read_text(encoding='utf-8-sig', errors='replace').splitlines()
    markers = [line for line in lines if '[LocalPlugin]' in line and any(s in line for s in
        ['Loading SMSM.StagehandBridge.dll', 'Finished loading SMSM.StagehandBridge', 'Finished unloading SMSM.StagehandBridge'])]
    if not markers or 'Finished unloading SMSM.StagehandBridge' not in markers[-1]:
        raise ValueError('Disable the bridge and wait for its finished-unloading log first')
    owned = json.loads((launcher/'pluginConfigs/SMSM.StagehandBridge.json').read_text(encoding='utf-8-sig'))['OwnedStages']
    if owned: raise ValueError('Bridge still owns a test Stage')
    control = launcher/'pluginConfigs/SMSM.StagehandBridge'
    if any((p/'command.txt').exists() for p in (control, control/'control-v2')):
        raise ValueError('Pending command prevents update')


def deploy(launcher, target, source, expected_old):
    target = target.resolve(strict=True); source = source.resolve(strict=True)
    if target == source: raise ValueError('Keep candidate separate from deployment')
    _, before = package(target); meta, after = package(source)
    if hashlib.sha256(before[NAME]).hexdigest() != expected_old:
        raise ValueError('Unexpected installed bridge')
    if set(before) != set(after): raise ValueError('Hot update cannot add or remove package files')
    check_unloaded(launcher, target)
    backup = ROOT/'artifacts/stagehand-m2/hot-deploy-backups'/uuid.uuid4().hex
    backup.mkdir(parents=True)
    for name, raw in before.items(): (backup/name).write_bytes(raw)
    changed = []
    try:
        check_unloaded(launcher, target)
        # DLL first: if the loader still holds it, fail before touching the manifest.
        for name in [NAME] + sorted(set(after)-{NAME, 'package.json'}) + ['package.json']:
            if before[name] == after[name]: continue
            if (target/name).read_bytes() != before[name]: raise ValueError('Deployment changed during update')
            write_atomic(target/name, after[name]); changed.append(name)
        if any((target/n).read_bytes() != raw for n, raw in after.items()): raise ValueError('Deployment verification failed')
    except BaseException:
        for name in reversed(changed):
            if (target/name).read_bytes() != after[name]: raise RuntimeError('External change prevents rollback; prior package retained at '+str(backup))
            write_atomic(target/name, before[name])
        raise
    receipt = {'version': meta['bridge_version'], 'deployment': str(target), 'candidate': str(source),
               'frozen_previous_package': str(backup), 'game_dlls_changed': False, 'dalamud_config_changed': False,
               'new_dll_sha256': meta['files'][NAME]}
    write_atomic(backup/'hot-deployment.json', encoded(receipt))
    print(json.dumps(receipt))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('launcher', 'target', 'source'): p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--expected-old', required=True)
    a = p.parse_args(); deploy(a.launcher, a.target, a.source, a.expected_old)
