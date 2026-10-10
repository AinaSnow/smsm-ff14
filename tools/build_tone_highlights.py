"""Prepare an uninstalled SDR highlight experiment from the fixed c2 baseline."""
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


def build(baseline, output):
    original, receipt = read_package(baseline)
    if digest(receipt) != BASELINE:
        raise ValueError('Expected unchanged c2 baseline')
    files = {n: (baseline/n).read_bytes() for n in original['files']}
    source = files[SOURCE].decode().replace('\r\n', '\n')
    marker = '  #endif\n}\n\nvoid orig_dec'
    if source.count(marker) != 1:
        raise ValueError('Tone output boundary changed')
    patch = (ROOT/'tools/patches/tone_highlights.hlsl').read_text(encoding='utf-8')
    source = source.replace(marker, '  #endif\n'+patch+'}\n\nvoid orig_dec')
    files[SOURCE] = source.encode()
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    compiler = Compiler(baseline/'d3dcompiler_46.dll')
    binary, diagnostics = compiler.compile(output/SOURCE)
    old_bindings = bindings(compiler.disassemble(files[BINARY]))
    new_bindings = bindings(compiler.disassemble(binary))
    if old_bindings != new_bindings:
        raise ValueError('Shader resource interface changed')
    files[BINARY] = binary
    (output/BINARY).write_bytes(binary)
    manifest = copy.deepcopy(original)
    manifest['files'] = {n: digest(v) for n, v in files.items()}
    manifest['shaders'][0]['compiled_sha256'] = digest(binary)
    manifest['shaders'][0]['compiler_diagnostics'] = diagnostics
    manifest['effects']['tone']['status'] = 'experimental-highlight-shoulder-not-game-validated'
    manifest['compatibility_candidate']['id'] = 'r11-tone-highlights-h1'
    manifest['compatibility_candidate']['stage'] = 'R3-offline-preparation'
    manifest['compatibility_candidate']['acceptance'] = 'pending scene comparison; not installed'
    manifest['tone_experiment'] = {'id': 'highlights-h1', 'baseline_manifest_sha256': BASELINE,
        'knee': 0.85, 'problem_hypothesis': 'SDR downstream clipping may flatten bright gradients',
        'risk': 'may dim whites, bright skin, emissive materials and bloom contribution',
        'visual_improvement_verified': False, 'game_verified': False}
    # Keep vanilla default; the existing installed c2 package is never altered.
    (output/RECEIPT).write_bytes(encoded(manifest))
    read_package(output)
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    build(a.baseline, a.output)
    print(f'Prepared {a.output}; default OFF, not installed, scene acceptance pending')
