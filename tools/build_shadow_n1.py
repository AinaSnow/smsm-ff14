"""Build the N0+N1 normal shadow package: D1-strong base plus switchable normal shadows in both sun-light shaders.

Uses the r10 ASM insertion (patch_shader_asm): original instructions must roundtrip exactly; the helper
result is min()'d into the host's shadow mask. The helper additionally reads IniParams t120, which the
host does not declare, so a t120 declaration is added; every other helper resource and constant read must
already exist in the host.
"""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package
from shader_compile import Compiler
from build_preview import bindings
from build_dither_t2 import FIXES, TONE, edit_once, fnv
from patch_shader_asm import assemble, disassemble_exact, inject_once, instructions, temp_count

D1_STRONG = 'a659dab8c1e37c870262f6db7ba58642d2bd244b35211cd89ed0d4c57fff749f'
EXTRACTION = ROOT/'artifacts/client-2026.10.06'
DECOMPILER = ROOT.parent/'smsm-ff14/artifacts/decompiler/1.3.16/cmd_Decompiler.exe'
HOSTS = {'8b384acd7a03c836': 'directional normal shadows (N1 switch)',
         'e9f57e0834b642f5': 'directional normal shadows with fake specular (N1 switch)'}
ANCHOR = 'sample_indexable(texture2d)(float,float,float,float) r0.x, r0.xyxx, t8.xyzw, s7'
T120 = ('texture', 120)

TONE_EDIT = ('  }\n}\n\nvoid orig_dec',
             '  }\n'
             '  float n1Level = IniParams.Load(int2(5, 0)).x;\n'
             '  if (smsmControls.y > 0.5 && all(smsmPixel >= uint2(90, 24)) && all(smsmPixel < uint2(102, 46)))\n'
             '    o0.rgb = float3(0.025, 0.025, 0.025);\n'
             '  if (smsmControls.y > 0.5 && n1Level > 0.5 &&\n'
             '      all(smsmPixel >= uint2(88, 28)) && all(smsmPixel < uint2(98, 42)))\n'
             '  {\n'
             '    static const uint rowsN[7] = {17, 25, 21, 19, 17, 17, 17};\n'
             '    uint2 cellN = (smsmPixel - uint2(88, 28)) / 2;\n'
             '    if ((rowsN[cellN.y] >> (4u - cellN.x)) & 1u) o0.rgb = float3(0.55, 0.85, 1.0);\n'
             '  }\n'
             '}\n\nvoid orig_dec')
INI_ANCHOR = 'y6 = 2\nz6 = 0\n'
INI_APPEND = b'''
; N0/N1 normal shadows in the sun-light shaders. x5 = 1 on (Ctrl+F1); y5 = 1 removes direct sun to prove
; the shaders run (Ctrl+F11).
[KeySMSMNormalShadow]
key = ctrl no_shift no_alt VK_F1
type = cycle
x5 = 0, 1
[KeySMSMNormalShadowDiagnostic]
key = ctrl no_shift no_alt VK_F11
type = cycle
y5 = 1, 0
'''


def patch_host(hash_value, original, work, compiler, helper, helper_asm):
    work.mkdir(parents=True)
    binary = work/'original.bin'; binary.write_bytes(original)
    base = disassemble_exact(DECOMPILER, binary)
    if instructions(assemble(DECOMPILER, binary.with_suffix('.asm'), binary)) != instructions(original):
        raise ValueError(f'Instruction roundtrip changed original: {hash_value}')
    host = bindings(compiler.disassemble(original))
    for slot, value in bindings(compiler.disassemble(helper)).items():
        if slot != T120 and host.get(slot) != value:
            raise ValueError(f'Helper binding exceeds host: {slot}')
    if T120 in host:
        raise ValueError('Host already uses t120')
    sizes = lambda s: {int(a): int(b) for a, b in re.findall(r'dcl_constantbuffer cb(\d+)\[(\d+)\]', s, re.I)}
    if any(size > sizes(base).get(slot, 0) for slot, size in sizes(helper_asm).items()):
        raise ValueError('Helper constant reads exceed host')
    lines = helper_asm.splitlines()
    t120 = [line for line in lines if line.startswith('dcl_resource') and line.rstrip().endswith('t120')]
    if len(t120) != 1:
        raise ValueError('Helper must declare t120 once')
    start = max(i for i, line in enumerate(lines) if line.startswith('dcl_')) + 1
    body = '\n'.join(line for line in lines[start:] if line.strip() and not line.startswith('//'))
    count = temp_count(base)
    helper_count = temp_count(helper_asm)
    result = f'r{count + helper_count}'
    body = re.sub(r'\br(\d+)\b', lambda m: f'r{int(m[1]) + count}', body)
    body = re.sub(r'\bo0\b', result, body)
    # The helper now has early returns: turn each ret into a jump to the end of the block.
    if not body.endswith('ret'):
        raise ValueError('Helper must end with ret')
    body = body.removesuffix('ret').rstrip()
    if 'ret' in re.findall(r'^\s*(\w+)', body, re.M):
        body = 'loop\n' + re.sub(r'^(\s*)ret\s*$', r'\1break', body, flags=re.M) + '\nbreak\nendloop'
    addition = f'// SMSM N1 normal shadow begin\n{body}\nmin r0.x, r0.x, {result}.x\n// SMSM N1 normal shadow end'
    patched = inject_once(base, ANCHOR, addition, after=True)
    patched = inject_once(patched, f'dcl_temps {count}', t120[0])
    patched = re.sub(r'^dcl_temps \d+$', f'dcl_temps {count + helper_count + 1}', patched, count=1, flags=re.M)
    source = work/f'{hash_value}-ps.txt'
    source.write_text(patched)
    data = assemble(DECOMPILER, source, binary)
    check = work/'patched.bin'; check.write_bytes(data)
    disassemble_exact(DECOMPILER, check)
    return source, data


def build(baseline, output, extraction=EXTRACTION):
    original_manifest, receipt = read_package(baseline)
    if digest(receipt) != D1_STRONG:
        raise ValueError('Expected the D1 strong package')
    files = {n: (baseline/n).read_bytes() for n in original_manifest['files']}
    ini = files['d3dx.ini'].decode().replace('\r\n', '\n')
    if 'KeySMSMNormalShadow' in ini or 'x5' in ini or 'y5' in ini:
        raise ValueError('Unexpected base INI')
    files['d3dx.ini'] = edit_once(ini, INI_ANCHOR, INI_ANCHOR + 'x5 = 1\ny5 = 0\n', 'INI').encode() + INI_APPEND
    tone_name = f'{FIXES}/{TONE}-ps_replace'
    source = files[tone_name+'.txt'].decode().replace('\r\n', '\n')
    files[tone_name+'.txt'] = edit_once(source, *TONE_EDIT, 'tone indicator').encode()

    output.mkdir(parents=True, exist_ok=False)
    audit = output/'build-audit'
    compiler = Compiler((baseline/'d3dcompiler_46.dll').resolve())
    helper, diagnostics = compiler.compile(ROOT/'tools/patches/normal_shadow_n1.hlsl')
    if diagnostics:
        raise ValueError('Helper must compile without warnings: ' + diagnostics)
    audit.mkdir(parents=True)
    (audit/'helper.bin').write_bytes(helper)
    helper_asm = disassemble_exact(DECOMPILER, audit/'helper.bin')
    records = {s['Hash']: s for s in json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders']
               if s['Profile'] == 'ps_5_0'}
    rows = []
    for hash_value, effect in HOSTS.items():
        record = records[hash_value]
        game = (extraction/record['File']).read_bytes()
        if hashlib.sha256(game).hexdigest() != record['Sha256'] or fnv(game) != hash_value:
            raise ValueError(f'{hash_value}: extracted original does not match')
        asm, data = patch_host(hash_value, game, audit/hash_value, compiler, helper, helper_asm)
        files[f'{FIXES}/{hash_value}-ps.txt'] = asm.read_bytes()
        files[f'{FIXES}/{hash_value}-ps.bin'] = data
        rows.append({'hash': hash_value, 'effect': effect, 'original_sha256': record['Sha256'],
                     'compiled_sha256': digest(data), 'compiler_diagnostics': 'Original instruction stream roundtrip verified; bounded ASM insertion with t120'})
    tone_src = output/tone_name
    for name, data in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    binary, tone_diag = compiler.compile(output/(tone_name+'.txt'))
    files[tone_name+'.bin'] = binary
    (output/(tone_name+'.bin')).write_bytes(binary)

    manifest = copy.deepcopy(original_manifest)
    manifest['files'] = {n: digest(v) for n, v in files.items()}
    manifest['shaders'][0].update(compiled_sha256=digest(binary), compiler_diagnostics=tone_diag)
    manifest['shaders'] += rows
    manifest['effects']['shadows'] = {'shaders': list(HOSTS), 'status': 'experimental-n1-normal-shadow-toggle',
                                      'execution_verified': False, 'performance_verified': False}
    manifest['profiles']['daily'] = ['tone', 'dithering', 'radial', 'dof', 'shadows']
    manifest['compatibility_candidate']['id'] = 'r11-shadow-n1-2026.10.06'
    manifest['compatibility_candidate']['stage'] = 'N0-N1-normal-shadows'
    manifest['compatibility_candidate']['acceptance'] = 'N0 removes sunlight to prove execution; user compares N1 on/off'
    manifest['dof_experiment']['status'] = 'accepted-default-strong'
    manifest['shadow_experiment'] = {
        'id': 'shadow-n1', 'baseline_manifest_sha256': D1_STRONG,
        'comparison': {'key': 'Ctrl+F1', 'states': ['off', 'on'], 'startup': 'on', 'resource': 'IniParams t120[5].x',
                       'indicator': 'light blue N after B (Ctrl+F7)'},
        'diagnostic': {'key': 'Ctrl+F11', 'resource': 'IniParams t120[5].y', 'startup': 'off',
                       'effect': 'shadow mask forced to 0: direct sunlight disappears where these shaders run'},
        'label_box': [24, 24, 102, 46], 'indicator_box': [88, 28, 98, 42],
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
    print(f'Prepared {a.output}; normal shadows on, Ctrl+F1 toggles, Ctrl+F11 sunlight-removal diagnostic')
