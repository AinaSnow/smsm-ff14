"""Build an opt-in constant-magenta SSR execution probe from a verified managed package.

No game files are written. The probe appends one output write to the ORIGINAL
client shader, not the jitter experiment. It intentionally overrides RGB/alpha
and hit/fade information, so visible colour proves contribution, not SSR quality.
Absence of colour does not prove that the shader never executed.
"""
import argparse
import json
from pathlib import Path
import re
import shutil

from build_preview import BUILD, verify_interface
from manage_preview import ROOT, RECEIPT, FIXES, digest, encoded, read_package
from patch_shader_asm import assemble, disassemble_exact, instructions
from shader_compile import Compiler
from validate_d3d11 import validate_package

TARGET = "4caad0714bdcc47e"
MARKER = "mov o0.xyzw, l(1.000000, 0.000000, 1.000000, 1.000000)"


def append_marker(base):
    # Only this reviewed straight-line exit is supported. All original control
    # flow, resources, instructions and declarations remain ahead of the marker.
    if len(re.findall(r"^ret\s*$", base, re.M)) != 1 or re.search(r"^\s*(?:retc\S*|discard\S*)\b", base, re.M):
        raise ValueError("Probe requires exactly one unconditional exit and no discard")
    anchor = "mov o0.w, r0.w\nret"
    if base.count(anchor) != 1:
        raise ValueError("Unreviewed reflection exit")
    return base.replace(anchor, "mov o0.w, r0.w\n// DIAGNOSTIC ONLY: forced magenta, including alpha\n" + MARKER + "\nret")


def check_instruction_delta(original, probe):
    old, new = instructions(original), instructions(probe)
    # First two DWORDs are shader model and length. The reviewed shader's final
    # instruction is the one-DWORD ret. Only a mov is allowed before that ret.
    if (old[:4] != new[:4] or old[-4:] != new[-4:] or
            new[8:len(old) - 4] != old[8:-4]):
        raise ValueError("Probe changed original instructions")
    inserted = new[len(old) - 4:-4]
    if len(inserted) != 32 or int.from_bytes(inserted[:4], "little") & 0x7ff != 54:
        raise ValueError("Expected one eight-DWORD output mov")


def build_probe(extraction, base_package, output, decompiler):
    manifest, receipt = read_package(base_package)
    if (manifest.get("schema_version") != 2 or manifest["client_build"] != BUILD or
            manifest["effects"].get("reflection", {}).get("shaders") != [TARGET] or manifest.get("diagnostic")):
        raise ValueError("Expected a reviewed managed reflection baseline")
    extracted = json.loads((extraction / "manifest.json").read_text())
    if extracted["ClientBuild"] != BUILD:
        raise ValueError("Unreviewed client build")
    record = next(s for s in extracted["Shaders"] if s["Hash"] == TARGET and s["Profile"] == "ps_5_0")
    source_path = (extraction / record["File"]).resolve(strict=True)
    if not source_path.is_relative_to(extraction.resolve()):
        raise ValueError("Extraction path escapes root")
    original = source_path.read_bytes()
    original_sha = next(s for s in manifest["shaders"] if s["hash"] == TARGET)["original_sha256"]
    fnv = 0
    for value in original:
        fnv = ((fnv * 0x100000001b3) & 0xffffffffffffffff) ^ value
    if digest(original) != original_sha or original_sha != record["Sha256"] or f"{fnv:016x}" != TARGET:
        raise ValueError("Original bytecode integrity mismatch")
    if output.exists():
        raise FileExistsError("Use a fresh immutable output directory")
    work = output / "build-audit" / TARGET
    work.mkdir(parents=True)
    binary = work / "original.bin"
    binary.write_bytes(original)
    base = disassemble_exact(decompiler, binary)
    if instructions(assemble(decompiler, binary.with_suffix(".asm"), binary)) != instructions(original):
        raise ValueError("Original instruction roundtrip mismatch")
    source = work / f"{TARGET}-ps.txt"
    source.write_text(append_marker(base))
    data = assemble(decompiler, source, binary)
    check_instruction_delta(original, data)
    compiler = Compiler(ROOT / "d3dcompiler_46.dll")
    verify_interface(compiler.disassemble(original), compiler.disassemble(data))
    (work / "probe-disassembly.txt").write_text(compiler.disassemble(data))

    # Copy only inventoried assets; never mutate the source package or receipt.
    for name in manifest["files"]:
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_package / name, destination)
    names = [n for n in manifest["files"] if n.startswith(f"{FIXES}/{TARGET}-ps")]
    for name in names:
        (output / name).write_bytes(data if name.endswith(".bin") else source.read_bytes())
        manifest["files"][name] = digest((output / name).read_bytes())
    for row in manifest["shaders"]:
        if row["hash"] == TARGET:
            row.update(effect="DIAGNOSTIC: constant magenta SSR output, not a visual improvement",
                       compiled_sha256=digest(data), compiler_diagnostics="Exact original instructions plus one output mov; interface verified")
    manifest["effects"]["reflection"].update(status="diagnostic-only", execution_verified=False, performance_verified=False)
    manifest["profiles"] = {"daily": ["tone"], "vanilla": [], "reflection-probe": ["reflection"]}
    manifest["default_profile"] = "daily"
    manifest["diagnostic"] = {"kind": "reflection-execution-marker", "target": TARGET,
                              "base_package_sha256": digest(receipt), "output_rgba": [1, 0, 1, 1],
                              "forces_alpha_and_bypasses_hit_fades": True,
                              "positive_means": "Target replacement output contributes to the visible frame in this scene",
                              "negative_means": "Inconclusive: reload, pass selection, settings or downstream masking may prevent visibility",
                              "quality_test": False}
    (output / RECEIPT).write_bytes(encoded(manifest))
    read_package(output)
    validate_package(output)
    report = {"original_instruction_roundtrip": True, "only_one_output_mov_added": True,
              "interface_verified": True, "warp_creation_verified": True,
              "changed_assets": names, "base_package_sha256": digest(receipt),
              "probe_package_sha256": digest((output / RECEIPT).read_bytes()),
              "game_execution_verified": False, "offline_draw_verified": False}
    (output / "build-audit/validation.json").write_bytes(encoded(report))
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extraction", type=Path)
    parser.add_argument("base_package", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--decompiler", type=Path, required=True)
    args = parser.parse_args()
    build_probe(args.extraction, args.base_package, args.output, args.decompiler.resolve(strict=True))
