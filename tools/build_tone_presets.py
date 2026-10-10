"""Build the T1 tone preset comparison package (R10 / A / B / C) from the fixed c2 baseline."""
import argparse
import copy
from pathlib import Path
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package
from shader_compile import Compiler
from build_preview import bindings

BASELINE = '850f6ea5017ad97a8f3a435af8cb8dedc989b9522562e3b3c094272959e99c27'
HASH = '72a656dfd52149ad'
SOURCE = f'SMSM-ShaderFixes/{HASH}-ps_replace.txt'
BINARY = f'SMSM-ShaderFixes/{HASH}-ps_replace.bin'
MODES = ['r10-baseline', 'a-hue-preserving', 'b-game-colour-smsm-brightness', 'c-hue-preserving-highlight-rolloff']
INI = b'''
; T1 tone presets. Independent keys work with hunting disabled. No persistence or reload.
[Constants]
x7 = 0
y7 = 1
[KeySMSMTonePreset]
key = ctrl no_shift no_alt VK_F8
type = cycle
x7 = 0, 1, 2, 3
[KeySMSMCompareLabel]
key = ctrl no_shift no_alt VK_F7
type = cycle
y7 = 1, 0
'''


def build(baseline, output):
    original, receipt = read_package(baseline)
    if digest(receipt) != BASELINE:
        raise ValueError('Expected unchanged c2 baseline')
    files = {n: (baseline/n).read_bytes() for n in original['files']}
    source = files[SOURCE].decode().replace('\r\n', '\n')
    marker = '  #endif\n}\n\nvoid orig_dec'
    if source.count(marker) != 1:
        raise ValueError('Tone output boundary changed')
    patch = (ROOT/'tools/patches/tone_presets_t1.hlsl').read_text(encoding='utf-8')
    source = source.replace(marker, '  #endif\n'+patch+'}\n\nvoid orig_dec')
    files[SOURCE] = source.encode()
    files['d3dx.ini'] += INI
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    compiler = Compiler(baseline/'d3dcompiler_46.dll')
    binary, diagnostics = compiler.compile(output/SOURCE)
    expected = dict(bindings(compiler.disassemble(files[BINARY])))
    expected[('texture', 120)] = ('float4', '1d', 1)
    if expected != bindings(compiler.disassemble(binary)):
        raise ValueError('Shader resource interface changed')
    files[BINARY] = binary
    (output/BINARY).write_bytes(binary)
    manifest = copy.deepcopy(original)
    manifest['files'] = {n: digest(v) for n, v in files.items()}
    manifest['shaders'][0]['compiled_sha256'] = digest(binary)
    manifest['shaders'][0]['compiler_diagnostics'] = diagnostics
    manifest['effects']['tone']['status'] = 'experimental-tone-presets-t1'
    manifest['compatibility_candidate']['id'] = 'r11-tone-presets-t1'
    manifest['compatibility_candidate']['stage'] = 'T1-scene-choice'
    manifest['compatibility_candidate']['acceptance'] = 'user picks one mode from scene screenshots'
    manifest['tone_experiment'] = {
        'id': 'tone-presets-t1', 'baseline_manifest_sha256': BASELINE,
        'comparison': {'key': 'Ctrl+F8', 'states': MODES, 'startup': MODES[0],
                       'label_key': 'Ctrl+F7', 'label_startup': True, 'label_bounds': [24, 24, 72, 46],
                       'resource': 'IniParams t120[7].xy'},
        'problem_hypothesis': '100% SMSM looked too white because the curve is per-channel and the game tone LUT is ignored',
        'game_verified': False}
    (output/RECEIPT).write_bytes(encoded(manifest))
    read_package(output)
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    build(a.baseline, a.output)
    print(f'Prepared {a.output}; startup mode R10, Ctrl+F8 cycles R10/A/B/C')
