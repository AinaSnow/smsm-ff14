"""Back up and disable external Dalamud viewports; freeze only SMSM's test bridge."""
import argparse
import copy
import json
from pathlib import Path
from manage_preview import digest, encoded, running_game, write_atomic


def adjusted(config):
    result = copy.deepcopy(config)
    result['IsDisableViewport'] = True
    locations = result.get('DevPluginLoadLocations', {}).get('$values', [])
    for entry in locations:
        if entry.get('Path', '').replace('\\', '/').rsplit('/', 1)[-1].lower() == 'smsm.stagehandbridge.dll':
            entry['IsEnabled'] = False
    settings = result.get('DevPluginSettings', {})
    for path, value in settings.items():
        if path.replace('\\', '/').rsplit('/', 1)[-1].lower() == 'smsm.stagehandbridge.dll':
            value['StartOnBoot'] = False
    return result


def configure(config, backup, game, restore=False):
    if running_game(game):
        raise ValueError('Exit FF14 before changing Dalamud configuration')
    for path in (config, *config.absolute().parents):
        if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse configuration path')
    before = config.read_bytes()
    if restore:
        meta = json.loads((backup/'config-change.json').read_bytes())
        after = (backup/'dalamudConfig.before.json').read_bytes()
        if str(config.resolve()) != meta['config'] or digest(before) != meta['after_sha256'] or digest(after) != meta['before_sha256']:
            raise ValueError('Configuration changed since migration; merge saved fields manually to preserve newer settings')
    else:
        after = encoded(adjusted(json.loads(before)))
        backup.mkdir(parents=True, exist_ok=False)
        (backup/'dalamudConfig.before.json').write_bytes(before)
        (backup/'config-change.json').write_bytes(encoded({'config': str(config.resolve()),
            'before_sha256': digest(before), 'after_sha256': digest(after),
            'changes': ['IsDisableViewport=true', 'SMSM.StagehandBridge disabled; standalone Stagehand preserved']}))
    if running_game(game) or config.read_bytes() != before:
        raise ValueError('Game started or configuration changed during backup')
    write_atomic(config, after)
    if config.read_bytes() != after:
        raise ValueError('Configuration verification failed')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True, type=Path)
    p.add_argument('--backup', required=True, type=Path)
    p.add_argument('--game', required=True, type=Path)
    p.add_argument('--restore', action='store_true')
    args = p.parse_args()
    configure(args.config, args.backup, args.game, args.restore)
    print('Configuration verified; backup retained. Actual game/UI acceptance pending.')
