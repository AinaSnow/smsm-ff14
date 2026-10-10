"""Build the T2b dithering comparison package: tone A default with dithering inside tone mapping.

T2 (first build) put dithering in r10's output-copy shader 23d27700572e0c4d; in game its
indicator never appeared with DLSS or FSR, so that copy is not on the displayed path.
T2b adds the same noise at the end of the tone shader, whose label is visibly displayed,
and keeps r10's vignette dither 782e995758bf001d.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package
from shader_compile import Compiler
from build_preview import bindings

A_DEFAULT = 'e0804b681fcd63abc6f8b0792c5e6548478bd5f15e1f3dcf60329ec716322617'
R10 = 'artifacts/preview-2026.09.15-r10-managed'
EXTRACTION = ROOT.parent/'smsm-ff14/artifacts/client-2026.09.15'
FIXES = 'SMSM-ShaderFixes'
TONE = '72a656dfd52149ad'
VIGNETTE = '782e995758bf001d'

# Insert the dither after the tone mode output and before the label; add "D" after the label.
TONE_EDITS = [
    ('  // Mode label: "R10" in blue', None),   # None: replaced with the dither patch + anchor
    ('  }\n}\n\nvoid orig_dec',
     '  }\n'
     '  // "D" beside the tone letter while dithering is on (labels shown with Ctrl+F7).\n'
     '  if (smsmControls.y > 0.5 && smsmControls.z > 0.5 &&\n'
     '      all(smsmPixel >= uint2(40, 28)) && all(smsmPixel < uint2(50, 42)))\n'
     '  {\n'
     '    static const uint rowsD[7] = {28, 18, 17, 17, 17, 18, 28};\n'
     '    uint2 cellD = (smsmPixel - uint2(40, 28)) / 2;\n'
     '    if ((rowsD[cellD.y] >> (4u - cellD.x)) & 1u) o0.rgb = float3(0.95, 0.95, 0.95);\n'
     '  }\n'
     '}\n\nvoid orig_dec'),
]
VIGNETTE_EDIT = ('  o0.w += dither;\n',
                 '  // T2: z7 switches dithering (Ctrl+F6); 0 leaves the plain vignette.\n'
                 '  o0.w += dither * IniParams.Load(int2(7, 0)).z;\n')

INI_REPLACE = ('[Constants]\nx7 = 1\ny7 = 0\n', '[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\n')
INI_APPEND = b'''
; T2b dithering inside tone mapping and the vignette. z7 = on/off (Ctrl+F6).
[KeySMSMDither]
key = ctrl no_shift no_alt VK_F6
type = cycle
z7 = 0, 1
'''


def fnv(data):
    value = 0
    for byte in data:
        value = ((value * 0x100000001b3) & 0xffffffffffffffff) ^ byte
    return f'{value:016x}'


def edit_once(source, old, new, what):
    if source.count(old) != 1:
        raise ValueError(f'{what}: edit anchor changed')
    return source.replace(old, new)


def build(baseline, output, r10=ROOT/R10, extraction=EXTRACTION):
    original, receipt = read_package(baseline)
    if digest(receipt) != A_DEFAULT:
        raise ValueError('Expected the deployed tone A default package')
    extracted = {s['Hash']: s for s in json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders']
                 if s['Profile'] == 'ps_5_0'}
    files = {n: (baseline/n).read_bytes() for n in original['files']}
    ini = files['d3dx.ini'].decode().replace('\r\n', '\n')
    if 'KeySMSMDither' in ini or 'z7' in ini:
        raise ValueError('Unexpected A default INI')
    files['d3dx.ini'] = edit_once(ini, *INI_REPLACE, 'INI').encode() + INI_APPEND

    tone_name = f'{FIXES}/{TONE}-ps_replace'
    source = files[tone_name+'.txt'].decode().replace('\r\n', '\n')
    patch = (ROOT/'tools/patches/tone_dither_t2.hlsl').read_text(encoding='utf-8')
    anchor = TONE_EDITS[0][0]
    source = edit_once(source, anchor, patch + anchor, 'tone dither')
    source = edit_once(source, *TONE_EDITS[1], 'tone indicator')
    files[tone_name+'.txt'] = source.encode()
    vignette = (r10/FIXES/f'{VIGNETTE}-ps_replace.txt').read_text(encoding='utf-8').replace('\r\n', '\n')
    files[f'{FIXES}/{VIGNETTE}-ps_replace.txt'] = edit_once(vignette, *VIGNETTE_EDIT, 'vignette').encode()

    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    compiler = Compiler(baseline/'d3dcompiler_46.dll')
    compiled = {}
    for hash_value in (TONE, VIGNETTE):
        record = extracted[hash_value]
        game = (extraction/record['File']).read_bytes()
        if hashlib.sha256(game).hexdigest() != record['Sha256'] or fnv(game) != hash_value:
            raise ValueError(f'{hash_value}: extracted original does not match')
        name = f'{FIXES}/{hash_value}-ps_replace'
        binary, diagnostics = compiler.compile(output/(name+'.txt'))
        # Same resources as the game shader plus only the 3DMigoto parameter texture.
        expected = dict(bindings(compiler.disassemble(game)))
        expected[('texture', 120)] = ('float4', '1d', 1)
        if bindings(compiler.disassemble(binary)) != expected:
            raise ValueError(f'{hash_value}: resource interface changed')
        files[name+'.bin'] = binary
        (output/(name+'.bin')).write_bytes(binary)
        compiled[hash_value] = (record, binary, diagnostics)

    manifest = copy.deepcopy(original)
    manifest['files'] = {n: digest(v) for n, v in files.items()}
    tone_row = manifest['shaders'][0]
    record, binary, diagnostics = compiled[TONE]
    tone_row['compiled_sha256'] = digest(binary)
    tone_row['compiler_diagnostics'] = diagnostics
    record, binary, diagnostics = compiled[VIGNETTE]
    manifest['shaders'].append({'hash': VIGNETTE, 'effect': 'vignette dithering', 'original_sha256': record['Sha256'],
                                'compiled_sha256': digest(binary), 'compiler_diagnostics': diagnostics})
    manifest['effects']['dithering'] = {'shaders': [VIGNETTE], 'status': 'experimental-t2b-dither-toggle',
                                        'execution_verified': False, 'performance_verified': False}
    manifest['profiles']['daily'] = ['tone', 'dithering']
    manifest['compatibility_candidate']['id'] = 'r11-dither-t2b'
    manifest['compatibility_candidate']['stage'] = 'T2-dithering-comparison'
    manifest['compatibility_candidate']['acceptance'] = 'user compares dithering on/off on sky gradients and dark areas'
    manifest['dither_experiment'] = {
        'id': 'dither-t2b', 'baseline_manifest_sha256': A_DEFAULT,
        'comparison': {'key': 'Ctrl+F6', 'states': ['off', 'on'], 'startup': 'on', 'resource': 'IniParams t120[7].z',
                       'indicator': 'white D beside the tone letter while on (Ctrl+F7)'},
        'placement': 'end of tone mapping 72a656dfd52149ad (inside the tone effect) + vignette 782e995758bf001d',
        'excluded': {'23d27700572e0c4d': 'output copy not on the displayed path with DLSS/FSR (T2 in-game indicator never shown)',
                     '12dd4d7295446a19': 'not executed in the 2026.09.15 capture'},
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
    print(f'Prepared {a.output}; tone A + dithering on, Ctrl+F6 toggles dithering')
