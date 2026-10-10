"""Build the T2 dithering comparison package: tone A default plus r10's two live dither shaders."""
import argparse
import copy
import hashlib
import re
from pathlib import Path
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package
from shader_compile import Compiler
from build_preview import bindings

A_DEFAULT = 'e0804b681fcd63abc6f8b0792c5e6548478bd5f15e1f3dcf60329ec716322617'
R10 = 'artifacts/preview-2026.09.15-r10-managed'
EXTRACTION = ROOT.parent/'smsm-ff14/artifacts/client-2026.09.15'
FIXES = 'SMSM-ShaderFixes'
OUTPUT = '23d27700572e0c4d'    # current-pipeline scene output copy (post tone mapping)
VIGNETTE = '782e995758bf001d'
EFFECTS = {OUTPUT: 'post-tonemap output dithering', VIGNETTE: 'vignette dithering'}

# Each edit must match exactly once in the r10 source.
EDITS = {
    OUTPUT: [
        ('    if (IniParams.Load(int2(0, 0)).x > 0.5) {\n',
         '    // T2: z7 switches dithering (Ctrl+F6); x is still the post-tone stage marker.\n'
         '    float4 smsmControls = IniParams.Load(int2(7, 0));\n'
         '    bool smsmFinal = IniParams.Load(int2(0, 0)).x > 0.5;\n'
         '    if (smsmFinal && smsmControls.z > 0.5) {\n'),
        ('    return value;\n}\n',
         '    // "D" beside the tone label while dithering is on (labels shown with Ctrl+F7).\n'
         '    uint2 smsmPixel = (uint2)position.xy;\n'
         '    if (smsmFinal && smsmControls.y > 0.5 && smsmControls.z > 0.5 &&\n'
         '        all(smsmPixel >= uint2(40, 28)) && all(smsmPixel < uint2(50, 42)))\n'
         '    {\n'
         '        static const uint rowsD[7] = {28, 18, 17, 17, 17, 18, 28};\n'
         '        uint2 cell = (smsmPixel - uint2(40, 28)) / 2;\n'
         '        if ((rowsD[cell.y] >> (4u - cell.x)) & 1u) value.rgb = float3(0.95, 0.95, 0.95);\n'
         '    }\n'
         '    return value;\n}\n'),
    ],
    VIGNETTE: [
        ('  o0.w += dither;\n',
         '  // T2: z7 switches dithering (Ctrl+F6); 0 leaves the plain vignette.\n'
         '  o0.w += dither * IniParams.Load(int2(7, 0)).z;\n'),
    ],
}

# Diagnostic indicator: drawn on every copy while labels are shown; colour reports the state.
# white = armed + dither on, yellow = armed + dither off, red = copy ran without the tone marker.
DIAGNOSTIC_INDICATOR = (
    '    if (smsmFinal && smsmControls.y > 0.5 && smsmControls.z > 0.5 &&\n',
    '    if (smsmControls.y > 0.5 &&\n')
DIAGNOSTIC_COLOUR = (
    'value.rgb = float3(0.95, 0.95, 0.95);',
    'value.rgb = !smsmFinal ? float3(1, 0.1, 0.1) : smsmControls.z > 0.5 ? float3(0.95, 0.95, 0.95) : float3(1, 0.85, 0.1);')

INI_REPLACE = ('[Constants]\nx7 = 1\ny7 = 0\n',
               '[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\nx = 0\n')
INI_APPEND = b'''
; T2 dithering. x marks the final scene copy: armed by tone mapping, consumed by
; the copy shader and reset every frame. z7 = dithering on/off (Ctrl+F6).
[KeySMSMDither]
key = ctrl no_shift no_alt VK_F6
type = cycle
z7 = 0, 1
[Present]
post x = 0
[ShaderOverrideSMSMOutputArm]
hash = 72a656dfd52149ad
x = 1
[ShaderOverrideSMSMOutputConsume]
hash = 23d27700572e0c4d
post x = 0
'''


def fnv(data):
    value = 0
    for byte in data:
        value = ((value * 0x100000001b3) & 0xffffffffffffffff) ^ byte
    return f'{value:016x}'


def build(baseline, output, r10=ROOT/R10, extraction=EXTRACTION, diagnostic=False):
    original, receipt = read_package(baseline)
    if digest(receipt) != A_DEFAULT:
        raise ValueError('Expected the deployed tone A default package')
    r10_manifest, _ = read_package(r10)
    extracted = {s['Hash']: s for s in __import__('json').loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders']
                 if s['Profile'] == 'ps_5_0'}
    files = {n: (baseline/n).read_bytes() for n in original['files']}
    ini = files['d3dx.ini'].decode().replace('\r\n', '\n')
    if ini.count(INI_REPLACE[0]) != 1 or re.search(r'^\[(Present|KeySMSMDither)\]', ini, re.M) or 'x = 0' in ini:
        raise ValueError('Unexpected A default INI')
    files['d3dx.ini'] = ini.replace(*INI_REPLACE).encode() + INI_APPEND
    for hash_value, edits in EDITS.items():
        source = (r10/FIXES/f'{hash_value}-ps_replace.txt').read_text(encoding='utf-8').replace('\r\n', '\n')
        for old, new in edits:
            if source.count(old) != 1:
                raise ValueError(f'{hash_value}: edit anchor changed')
            source = source.replace(old, new)
        if diagnostic and hash_value == OUTPUT:
            for old, new in (DIAGNOSTIC_INDICATOR, DIAGNOSTIC_COLOUR):
                if source.count(old) != 1:
                    raise ValueError('Diagnostic anchor changed')
                source = source.replace(old, new)
        files[f'{FIXES}/{hash_value}-ps_replace.txt'] = source.encode()
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    compiler = Compiler(baseline/'d3dcompiler_46.dll')
    rows = []
    for hash_value, effect in EFFECTS.items():
        record = extracted[hash_value]
        game = (extraction/record['File']).read_bytes()
        if hashlib.sha256(game).hexdigest() != record['Sha256'] or fnv(game) != hash_value:
            raise ValueError(f'{hash_value}: extracted original does not match')
        name = f'{FIXES}/{hash_value}-ps_replace'
        binary, diagnostics = compiler.compile(output/(name+'.txt'))
        # Same resources as the game shader, plus only the 3DMigoto parameter texture.
        expected = dict(bindings(compiler.disassemble(game)))
        expected[('texture', 120)] = ('float4', '1d', 1)
        if bindings(compiler.disassemble(binary)) != expected:
            raise ValueError(f'{hash_value}: resource interface changed')
        files[name+'.bin'] = binary
        (output/(name+'.bin')).write_bytes(binary)
        previous = next(s for s in r10_manifest['shaders'] if s['hash'] == hash_value)
        rows.append({'hash': hash_value, 'effect': effect, 'original_sha256': record['Sha256'],
                     'compiled_sha256': digest(binary), 'compiler_diagnostics': diagnostics,
                     'r10_compiled_sha256': previous['compiled_sha256']})
    manifest = copy.deepcopy(original)
    manifest['files'] = {n: digest(v) for n, v in files.items()}
    manifest['shaders'] = manifest['shaders'] + rows
    manifest['effects']['dithering'] = {'shaders': list(EFFECTS), 'status': 'experimental-t2-dither-toggle',
                                        'execution_verified': False, 'performance_verified': False}
    manifest['profiles']['daily'] = ['tone', 'dithering']
    manifest['compatibility_candidate']['id'] = 'r11-dither-t2'
    manifest['compatibility_candidate']['stage'] = 'T2-dithering-comparison'
    manifest['compatibility_candidate']['acceptance'] = 'user compares dithering on/off on sky gradients and dark areas'
    manifest['dither_experiment'] = {
        'id': 'dither-t2', 'baseline_manifest_sha256': A_DEFAULT,
        'comparison': {'key': 'Ctrl+F6', 'states': ['off', 'on'], 'startup': 'on', 'resource': 'IniParams t120[7].z',
                       'indicator': 'white D beside the tone label while on (Ctrl+F7)'},
        'stage_marker': 'IniParams t120[0].x armed by 72a656dfd52149ad, consumed by 23d27700572e0c4d, reset at Present',
        'excluded': {'12dd4d7295446a19': 'not executed in the 2026.09.15 capture'},
        'game_verified': False, 'visual_improvement_verified': False}
    if diagnostic:
        manifest['compatibility_candidate']['id'] = 'r11-dither-t2-diagnostic'
        manifest['dither_experiment']['diagnostic_indicator'] = (
            'D drawn on every output copy while labels are shown: white armed+on, yellow armed+off, red unarmed')
    (output/RECEIPT).write_bytes(encoded(manifest))
    read_package(output)
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--diagnostic', action='store_true', help='colour-coded D on every copy (white/yellow/red)')
    a = p.parse_args()
    build(a.baseline, a.output, diagnostic=a.diagnostic)
    print(f'Prepared {a.output}; tone A + dithering on, Ctrl+F6 toggles dithering')
