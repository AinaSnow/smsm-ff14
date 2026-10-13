"""Build the light shaft comparison package: base (T2b -> T2c, S2c -> T2d) plus the r10 radial blur with a game/SMSM switch."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package
from shader_compile import Compiler
from build_preview import bindings
from build_dither_t2 import EXTRACTION, FIXES, TONE, edit_once, fnv

T2B = 'b6cbe48cc1ccf0fb9e045889ce03a47fd973908504e3e657578e28b586f2b0b4'
S2C = 'ecee36231ad82d5018db0abd43fac9bd6a4284631066bf47177049bdc0eeaa2f'
RADIAL = '91f970e6bbe57d99'

# On S2c the slot after D holds the sharpen "S", so "R" goes after it (x 64-74)
# with its own dark background, since the tone label box ends at x 72.
S2C_TONE_EDIT = ('  }\n}\n\nvoid orig_dec',
                 '  }\n'
                 '  if (smsmControls.y > 0.5 && all(smsmPixel >= uint2(72, 24)) && all(smsmPixel < uint2(78, 46)))\n'
                 '    o0.rgb = float3(0.025, 0.025, 0.025);\n'
                 '  if (smsmControls.y > 0.5 && smsmControls.w > 0.5 &&\n'
                 '      all(smsmPixel >= uint2(64, 28)) && all(smsmPixel < uint2(74, 42)))\n'
                 '  {\n'
                 '    static const uint rowsR[7] = {30, 17, 17, 30, 20, 18, 17};\n'
                 '    uint2 cellR = (smsmPixel - uint2(64, 28)) / 2;\n'
                 '    if ((rowsR[cellR.y] >> (4u - cellR.x)) & 1u) o0.rgb = float3(1.0, 0.85, 0.3);\n'
                 '  }\n'
                 '}\n\nvoid orig_dec')
BASES = {
    T2B: {'name': 't2b', 'id': 'r11-radial-t2c', 'tone_edit': None, 'r_box': [52, 28, 62, 42], 'label_box': [24, 24, 72, 46]},
    S2C: {'name': 's2c', 'id': 'r11-radial-t2d', 'tone_edit': S2C_TONE_EDIT, 'r_box': [64, 28, 74, 42], 'label_box': [24, 24, 78, 46]},
}

# "R" beside the dither "D" while SMSM radial blur is selected (labels shown with Ctrl+F7).
TONE_EDIT = ('    if ((rowsD[cellD.y] >> (4u - cellD.x)) & 1u) o0.rgb = float3(0.95, 0.95, 0.95);\n  }\n}\n\nvoid orig_dec',
             '    if ((rowsD[cellD.y] >> (4u - cellD.x)) & 1u) o0.rgb = float3(0.95, 0.95, 0.95);\n  }\n'
             '  if (smsmControls.y > 0.5 && smsmControls.w > 0.5 &&\n'
             '      all(smsmPixel >= uint2(52, 28)) && all(smsmPixel < uint2(62, 42)))\n'
             '  {\n'
             '    static const uint rowsR[7] = {30, 17, 17, 30, 20, 18, 17};\n'
             '    uint2 cellR = (smsmPixel - uint2(52, 28)) / 2;\n'
             '    if ((rowsR[cellR.y] >> (4u - cellR.x)) & 1u) o0.rgb = float3(1.0, 0.85, 0.3);\n'
             '  }\n'
             '}\n\nvoid orig_dec')
INI_REPLACE = ('[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\n', '[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\nw7 = 1\n')
INI_APPEND = b'''
; T2c light shafts / radial blur. w7 = 1 SMSM 8-tap, 0 game 4-tap (Ctrl+F5).
[KeySMSMRadial]
key = ctrl no_shift no_alt VK_F5
type = cycle
w7 = 0, 1
'''


def build(baseline, output, extraction=EXTRACTION):
    original, receipt = read_package(baseline)
    base_hash = digest(receipt)
    if base_hash not in BASES:
        raise ValueError('Expected the T2b or S2c package')
    base = BASES[base_hash]
    extracted = {s['Hash']: s for s in json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders']
                 if s['Profile'] == 'ps_5_0'}
    files = {n: (baseline/n).read_bytes() for n in original['files']}
    ini = files['d3dx.ini'].decode().replace('\r\n', '\n')
    if 'KeySMSMRadial' in ini or 'w7' in ini:
        raise ValueError('Unexpected base INI')
    files['d3dx.ini'] = edit_once(ini, *INI_REPLACE, 'INI').encode() + INI_APPEND
    tone_name = f'{FIXES}/{TONE}-ps_replace'
    source = files[tone_name+'.txt'].decode().replace('\r\n', '\n')
    files[tone_name+'.txt'] = edit_once(source, *(base['tone_edit'] or TONE_EDIT), 'tone indicator').encode()
    files[f'{FIXES}/{RADIAL}-ps_replace.txt'] = (ROOT/'tools/patches/radial_t2c.hlsl').read_bytes().replace(b'\r\n', b'\n')

    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    compiler = Compiler(baseline/'d3dcompiler_46.dll')
    compiled = {}
    for hash_value in (TONE, RADIAL):
        record = extracted[hash_value]
        game = (extraction/record['File']).read_bytes()
        if hashlib.sha256(game).hexdigest() != record['Sha256'] or fnv(game) != hash_value:
            raise ValueError(f'{hash_value}: extracted original does not match')
        name = f'{FIXES}/{hash_value}-ps_replace'
        binary, diagnostics = compiler.compile(output/(name+'.txt'))
        expected = dict(bindings(compiler.disassemble(game)))
        expected[('texture', 120)] = ('float4', '1d', 1)
        if bindings(compiler.disassemble(binary)) != expected:
            raise ValueError(f'{hash_value}: resource interface changed')
        files[name+'.bin'] = binary
        (output/(name+'.bin')).write_bytes(binary)
        compiled[hash_value] = (record, binary, diagnostics)

    manifest = copy.deepcopy(original)
    manifest['files'] = {n: digest(v) for n, v in files.items()}
    record, binary, diagnostics = compiled[TONE]
    manifest['shaders'][0].update(compiled_sha256=digest(binary), compiler_diagnostics=diagnostics)
    record, binary, diagnostics = compiled[RADIAL]
    manifest['shaders'].append({'hash': RADIAL, 'effect': 'dynamic-resolution radial blur (game/SMSM switch)',
                                'original_sha256': record['Sha256'], 'compiled_sha256': digest(binary),
                                'compiler_diagnostics': diagnostics})
    manifest['effects']['radial'] = {'shaders': [RADIAL], 'status': 'experimental-t2c-radial-toggle',
                                     'execution_verified': False, 'performance_verified': False}
    manifest['profiles']['daily'] = ['tone', 'dithering', 'radial']
    manifest['compatibility_candidate']['id'] = base['id']
    manifest['compatibility_candidate']['stage'] = 'T2-radial-comparison'
    manifest['compatibility_candidate']['acceptance'] = 'user compares game/SMSM light shafts in a scene that shows them'
    manifest['dither_experiment']['status'] = 'accepted-default-on'
    manifest['radial_experiment'] = {
        'id': 'radial-t2c', 'baseline_manifest_sha256': base_hash,
        'comparison': {'key': 'Ctrl+F5', 'states': ['game-4-tap', 'smsm-8-tap-jitter'], 'startup': 'smsm-8-tap-jitter',
                       'resource': 'IniParams t120[7].w', 'indicator': 'yellow R after the tone letters while SMSM (Ctrl+F7)'},
        'game_verified': False, 'visual_improvement_verified': False}
    if base['name'] == 's2c':
        manifest['sharpen_experiment']['status'] = 'accepted-default-light'
        manifest['radial_experiment']['indicator_box'] = base['r_box']
        manifest['radial_experiment']['label_box'] = base['label_box']
    (output/RECEIPT).write_bytes(encoded(manifest))
    read_package(output)
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    build(a.baseline, a.output)
    print(f'Prepared {a.output}; SMSM light shafts on, Ctrl+F5 switches game/SMSM')
