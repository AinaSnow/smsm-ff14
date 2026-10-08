"""Control the explicitly installed, default-off native ambient material experiment."""
import argparse
import json
import os
from pathlib import Path
import uuid
from native_environment import current, RECEIPT


def request(game, action):
    if action not in ('on','half','off','status','coverage','audit') or os.name!='nt':
        raise ValueError('Unsupported ambient command/platform')
    owned=current(game)
    if not owned or json.loads(owned[RECEIPT]).get('shader_replacement') is not True:
        raise ValueError('An experimental material package must be explicitly installed first')
    if action=='coverage' and not json.loads(owned[RECEIPT]).get('coverage_shader_sha256'):
        raise ValueError('Installed package has no coverage marker; do not send this command to r4')
    if action=='audit' and json.loads(owned[RECEIPT]).get('output_audit') is not True:
        raise ValueError('Installed package has no output audit; do not send this command to r5')
    folder=game/'SMSM-native-captures'
    if not folder.is_dir() or folder.is_symlink() or getattr(folder.lstat(),'st_file_attributes',0)&0x400:
        raise ValueError('Initialize a real writable diagnostic directory first')
    destination=folder/'ambient-command.txt';temporary=folder/('.ambient-command-'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write((action+'\n').encode('ascii'));stream.flush();os.fsync(stream.fileno())
        os.rename(temporary,destination)
    finally:
        if temporary.exists():temporary.unlink()
    print('Submitted '+action+'; result is SMSM-native-captures/ambient-status.json after Present')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('game',type=Path)
    p.add_argument('action',choices=['on','half','off','status','coverage','audit']);args=p.parse_args();request(args.game.absolute(),args.action)
