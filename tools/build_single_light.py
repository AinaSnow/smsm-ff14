"""Build a default-off single-light package with baked, file-controlled parameters.

Offline animation uses the same helper with b13. Game packages use constants
only: no new runtime binding, DLL/INI changes or unverified hot parameter keys.
"""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
from build_preview import BUILD, verify_interface, bindings
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package
from patch_shader_asm import assemble, disassemble_exact, instructions, temp_count
from shader_compile import Compiler
from validate_d3d11 import validate_package

TARGETS = {"8b384acd7a03c836": "r3", "e9f57e0834b642f5": "r10"}


def validate_settings(position, color, intensity, radius):
    if len(position) != 3 or len(color) != 3 or not all(math.isfinite(v) for v in [*position, *color, intensity, radius]):
        raise ValueError("Light parameters must be finite xyz/RGB/scalars")
    if any(abs(v) > 10000 for v in position) or any(v < 0 or v > 8 for v in color) or not 0 <= intensity <= 100 or not .01 <= radius <= 1000:
        raise ValueError("Position +/-10000, RGB 0..8, intensity 0..100, range .01..1000 required")


def compile_helper(work, compiler, position, color, intensity, radius):
    validate_settings(position, color, intensity, radius)
    work.mkdir(parents=True, exist_ok=True)
    fmt = lambda values: ", ".join(format(float(v), ".9g") for v in values)
    (work / "single_light_parameters.h").write_text(
        "static const float4 lampPositionRange = float4(" + fmt([*position, radius]) + ");\n" +
        "static const float4 lampColorIntensity = float4(" + fmt([*color, intensity]) + ");\n")
    source = work / "single_light.hlsl"
    source.write_text("#define SINGLE_LIGHT_BAKED 1\n" + (ROOT / "tools/patches/single_light.hlsl").read_text())
    binary, diagnostics = compiler.compile(source)
    if diagnostics:
        raise ValueError(diagnostics)
    (work / "helper.bin").write_bytes(binary)
    return binary


def patch_light(original, helper, work, target, decompiler, compiler):
    work.mkdir(parents=True, exist_ok=True)
    binary = work / "original.bin"; binary.write_bytes(original)
    base = disassemble_exact(decompiler, binary)
    if instructions(assemble(decompiler, binary.with_suffix(".asm"), binary)) != instructions(original):
        raise ValueError("Original instruction roundtrip changed")
    helper_path = work / "helper.bin"; helper_path.write_bytes(helper)
    helper_asm = disassemble_exact(decompiler, helper_path)
    compiled_text = compiler.disassemble(helper)
    helper_ops = [line.strip() for line in compiled_text.splitlines()
                  if line.strip() and not line.startswith("//") and not line.startswith("dcl_") and line.strip() != "ps_5_0"]
    if helper_ops == ["mov o0.xyzw, l(0,0,0,0)", "ret"]:
        # A zero lamp is an exact identity, including code generation: do not
        # invent resource declarations or assume an optimized-away temp exists.
        source = work / f"{target}-ps.txt"; source.write_text(base)
        return source, original
    old_bindings = bindings(compiler.disassemble(original))
    if any(old_bindings.get(k) != v for k, v in bindings(compiled_text).items()):
        raise ValueError("Helper adds an unbound resource")
    sizes = lambda s: {int(a): int(b) for a, b in re.findall(r"dcl_constantbuffer cb(\d+)\[(\d+)\]", s)}
    if any(n > sizes(base).get(k, 0) for k, n in sizes(helper_asm).items()):
        raise ValueError("Helper constant range exceeds host")
    lines = helper_asm.splitlines()
    start = max(i for i, s in enumerate(lines) if s.startswith("dcl_")) + 1
    body = "\n".join(s for s in lines[start:] if s.strip() and not s.startswith("//"))
    if body.splitlines().count("ret") != 1 or not body.endswith("ret") or re.search(r"\b(retc\w*|discard\w*)\b", body):
        raise ValueError("Helper must have one final return")
    count, helper_count = temp_count(base), temp_count(helper_asm)
    result = f"r{count + helper_count}"
    body = re.sub(r"\br(\d+)\b", lambda m: f"r{int(m[1]) + count}", body.removesuffix("ret").rstrip())
    body = re.sub(r"\bo0\b", result, body)
    destination = TARGETS[target]
    anchor = f"mov o0.xyzw, {destination}.xyzw"
    if base.count(anchor) != 1 or len(re.findall(r"^ret$", base, re.M)) != 1:
        raise ValueError("Unreviewed light output stage")
    addition = "// SINGLE LIGHT EXPERIMENT BEGIN\n" + body + f"\nadd {destination}.xyz, {destination}.xyzx, {result}.xyzx\n// SINGLE LIGHT EXPERIMENT END\n"
    patched = base.replace(anchor, addition + anchor)
    patched = re.sub(r"^dcl_temps \d+$", f"dcl_temps {count + helper_count + 1}", patched, count=1, flags=re.M)
    # Mechanically prove no original source instruction changed outside the
    # insertion and temp declaration, in addition to assembled interface checks.
    recovered = patched.replace(addition, "")
    recovered = re.sub(r"^dcl_temps \d+$", f"dcl_temps {count}", recovered, count=1, flags=re.M)
    if recovered != base:
        raise ValueError("Unexpected mutation outside injection")
    source = work / f"{target}-ps.txt"; source.write_text(patched)
    data = assemble(decompiler, source, binary)
    verify_interface(compiler.disassemble(original), compiler.disassemble(data))
    (work / "patched-disassembly.txt").write_text(compiler.disassemble(data))
    return source, data


def build(extraction, base_package, output, decompiler, position, color, intensity, radius):
    validate_settings(position, color, intensity, radius)
    manifest, receipt = read_package(base_package)
    if manifest.get("schema_version") != 2 or manifest["client_build"] != BUILD or manifest.get("diagnostic") or manifest.get("single_light"):
        raise ValueError("Expected the original managed baseline")
    if set(manifest["effects"].get("shadows", {}).get("shaders", [])) != set(TARGETS):
        raise ValueError("Light targets must occupy the baseline shadow group; overlapping fixes prohibited")
    extracted = json.loads((extraction / "manifest.json").read_text())
    if extracted["ClientBuild"] != BUILD:
        raise ValueError("Unreviewed build")
    if output.exists():
        raise FileExistsError("Use a fresh immutable output directory")
    compiler = Compiler(ROOT / "d3dcompiler_46.dll")
    helper = compile_helper(output / "build-audit/helper", compiler, position, color, intensity, radius)
    for name in manifest["files"]:
        path = output / name; path.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(base_package / name, path)
    for target in TARGETS:
        record = next(s for s in extracted["Shaders"] if s["Hash"] == target and s["Profile"] == "ps_5_0")
        path = (extraction / record["File"]).resolve(strict=True)
        if not path.is_relative_to(extraction.resolve()):
            raise ValueError("Extraction path escapes root")
        original = path.read_bytes()
        row = next(r for r in manifest["shaders"] if r["hash"] == target)
        fnv = 0
        for value in original: fnv = ((fnv * 0x100000001b3) & 0xffffffffffffffff) ^ value
        if f"{fnv:016x}" != target or digest(original) != record["Sha256"] or record["Sha256"] != row["original_sha256"]:
            raise ValueError("Original integrity mismatch")
        source, data = patch_light(original, helper, output / "build-audit" / target, target, decompiler, compiler)
        for name in manifest["files"]:
            if name.startswith(f"SMSM-ShaderFixes/{target}-ps"):
                (output / name).write_bytes(data if name.endswith(".bin") else source.read_bytes())
                manifest["files"][name] = digest((output / name).read_bytes())
        row.update(effect="experimental additive single-light diffuse irradiance", compiled_sha256=digest(data),
                   compiler_diagnostics="Original roundtrip and bounded insertion; no extra bindings; MRT interface preserved")
    del manifest["effects"]["shadows"]
    manifest["effects"]["single-light"] = {"shaders": list(TARGETS), "status": "experimental-offline-prototype",
                                            "execution_verified": False, "performance_verified": False}
    manifest["profiles"] = {"daily": ["tone"], "vanilla": [], "single-light-only": ["single-light"]}
    manifest["default_profile"] = "daily"
    manifest["single_light"] = {"position_view": position, "color_linear": color, "intensity": intensity, "range": radius,
        "control": "baked immutable shader parameters; select package then F10; no per-frame in-game controller yet",
        "base_package_sha256": digest(receipt), "occlusion": False, "material_adaptation": False,
        "world_locked": False, "injection_count_game_verified": False, "game_runtime_verified": False}
    (output / RECEIPT).write_bytes(encoded(manifest)); read_package(output); validate_package(output)
    print(f"Built default-off single-light candidate: {output}")
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("extraction", type=Path); p.add_argument("base_package", type=Path); p.add_argument("output", type=Path)
    p.add_argument("--decompiler", required=True, type=Path)
    p.add_argument("--position", type=float, nargs=3, default=[0, 0, 0]); p.add_argument("--color", type=float, nargs=3, default=[1, 1, 1])
    p.add_argument("--intensity", type=float, default=1); p.add_argument("--range", dest="radius", type=float, default=8)
    a = p.parse_args()
    build(a.extraction, a.base_package, a.output, a.decompiler.resolve(), a.position, a.color, a.intensity, a.radius)
