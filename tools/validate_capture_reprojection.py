"""Actual WARP resource readback and adversarial tests for capture correspondence.

CPU ray/geometry positions are independent of inverse-projection reconstruction.
GPU pass copies those fixtures through float render targets; it is not a game capture.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import struct
import numpy as np
from capture_reprojection import evaluate, read_dds, sha, half_ulp
from manage_preview import ROOT, encoded
from offline_render import render
from shader_compile import Compiler
from validate_single_light import fixture


def dds(pixels, fmt, padding=0):
    # Test writer, deliberately separate from the production decoder.
    dtype, code = {'rgba32f': ('<f4', 2), 'rgba16f': ('<f2', 10), 'r32f': ('<f4', 41)}[fmt]
    height, width, channels = pixels.shape
    rows = np.asarray(pixels, dtype=dtype).reshape(height, -1)
    pitch = rows.shape[1] * np.dtype(dtype).itemsize + padding
    header = bytearray(148); header[:4] = b'DDS '
    for offset, value in {4:124, 8:0x100f, 12:height, 16:width, 20:pitch,
                          28:1, 76:32, 80:4, 108:0x1000, 128:code, 132:3, 140:1}.items():
        struct.pack_into('<I', header, offset, value)
    header[84:88] = b'DX10'
    return bytes(header) + b''.join(r.tobytes() + b'\xcd'*padding for r in rows)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    compiler = Compiler(ROOT/'d3dcompiler_46.dll')
    source = output/'readback.hlsl'
    source.write_text('Texture2D<float4> position : register(t0);\n'
        'Texture2D<float4> depth : register(t1);\n'
        'struct Result { float4 p:SV_TARGET0; float4 d:SV_TARGET1; };\n'
        'Result main(float4 pixel:SV_POSITION) { Result r; '
        'r.p=position.Load(int3(pixel.xy,0)); r.d=depth.Load(int3(pixel.xy,0)); return r; }\n')
    binary, diagnostics = compiler.compile(source)
    if diagnostics: raise ValueError(diagnostics)
    shader = output/'readback.bin'; shader.write_bytes(binary)
    checks, reports = [], []; gpu_draws=0
    def check(name, condition):
        if not condition: raise AssertionError(name)
        checks.append(dict(name=name, passed=True))
    def rejects(name, callback):
        try: callback()
        except (ValueError, KeyError): check(name, True)
        else: raise AssertionError('False acceptance: ' + name)
    for name, settings in [
        ('sphere', dict(geometry='sphere')), ('tilt', dict(geometry='tilt')),
        ('reverse', dict(geometry='sphere', reverse=True)),
        ('right-handed', dict(geometry='sphere', right_handed=True)),
        ('jitter', dict(geometry='sphere', jitter=(.004, -.006))),
        ('subviewport', dict(geometry='sphere', viewport=(8, 6, 80, 50))),
        ('half-position', dict(geometry='sphere')),
        ('half-depth', dict(geometry='sphere')),
        ('depth-range', dict(geometry='tilt'))]:
        f = fixture(**settings)
        p = np.concatenate((f['position'], np.ones((f['height'], f['width'], 1))), -1).astype('<f4')
        p[~f['mask']] = 0
        depth = f['textures'][0].copy(); depth[~f['mask']] = 1
        zmin, zmax = (.2, .85) if name == 'depth-range' else (0, 1)
        depth[..., 0] = zmin + depth[..., 0] * (zmax-zmin)
        gpu = render(shader, output/(name+'-gpu'), f['width'], f['height'], {0:p, 1:depth}, targets=2)[0]
        gpu_draws += 1
        check(name+' actual RGBA32 readback', np.array_equal(gpu[0], p) and np.array_equal(gpu[1], depth))
        if name in ('half-position','half-depth'):
            half = render(shader, output/(name+'-gpu16'), f['width'], f['height'], {0:p, 1:depth}, targets=2, target_format='rgba16f')[0]
            gpu_draws += 1
            channel = 0 if name == 'half-position' else 1
            check(name+' actual storage', np.max(np.abs(gpu[channel]-half[channel])) > 0)
            gpu[channel] = half[channel]
        folder = output/name; folder.mkdir()
        snapshot = dict(capture='synthetic-'+name, draw=1, phase='pre')
        specs = {}
        def resource(key, filename, raw, **extra):
            (folder/filename).write_bytes(raw)
            specs[key] = dict(path=filename, sha256=sha(raw), snapshot=deepcopy(snapshot), **extra)
        camera = np.zeros((59, 4), dtype='<f4')
        camera[14:18] = f['constants'][1][14:18]
        camera[18:22] = np.linalg.inv(f['constants'][1][14:18].astype(float))
        camera[22:26] = camera[18:22]
        resource('camera', 'camera.buf', camera.tobytes())
        resource('position', 'position.dds', dds(gpu[0], 'rgba16f' if name == 'half-position' else 'rgba32f', padding=16), format='dds')
        resource('depth', 'depth.dds', dds(gpu[1] if name=='half-depth' else gpu[1,...,:1],
                 'rgba16f' if name=='half-depth' else 'r32f', padding=4), format='dds')
        m = dict(schema=1, source_kind='synthetic', matrix_convention='row_dot_column_vector',
                 projection_rows=[18,19,20,21], position_origin='independent_view_position',
                 viewport=list(f['viewport'] or (0,0,f['width'],f['height']))+[zmin,zmax], inputs=specs)
        (folder/'manifest.json').write_bytes(encoded(m))
        report = evaluate(m, folder); (folder/'report.json').write_bytes(encoded(report))
        check(name+' independent correspondence', report['numerical_correspondence_passed'])
        check(name+' never promotes game bindings', not report['eligible_for_game_occlusion'] and not report['game_projection_verified'])
        if name.startswith('half-'):
            bad=deepcopy(m);raw=dds(gpu[1,...,:1]+.001,'r32f')
            (folder/'mismatched-depth.dds').write_bytes(raw)
            bad['inputs']['depth'].update(path='mismatched-depth.dds',sha256=sha(raw))
            check(name+' quantization allowance rejects wrong depth',not evaluate(bad,folder)['numerical_correspondence_passed'])
        reports.append(dict(name=name, **report))
        if name == 'sphere': baseline, basefolder, basecamera = deepcopy(m), folder, camera.copy()
    def edited(): return deepcopy(baseline)
    def numerical_reject(name, m):
        report = evaluate(m, basefolder)
        (output/(name+'.json')).write_bytes(encoded(report))
        check(name, not report['numerical_correspondence_passed'])
    def replace_data(m, key, filename, raw):
        (basefolder/filename).write_bytes(raw)
        m['inputs'][key].update(path=filename, sha256=sha(raw))
    m=edited(); cam=basecamera.copy(); cam[18:22]=cam[18:22].T
    replace_data(m,'camera','transposed.buf',cam.tobytes()); numerical_reject('transposed-projection',m)
    m=edited(); m['projection_rows']=[14,15,16,17]; numerical_reject('inverse-is-not-projection',m)
    m=edited(); m['viewport']=[0,0,94,64,0,1]; numerical_reject('wrong-viewport',m)
    m=edited(); cam=basecamera.copy(); cam[18:22,2]*=-1
    replace_data(m,'camera','wrong-handed.buf',cam.tobytes()); numerical_reject('wrong-handedness',m)
    m=edited(); p=read_dds((basefolder/'position.dds').read_bytes())[0]
    p[...,1]*=-1; replace_data(m,'position','flipped.dds',dds(p,'rgba32f')); numerical_reject('flipped-y',m)
    m=edited(); d=read_dds((basefolder/'depth.dds').read_bytes())[0]+.001
    replace_data(m,'depth','wrong-depth.dds',dds(d,'r32f')); numerical_reject('wrong-depth',m)
    m=edited(); m['position_origin']='reconstructed_from_depth'; numerical_reject('circular-depth-proof',m)
    m=edited(); del m['inputs']['depth']; numerical_reject('missing-independent-depth',m)
    m=edited(); p[:]=0; replace_data(m,'position','empty.dds',dds(p,'rgba32f')); numerical_reject('empty-background',m)
    m=edited(); p=read_dds((basefolder/'position.dds').read_bytes())[0]; p[:60]=0
    replace_data(m,'position','sparse.dds',dds(p,'rgba32f')); numerical_reject('sparse-coverage',m)
    m=edited(); p=read_dds((basefolder/'position.dds').read_bytes())[0]; p[...,2]=5; p[...,:2]*=5/read_dds((basefolder/'position.dds').read_bytes())[0][...,2:3]
    replace_data(m,'position','flat.dds',dds(p,'rgba32f')); numerical_reject('no-depth-diversity',m)
    for name, mutation in [
        ('cross-frame', lambda m:m['inputs']['depth']['snapshot'].update(capture='another')),
        ('cross-draw', lambda m:m['inputs']['depth']['snapshot'].update(draw=2)),
        ('post-not-pre', lambda m:m['inputs']['depth']['snapshot'].update(phase='post')),
        ('hash-mismatch', lambda m:m['inputs']['camera'].update(sha256='0'*64)),
        ('row-outside-buffer', lambda m:m.update(projection_rows=[100,101,102,103])),
        ('path-traversal', lambda m:m['inputs']['camera'].update(path='../camera.buf')),
        ('negative-viewport', lambda m:m.update(viewport=[-1,0,96,64,0,1])),
        ('unknown-convention', lambda m:m.update(matrix_convention='auto'))]:
        m=edited();mutation(m);rejects(name,lambda:evaluate(m,basefolder))
    for name, raw in [('truncated-camera',basecamera.tobytes()[:-1]),('short-camera',basecamera[:6].tobytes()),
                      ('nan-camera',np.full_like(basecamera,np.nan).tobytes()),('singular-camera',np.zeros_like(basecamera).tobytes())]:
        m=edited();replace_data(m,'camera',name+'.buf',raw);rejects(name,lambda:evaluate(m,basefolder))
    good=(basefolder/'position.dds').read_bytes()
    rejects('DDS truncated',lambda:read_dds(good[:-1]))
    rejects('DDS trailing bytes',lambda:read_dds(good+b'\x00'))
    rejects('JPEG rejected',lambda:read_dds(b'\xff\xd8\xff'+bytes(200)))
    for name, offset, value in [('mips',28,2),('array',140,2),('typeless',128,1),('volume',132,4),('pitch',20,1),('cube',136,4)]:
        raw=bytearray(good);struct.pack_into('<I',raw,offset,value)
        rejects('DDS '+name,lambda:read_dds(raw))
    # Raw readback import uses exact byte sizes and explicit dimensions, too.
    m=edited();raw=read_dds(good)[0].astype('<f4').tobytes()
    replace_data(m,'position','position.f32',raw)
    m['inputs']['position'].update(format='rgba32f',width=96,height=64)
    check('raw float input',evaluate(m,basefolder)['numerical_correspondence_passed'])
    m['inputs']['position']['width']=95
    rejects('raw dimensions mismatch',lambda:evaluate(m,basefolder))
    check('finite half endpoints and subnormal ULP',np.array_equal(
        half_ulp(np.array([0.,2**-24,2**-14,1.,-1.,65504.])),[2**-24,2**-24,2**-24,2**-10,2**-10,32.]))
    result=dict(check_count=len(checks),all_passed=True,checks=checks,fixtures=reports,
        shader_sha256=sha(binary),gpu_draws=gpu_draws,game_capture_tested=False,game_files_modified=False,
        source_sha256={name:sha((ROOT/name).read_bytes()) for name in (
            'tools/capture_reprojection.py','tools/validate_capture_reprojection.py',
            'tools/validate_single_light.py','tools/offline_render.py','tools/offline/render_ps.cpp')},
        limits=['Synthetic CPU ray fixtures copied through real WARP float targets, not game captures',
                'Metadata and position independence are declared; lineage still needs external evidence',
                'Numerical pass never permits expanding game constant buffer bindings'])
    (output/'report.json').write_bytes(encoded(result))
    print(json.dumps(dict(checks=len(checks),gpu_draws=gpu_draws,maximum_pixel_error=max(r['pixel']['maximum'] for r in reports)),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    run(parser.parse_args().output)
