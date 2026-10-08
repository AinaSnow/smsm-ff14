"""OFFLINE ONLY: single-draw native composition with synthetic b12/b13 bindings.

Deliberately separate from the game patcher: no manifest or deployable package.
Original reflection is retained for native resources; harness-only CB declarations
are in the executable instruction chunk and are bound explicitly by the renderer.
"""
import re
from build_preview import bindings, signature
from patch_material_light import ANCHOR
from patch_shader_asm import assemble, disassemble_exact, instructions, temp_count


def fuse(original, helper, work, decompiler, compiler, *, mesh=False):
    work.mkdir(parents=True, exist_ok=False)
    native = work/'native.bin'; native.write_bytes(original)
    source = work/'helper.bin'; source.write_bytes(helper)
    base = disassemble_exact(decompiler, native)
    if instructions(assemble(decompiler, native.with_suffix('.asm'), native)) != instructions(original):
        raise ValueError('Native instruction roundtrip changed')
    effect = disassemble_exact(decompiler, source)
    old_bindings = bindings(compiler.disassemble(original))
    new_bindings = bindings(compiler.disassemble(helper))
    # Reflection keys are (resource-kind, register); only the two explicit
    # synthetic constant buffers may extend the real material interface.
    for slot, value in new_bindings.items():
        if slot in (('cbuffer', 12), ('cbuffer', 13)): continue
        if old_bindings.get(slot) != value: raise ValueError(f'Unexpected binding: {slot}')
    sizes = lambda text: {int(a): int(b) for a,b in re.findall(r'dcl_constantbuffer cb(\d+)\[(\d+)\]', text)}
    hs, ns = sizes(effect), sizes(base)
    extra_sizes={12:10 if mesh else 6,13:2}
    if any(hs.get(slot)!=size for slot,size in extra_sizes.items()) or 12 in ns or 13 in ns:
        raise ValueError('Unreviewed synthetic constants')
    if any(n > ns.get(k, 0) for k,n in hs.items() if k not in (12,13)):
        raise ValueError('Native constant range exceeded')
    inputs = re.findall(r'^dcl_input.*$', effect, re.M)
    if mesh:
        if inputs != ['dcl_input_ps linear v0.xyz','dcl_input_ps linear v1.xyz']:
            raise ValueError('Unreviewed mesh helper inputs')
    elif len(inputs) != 1 or inputs[0] not in base or not inputs[0].endswith('v0.xy, position'):
        raise ValueError('Unreviewed helper input')
    outputs = re.findall(r'^dcl_output.*$', effect, re.M)
    if outputs != ['dcl_output o0.xyzw']: raise ValueError('Unreviewed output')
    lines = effect.splitlines(); start = max(i for i,s in enumerate(lines) if s.startswith('dcl_')) + 1
    body = '\n'.join(s for s in lines[start:] if s.strip() and not s.startswith('//'))
    if body.splitlines().count('ret') != 1 or not body.endswith('ret') or re.search(r'\b(?:retc\w*|discard\w*)\b|\bx\d+\[', body):
        raise ValueError('Unreviewed helper control flow')
    count, helper_count = temp_count(base), temp_count(effect)
    result = f'r{count+helper_count}'
    body = re.sub(r'\br(\d+)\b', lambda m:f'r{int(m[1])+count}', body.removesuffix('ret').rstrip())
    body = re.sub(r'\bo0\b', result, body)
    anchor=ANCHOR
    add=f'add r9.yzw, r9.yyzw, {result}.xxyz'
    if mesh:
        from patch_forward_light import ANCHOR as MESH_ANCHOR
        anchor=MESH_ANCHOR
        body=re.sub(r'\bv[01]\b',lambda m:{'v0':'r1','v1':'v6'}[m[0]],body)
        add=f'add r7.xyz, r7.xyzx, {result}.xyzx'
    addition = '\n// OFFLINE VISIBILITY BEGIN\n'+body+'\n'+add+'\n// OFFLINE VISIBILITY END'
    declarations = '\n'.join(re.findall(r'^dcl_constantbuffer cb(?:12|13)\[.*$', effect, re.M))+'\n'
    if base.count(anchor) != 1: raise ValueError('Native anchor mismatch')
    modified = base.replace(anchor, anchor+addition)
    modified = modified.replace(f'dcl_temps {count}\n', declarations+f'dcl_temps {count+helper_count+1}\n', 1)
    restored = modified.replace(addition, '').replace(declarations, '').replace(
        f'dcl_temps {count+helper_count+1}\n', f'dcl_temps {count}\n', 1)
    if restored != base: raise ValueError('Native code changed outside offline injection')
    asm = work/'offline-fused.asm'; asm.write_text(modified)
    data = assemble(decompiler, asm, native)
    path = work/'offline-fused.bin'; path.write_bytes(data)
    # Signature/native reflection preserved, not a proof of runtime resources.
    original_text, fused_text = compiler.disassemble(original), compiler.disassemble(data)
    if bindings(original_text) != bindings(fused_text) or any(
            signature(original_text, title) != signature(fused_text, title)
            for title in ('Input signature', 'Output signature')):
        raise ValueError('Native signature or reflection changed')
    if sizes(fused_text) != ns | extra_sizes:
        raise ValueError('Executable constant declarations differ')
    disassemble_exact(decompiler, path)
    if instructions(assemble(decompiler, path.with_suffix('.asm'), native)) != instructions(data):
        raise ValueError('Fused instruction roundtrip changed')
    return path
