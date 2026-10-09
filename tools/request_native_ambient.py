"""Control the explicitly installed, default-off native ambient material experiment."""
import argparse
import json
import os
from pathlib import Path
import uuid
import re
from native_environment import current, RECEIPT


def request(game, action, shader=None, skip=0, vertex=None, elements=None):
    if action not in ('on','half','off','status','coverage','audit','census','sample','probe') or os.name!='nt':
        raise ValueError('Unsupported ambient command/platform')
    owned=current(game)
    if not owned or json.loads(owned[RECEIPT]).get('shader_replacement') is not True:
        raise ValueError('An experimental material package must be explicitly installed first')
    if action=='coverage' and not json.loads(owned[RECEIPT]).get('coverage_shader_sha256'):
        raise ValueError('Installed package has no coverage marker; do not send this command to r4')
    if action=='audit' and json.loads(owned[RECEIPT]).get('output_audit') is not True:
        raise ValueError('Installed package has no output audit; do not send this command to r5')
    if action in ('census','sample','probe') and not json.loads(owned[RECEIPT]).get('material_roster_sha256'):
        raise ValueError('Installed package has no verified material roster')
    if action=='probe':
        if not json.loads(owned[RECEIPT]).get('material_input_probe'):raise ValueError('Installed package does not support material-input probe')
        if not isinstance(shader,str) or not re.fullmatch('[0-9a-f]{16}',shader) or not isinstance(vertex,str) or not re.fullmatch('[0-9a-f]{64}',vertex) or type(elements) is not int or not 1<=elements<=10000000 or skip!=0:
            raise ValueError('Probe needs exact PS/VS identities and element count')
        action=f'probe {shader} {elements} {vertex}'
    elif vertex is not None or elements is not None:raise ValueError('Vertex/elements only apply to probe')
    elif action=='sample':
        if not isinstance(shader,str) or not re.fullmatch('[0-9a-f]{16}',shader) or type(skip) is not int or not 0<=skip<=4096:
            raise ValueError('Sample needs an exact lowercase shader hash and skip in 0..4096')
        action=f'sample {shader} {skip}'
    elif shader is not None or skip!=0:raise ValueError('Shader/skip only apply to sample')
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
    p.add_argument('action',choices=['on','half','off','status','coverage','audit','census','sample','probe'])
    p.add_argument('--shader');p.add_argument('--skip',type=int,default=0)
    p.add_argument('--vertex');p.add_argument('--elements',type=int)
    args=p.parse_args();request(args.game.absolute(),args.action,args.shader,args.skip,args.vertex,args.elements)
