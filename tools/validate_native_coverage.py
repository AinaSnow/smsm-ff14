"""Rasterize the exact hair marker, including native rejection and alpha blending."""
import argparse
import json
from pathlib import Path
import numpy as np
from manage_preview import ROOT
from patch_native_coverage import build
from shader_compile import Compiler
from validate_forward_light import fixture
from offline_render import render


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    shader, meta = build(ROOT/'artifacts/client-2026.09.15', output/'patch',
                         ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe')
    original = output/'patch/original.bin'
    compiler = Compiler(); checks = []
    def check(name, actual, expected):
        error = float(np.max(np.abs(actual-expected)))
        assert np.isfinite(actual).all() and error < 2e-6, (name, error)
        checks.append({'name': name, 'passed': True, 'max_error': error})
    for name, settings in [('opaque', {}), ('alpha-half', {'alpha': .5}),
                            ('discard', {'alpha': 0}), ('depth-reject', {'depth': .4})]:
        f, inputs = fixture(compiler, output/(name+'-geometry'), **settings)
        a = render(original, output/(name+'-original'), f['width'], f['height'], **inputs)[0,0]
        b = render(shader, output/(name+'-marker'), f['width'], f['height'], **inputs)[0,0]
        check(name+' alpha retained', b[...,3], a[...,3])
        expected = np.zeros_like(b)
        if name not in ('discard', 'depth-reject'):
            expected[...,:3] = (1,0,1); expected[...,3] = a[...,3]
        check(name+' RGB marker/rejection', b, expected)
        if name == 'alpha-half':
            c = render(shader, output/'alpha-blend', f['width'], f['height'], **inputs, blend='source-alpha')[0,0]
            check('source alpha blend retained', c[...,:3], expected[...,:3]*a[...,3,None])
    f, inputs = fixture(compiler, output/'mixed-geometry')
    inputs['textures'][2][:,:f['width']//2,0] = .4
    b = render(shader, output/'mixed-output', f['width'], f['height'], **inputs)[0,0]
    expected = np.zeros_like(b); expected[:,f['width']//2:] = (1,0,1,1)
    check('mixed depth rejection retained', b, expected)
    # The marker must keep exact input/output signatures and require no new CB/SRV.
    def chunks(data):
        import struct
        result = {}
        for offset in struct.unpack_from('<'+'I'*struct.unpack_from('<I',data,28)[0],data,32):
            tag=data[offset:offset+4]; size=struct.unpack_from('<I',data,offset+4)[0]
            result[tag]=data[offset+8:offset+8+size]
        return result
    old,new=chunks(original.read_bytes()),chunks(shader.read_bytes())
    for tag in (b'ISGN',b'OSGN'):
        assert old[tag]==new[tag];checks.append({'name':tag.decode()+' unchanged','passed':True})
    meta['checks']=checks
    (output/'report.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta,indent=2))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    run(p.parse_args().output)
