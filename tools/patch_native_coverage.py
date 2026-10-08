"""Exact hair-variant coverage marker; retain original discard/depth/alpha logic."""
import re
from manage_preview import digest
from patch_material_light import load_original
from patch_shader_asm import assemble, disassemble_exact, instructions
from patch_native_ambient import TARGET, strip_reflection


def build(extraction, output, decompiler):
    output.mkdir(parents=True, exist_ok=False)
    original = load_original(extraction, TARGET)
    path = output / 'original.bin'; path.write_bytes(original)
    base = disassemble_exact(decompiler, path)
    # Replace only the sole final RGB write. Alpha, clip/discard, early depth,
    # input/output signatures, other outputs and all resource bindings survive.
    anchor = 'mul o0.xyz, r0.xyzx, cb1[3].xxxx'
    if base.count(anchor) != 1 or len(re.findall(r'^ret\s*$', base, re.M)) != 1:
        raise ValueError('Unexpected target shader exits/output')
    marker = 'mov o0.xyz, l(1.000000, 0.000000, 1.000000, 0.000000)'
    modified = base.replace(anchor, marker)
    if modified.replace(marker, anchor) != base:
        raise ValueError('Instructions outside RGB marker changed')
    source = output / 'coverage.asm'; source.write_text(modified)
    code = strip_reflection(assemble(decompiler, source, path))
    target = output / 'coverage.bin'; target.write_bytes(code)
    disassemble_exact(decompiler, target)
    if instructions(assemble(decompiler, target.with_suffix('.asm'), target)) != instructions(code):
        raise ValueError('Coverage DXBC roundtrip mismatch')
    return target, {'target': TARGET, 'resource_path': 'shader/sm5/shpk/hair.shpk',
                    'candidate_sha256': digest(code), 'original_sha256': digest(original),
                    'scope': 'magenta RGB marker only; native alpha/discard and draw states retained',
                    'game_visible_coverage_verified': False}
