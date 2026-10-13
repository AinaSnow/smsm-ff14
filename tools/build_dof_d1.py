"""Build the D0+D1 GPose bokeh package: deployed T2d (2026.10.06) plus the switchable blur pass 00f2b6068017c6c6."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package
from shader_compile import Compiler
from build_preview import verify_interface
from build_dither_t2 import FIXES, TONE, edit_once, fnv

T2D = '7fe078e01f5ed997b26af0c0a5ee1122c126f370b85475033f55d17d865c730e'
EXTRACTION = ROOT/'artifacts/client-2026.10.06'
BLUR = '00f2b6068017c6c6'

# "B" after R (x 76-86) while highlight bokeh is on; label background extended to x 90.
TONE_EDIT = ('  }\n}\n\nvoid orig_dec',
             '  }\n'
             '  float d1Level = IniParams.Load(int2(6, 0)).y;\n'
             '  if (smsmControls.y > 0.5 && all(smsmPixel >= uint2(78, 24)) && all(smsmPixel < uint2(90, 46)))\n'
             '    o0.rgb = float3(0.025, 0.025, 0.025);\n'
             '  if (smsmControls.y > 0.5 && d1Level > 0.5 &&\n'
             '      all(smsmPixel >= uint2(76, 28)) && all(smsmPixel < uint2(86, 42)))\n'
             '  {\n'
             '    static const uint rowsB[7] = {30, 17, 17, 30, 17, 17, 30};\n'
             '    uint2 cellB = (smsmPixel - uint2(76, 28)) / 2;\n'
             '    if ((rowsB[cellB.y] >> (4u - cellB.x)) & 1u)\n'
             '      o0.rgb = d1Level > 1.5 ? float3(1.0, 0.5, 0.3) : float3(1.0, 0.95, 0.6);\n'
             '  }\n'
             '}\n\nvoid orig_dec')
INI_ANCHOR = 'z7 = 1\nw7 = 1\nx6 = 1\n'
INI_APPEND = b'''
; D0/D1 GPose depth of field (00f2b6068017c6c6). y6 = highlight bokeh 0 off, 1 normal, 2 strong (Ctrl+F2);
; z6 = 1 tints the blur pass purple to prove it runs (Ctrl+F3).
[KeySMSMBokeh]
key = ctrl no_shift no_alt VK_F2
type = cycle
y6 = 0, 1, 2
[KeySMSMBokehDiagnostic]
key = ctrl no_shift no_alt VK_F3
type = cycle
z6 = 1, 0
'''


def build(baseline, output, extraction=EXTRACTION):
    original, receipt = read_package(baseline)
    if digest(receipt) != T2D:
        raise ValueError('Expected the deployed T2d (2026.10.06) package')
    files = {n: (baseline/n).read_bytes() for n in original['files']}
    ini = files['d3dx.ini'].decode().replace('\r\n', '\n')
    if 'KeySMSMBokeh' in ini or 'y6' in ini or 'z6' in ini:
        raise ValueError('Unexpected base INI')
    files['d3dx.ini'] = edit_once(ini, INI_ANCHOR, INI_ANCHOR + 'y6 = 1\nz6 = 0\n', 'INI').encode() + INI_APPEND
    tone_name = f'{FIXES}/{TONE}-ps_replace'
    source = files[tone_name+'.txt'].decode().replace('\r\n', '\n')
    files[tone_name+'.txt'] = edit_once(source, *TONE_EDIT, 'tone indicator').encode()
    files[f'{FIXES}/{BLUR}-ps_replace.txt'] = (ROOT/'tools/patches/dof_bokeh_d1.hlsl').read_bytes().replace(b'\r\n', b'\n')

    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    records = {s['Hash']: s for s in json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders']
               if s['Profile'] == 'ps_5_0'}
    compiler = Compiler((baseline/'d3dcompiler_46.dll').resolve())
    compiled = {}
    for hash_value in (TONE, BLUR):
        record = records[hash_value]
        game = (extraction/record['File']).read_bytes()
        if hashlib.sha256(game).hexdigest() != record['Sha256'] or fnv(game) != hash_value:
            raise ValueError(f'{hash_value}: extracted original does not match')
        name = f'{FIXES}/{hash_value}-ps_replace'
        binary, diagnostics = compiler.compile(output/(name+'.txt'))
        verify_interface(compiler.disassemble(game), compiler.disassemble(binary), allow_ini_params=True)
        files[name+'.bin'] = binary
        (output/(name+'.bin')).write_bytes(binary)
        compiled[hash_value] = (record, binary, diagnostics)

    manifest = copy.deepcopy(original)
    manifest['files'] = {n: digest(v) for n, v in files.items()}
    record, binary, diagnostics = compiled[TONE]
    manifest['shaders'][0].update(compiled_sha256=digest(binary), compiler_diagnostics=diagnostics)
    record, binary, diagnostics = compiled[BLUR]
    manifest['shaders'].append({'hash': BLUR, 'effect': 'gpose near/far aperture blur (D1 highlight bokeh, D0 marker)',
                                'original_sha256': record['Sha256'], 'compiled_sha256': digest(binary),
                                'compiler_diagnostics': diagnostics})
    manifest['effects']['dof'] = {'shaders': [BLUR], 'status': 'experimental-d1-highlight-bokeh',
                                  'execution_verified': False, 'performance_verified': False}
    manifest['profiles']['daily'] = ['tone', 'dithering', 'radial', 'dof']
    manifest['compatibility_candidate']['id'] = 'r11-dof-d1-2026.10.06'
    manifest['compatibility_candidate']['stage'] = 'D0-D1-gpose-bokeh'
    manifest['compatibility_candidate']['acceptance'] = 'D0 purple proves execution; user compares D1 off/normal/strong in /gpose'
    manifest['radial_experiment']['status'] = 'accepted-default-smsm'
    manifest['dof_experiment'] = {
        'id': 'dof-d1', 'baseline_manifest_sha256': T2D,
        'comparison': {'key': 'Ctrl+F2', 'states': ['off', 'normal-k6', 'strong-k16'], 'startup': 'normal-k6',
                       'resource': 'IniParams t120[6].y', 'indicator': 'B after R: pale yellow normal, orange strong'},
        'diagnostic': {'key': 'Ctrl+F3', 'resource': 'IniParams t120[6].z', 'startup': 'off', 'effect': 'purple tint on this pass'},
        'label_box': [24, 24, 90, 46], 'indicator_box': [76, 28, 86, 42],
        'game_verified': False, 'visual_improvement_verified': False}
    (output/RECEIPT).write_bytes(encoded(manifest))
    read_package(output)
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    build(a.baseline, a.output)
    print(f'Prepared {a.output}; highlight bokeh normal, Ctrl+F2 cycles, Ctrl+F3 purple diagnostic')
