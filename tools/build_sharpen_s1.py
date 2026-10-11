"""Build the S1/S2 sharpening comparison package: T2b (tone A + dither) plus sharpening in tone mapping.

S1: CAS-style 5-tap cross with a hard clamp (in game: below the visible threshold).
S2 (--variant s2): radius-2 unsharp mask with limited overshoot, levels 0/1/2.
"""
import argparse
import copy
import json
from pathlib import Path
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package
from shader_compile import Compiler
from build_preview import bindings
from build_dither_t2 import EXTRACTION, FIXES, TONE, edit_once

T2B = 'b6cbe48cc1ccf0fb9e045889ce03a47fd973908504e3e657578e28b586f2b0b4'
VARIANTS = {
    's1': {'patch': 'tone_sharpen_s1.hlsl', 'startup': '0.5', 'cycle': '0, 0.5, 1', 'strong_threshold': '0.75',
           'id': 'r11-sharpen-s1', 'experiment': 'sharpen-s1', 'states': ['off', 'medium-0.5', 'strong-1.0'],
           'method': 'CAS-style 5-tap cross on HDR input in u=c/(1+c), clamped to cross min/max'},
    's2': {'patch': 'tone_sharpen_s2.hlsl', 'startup': '1', 'cycle': '0, 1, 2', 'strong_threshold': '1.5',
           'id': 'r11-sharpen-s2', 'experiment': 'sharpen-s2', 'states': ['off', 'medium-2x-k0.2', 'strong-4x-k0.4'],
           'method': 'radius-2 13-tap unsharp mask on HDR input in u=c/(1+c); overshoot limited to k*(max-min) in linear HDR'},
    's2b': {'patch': 'tone_sharpen_s2b.hlsl', 'startup': '1', 'cycle': '0, 1, 2', 'strong_threshold': '1.5',
            'id': 'r11-sharpen-s2b', 'experiment': 'sharpen-s2b', 'states': ['off', 'medium-2x-k0.2', 'strong-4x-k0.4'],
            'method': 'S2 plus highlight protection: amount *= 1 - smoothstep(0.9, 1.05, SMSM display brightness of the 13-tap peak)'},
}

SAMPLE_ANCHOR = '  color = sInput.T.Sample(sInput.S_s, v1.xy);\n  float3 sourceColor = color.rgb;\n'
# "S" after the tone letter and D: light blue = medium, orange = strong (labels shown with Ctrl+F7).
INDICATOR = ('    if ((rowsD[cellD.y] >> (4u - cellD.x)) & 1u) o0.rgb = float3(0.95, 0.95, 0.95);\n  }\n}\n\nvoid orig_dec',
             '    if ((rowsD[cellD.y] >> (4u - cellD.x)) & 1u) o0.rgb = float3(0.95, 0.95, 0.95);\n  }\n'
             '  float s1Level = IniParams.Load(int2(6, 0)).x;\n'
             '  if (smsmControls.y > 0.5 && s1Level > 0 &&\n'
             '      all(smsmPixel >= uint2(52, 28)) && all(smsmPixel < uint2(62, 42)))\n'
             '  {\n'
             '    static const uint rowsS[7] = {15, 16, 16, 14, 1, 1, 30};\n'
             '    uint2 cellS = (smsmPixel - uint2(52, 28)) / 2;\n'
             '    if ((rowsS[cellS.y] >> (4u - cellS.x)) & 1u)\n'
             '      o0.rgb = s1Level > STRONG ? float3(1.0, 0.55, 0.15) : float3(0.45, 0.8, 1.0);\n'
             '  }\n'
             '}\n\nvoid orig_dec')
INI_ANCHOR = '[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\n'
INI_APPEND = '''
; {name} sharpening in tone mapping. x6 = level: {cycle} (off, medium, strong; Ctrl+F4).
[KeySMSMSharpen]
key = ctrl no_shift no_alt VK_F4
type = cycle
x6 = {cycle}
'''


def build(baseline, output, extraction=EXTRACTION, variant='s1'):
    v = VARIANTS[variant]
    original, receipt = read_package(baseline)
    if digest(receipt) != T2B:
        raise ValueError('Expected the deployed T2b package')
    files = {n: (baseline/n).read_bytes() for n in original['files']}
    ini = files['d3dx.ini'].decode().replace('\r\n', '\n')
    if 'KeySMSMSharpen' in ini or 'x6' in ini:
        raise ValueError('Unexpected T2b INI')
    ini = edit_once(ini, INI_ANCHOR, INI_ANCHOR + 'x6 = ' + v['startup'] + '\n', 'INI')
    files['d3dx.ini'] = (ini + INI_APPEND.format(name=variant.upper(), cycle=v['cycle'])).encode()
    name = f'{FIXES}/{TONE}-ps_replace'
    source = files[name+'.txt'].decode().replace('\r\n', '\n')
    patch = (ROOT/'tools/patches'/v['patch']).read_text(encoding='utf-8')
    head, tail = SAMPLE_ANCHOR.split('\n', 1)
    source = edit_once(source, SAMPLE_ANCHOR, head + '\n' + patch + tail, 'tone sample')
    source = edit_once(source, INDICATOR[0], INDICATOR[1].replace('STRONG', v['strong_threshold']), 'tone indicator')
    files[name+'.txt'] = source.encode()

    output.mkdir(parents=True, exist_ok=False)
    for path_name, data in files.items():
        path = output/path_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    compiler = Compiler(baseline/'d3dcompiler_46.dll')
    record = {s['Hash']: s for s in json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders']}[TONE]
    binary, diagnostics = compiler.compile(output/(name+'.txt'))
    expected = dict(bindings(compiler.disassemble((extraction/record['File']).read_bytes())))
    expected[('texture', 120)] = ('float4', '1d', 1)
    if bindings(compiler.disassemble(binary)) != expected:
        raise ValueError('Tone resource interface changed')
    files[name+'.bin'] = binary
    (output/(name+'.bin')).write_bytes(binary)

    manifest = copy.deepcopy(original)
    manifest['files'] = {n: digest(v_) for n, v_ in files.items()}
    manifest['shaders'][0].update(compiled_sha256=digest(binary), compiler_diagnostics=diagnostics)
    manifest['compatibility_candidate']['id'] = v['id']
    manifest['compatibility_candidate']['stage'] = 'S1-sharpen-comparison'
    manifest['compatibility_candidate']['acceptance'] = 'user compares off/medium/strong on hair and fine detail'
    manifest['dither_experiment']['status'] = 'accepted-default-on'
    manifest['sharpen_experiment'] = {
        'id': v['experiment'], 'baseline_manifest_sha256': T2B, 'method': v['method'],
        'comparison': {'key': 'Ctrl+F4', 'states': v['states'], 'startup': v['states'][1],
                       'resource': 'IniParams t120[6].x', 'indicator': 'S after the tone letters: light blue medium, orange strong'},
        'note': 'inside the tone effect; manager effect selection does not separate it',
        'game_verified': False, 'visual_improvement_verified': False}
    (output/RECEIPT).write_bytes(encoded(manifest))
    read_package(output)
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--variant', choices=sorted(VARIANTS), default='s1')
    a = p.parse_args()
    build(a.baseline, a.output, variant=a.variant)
    print(f'Prepared {a.output} ({a.variant}); sharpening medium, Ctrl+F4 cycles off/medium/strong')
