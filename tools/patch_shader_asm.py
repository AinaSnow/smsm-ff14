"""Insert bounded effects without recompiling the game's complex lighting logic.

Requires the official cmd_Decompiler 1.3.16. Original shaders and generated ASM
stay in artifacts. Each base shader must survive a bit-exact instruction roundtrip.
"""
from pathlib import Path
import re
import struct
import subprocess

PATCHES = {
    "4caad0714bdcc47e": "hierarchical screen-space reflection sampling",
    "8b384acd7a03c836": "directional normal shadows",
    "e9f57e0834b642f5": "directional normal shadows with fake specular",
}


def run(tool, *args):
    result = subprocess.run([str(tool), *map(str, args)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def instructions(data):
    count = struct.unpack_from("<I", data, 28)[0]
    for i in range(count):
        offset = struct.unpack_from("<I", data, 32 + i * 4)[0]
        if data[offset:offset + 4] in (b"SHDR", b"SHEX"):
            length = struct.unpack_from("<I", data, offset + 4)[0]
            return data[offset + 8:offset + 8 + length]
    raise ValueError("No shader instructions")


def disassemble_exact(tool, binary):
    run(tool, "-d", "-V", binary)
    return binary.with_suffix(".asm").read_text()


def assemble(tool, asm, original):
    run(tool, "-a", "--copy-reflection", original, asm)
    return asm.with_suffix(".shdr").read_bytes()


def temp_count(asm):
    return int(re.search(r"^dcl_temps (\d+)$", asm, re.M)[1])


def inject_once(asm, anchor, addition, after=False):
    if asm.count(anchor) != 1:
        raise ValueError(f"Patch anchor must occur exactly once: {anchor}")
    return asm.replace(anchor, anchor + "\n" + addition if after else addition + "\n" + anchor)


def build_patch(hash_value, original, output, compiler, tool, root):
    work = output / hash_value
    work.mkdir(parents=True)
    binary = work / "original.bin"
    binary.write_bytes(original)
    base = disassemble_exact(tool, binary)
    # MS disassembly rounds float literals; Flugan's validated representation
    # preserves them. Never patch an inexact baseline.
    roundtrip = assemble(tool, binary.with_suffix(".asm"), binary)
    if instructions(roundtrip) != instructions(original):
        raise ValueError(f"Instruction roundtrip changed original: {hash_value}")
    count = temp_count(base)
    patched = base
    if hash_value == "4caad0714bdcc47e":
        # Keep Hi-Z ray traversal, hit testing, material mask, distance/edge fades
        # and output alpha. Dither only the final reflection color lookup.
        a, b = f"r{count}", f"r{count + 1}"
        addition = f"""// SMSM: six-texel bounded reflection lookup jitter
dp2 {a}.x, v0.xyxx, l(0.06711056, 0.00583715, 0, 0)
add {a}.y, {a}.x, l(0.371)
frc {a}.xy, {a}.xyxx
mul {a}.xy, {a}.xyxx, l(52.9829189, 52.9829189, 0, 0)
frc {a}.xy, {a}.xyxx
mad {a}.xy, {a}.xyxx, l(2.0, 2.0, 0, 0), l(-1.0, -1.0, 0, 0)
resinfo {b}.xy, l(0), t1.xyzw
rcp {b}.xy, {b}.xyxx
mul {a}.xy, {a}.xyxx, {b}.xyxx
mad {a}.xy, {a}.xyxx, l(3.0, 3.0, 0, 0), r0.xyxx
max {a}.xy, {a}.xyxx, l(0, 0, 0, 0)
mad {b}.xy, -{b}.xyxx, l(0.5, 0.5, 0, 0), cb2[3].xyxx
min r0.xy, {a}.xyxx, {b}.xyxx
// SMSM end"""
        anchor = "sample_indexable(texture2d)(float,float,float,float) r0.xyz, r0.xyxx, t1.xyzw, s1"
        patched = inject_once(base, anchor, addition)
        patched = inject_once(patched, "dcl_temps " + str(count), "dcl_input_ps_siv linear noperspective v0.xy, position")
        new_count = count + 2
    elif hash_value in PATCHES:
        helper, diagnostics = compiler.compile(root / "tools/patches/normal_shadow.hlsl")
        if diagnostics:
            raise ValueError("Normal shadow helper must compile without warnings: " + diagnostics)
        helper_bin = work / "helper.bin"
        helper_bin.write_bytes(helper)
        helper_asm = disassemble_exact(tool, helper_bin)
        # Explicitly constrain helper resources/constant reads to the host shader.
        from build_preview import bindings
        old_bindings = bindings(compiler.disassemble(original))
        for slot, value in bindings(compiler.disassemble(helper)).items():
            if old_bindings.get(slot) != value:
                raise ValueError(f"Helper binding exceeds host: {slot}")
        sizes = lambda s: {int(a): int(b) for a, b in re.findall(r"dcl_constantbuffer cb(\d+)\[(\d+)\]", s, re.I)}
        if any(size > sizes(base).get(slot, 0) for slot, size in sizes(helper_asm).items()):
            raise ValueError("Helper constant reads exceed host")
        lines = helper_asm.splitlines()
        start = max(i for i, line in enumerate(lines) if line.startswith("dcl_")) + 1
        body = "\n".join(line for line in lines[start:] if line.strip() and not line.startswith("//"))
        if body.splitlines().count("ret") != 1 or not body.endswith("ret"):
            raise ValueError("Helper must have only a final return")
        body = body.removesuffix("ret").rstrip()
        helper_count = temp_count(helper_asm)
        result_register = f"r{count + helper_count}"
        body = re.sub(r"\br(\d+)\b", lambda m: f"r{int(m[1]) + count}", body)
        body = re.sub(r"\bo0\b", result_register, body)
        addition = f"// SMSM normal shadow begin\n{body}\nmin r0.x, r0.x, {result_register}.x\n// SMSM normal shadow end"
        anchor = "sample_indexable(texture2d)(float,float,float,float) r0.x, r0.xyxx, t8.xyzw, s7"
        patched = inject_once(base, anchor, addition, after=True)
        new_count = count + helper_count + 1
    else:
        raise ValueError("Unreviewed shader")
    patched = re.sub(r"^dcl_temps \d+$", f"dcl_temps {new_count}", patched, count=1, flags=re.M)
    source = work / f"{hash_value}-ps.txt"
    source.write_text(patched)
    data = assemble(tool, source, binary)
    # A second roundtrip checks the inserted code's encoding too.
    check = work / "patched.bin"
    check.write_bytes(data)
    disassemble_exact(tool, check)
    return source, data
