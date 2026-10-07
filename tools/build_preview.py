"""Build a version-pinned preview, checking every replacement against client bytecode."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from shader_compile import Compiler

ROOT = Path(__file__).resolve().parents[1]
BUILD = "2026.09.15.0000.0000"
# Reviewed, deliberately bounded first preview. DoF and lighting need live capture.
SHADERS = {
    "72a656dfd52149ad": "tonemapping",
    "98b1bbd7925dc288": "bloom bright pass",
    "5813cf7e6d426c37": "bloom blur",
    "d0bcbd729a678569": "bloom second blur",
    "a617dec7fe8f1603": "bloom merge",
    "12dd4d7295446a19": "output dithering",
    "782e995758bf001d": "vignette dithering",
    "91f970e6bbe57d99": "dynamic-resolution radial blur",
}


def section(text, title):
    tail = text.split("// " + title + ":", 1)[1]
    return re.split(r"\n// (?:Input signature|Output signature):|\nps_", tail, maxsplit=1)[0]


def bindings(text):
    result = {}
    for line in section(text, "Resource Bindings").splitlines():
        parts = line.removeprefix("//").split()
        if len(parts) == 6 and parts[1] in ("sampler", "texture", "cbuffer", "uav"):
            name, kind, fmt, dim, slot, count = parts
            result[(kind, int(slot))] = (fmt, dim, int(count))
    return result


def signature(text, title):
    result = {}
    for line in section(text, title).splitlines():
        parts = line.removeprefix("//").split()
        if len(parts) >= 6 and parts[1].isdigit():
            name, index, mask, register, sysvalue, fmt = parts[:6]
            result[(name.lower(), int(index))] = (mask, register, sysvalue.lower(), fmt)
    return result


def verify_interface(original, replacement):
    original_bindings, new_bindings = bindings(original), bindings(replacement)
    if not original_bindings or not new_bindings:
        raise ValueError("Cannot parse resource bindings")
    for key, value in new_bindings.items():
        if original_bindings.get(key) != value:
            raise ValueError(f"Resource mismatch at {key}: {value} vs {original_bindings.get(key)}")
    old_inputs, new_inputs = signature(original, "Input signature"), signature(replacement, "Input signature")
    for key, value in new_inputs.items():
        old = old_inputs.get(key)
        if old is None or not set(value[0]).issubset(old[0]) or value[1:] != old[1:]:
            raise ValueError(f"Input signature mismatch at {key}: {value} vs {old}")
    if signature(original, "Output signature") != signature(replacement, "Output signature"):
        raise ValueError("Output signature mismatch")
    # Compiled constant-register ranges must fit the buffers available in the original.
    def sizes(text):
        return {int(a): int(b) for a, b in re.findall(r"dcl_constantbuffer cb(\d+)\[(\d+)\]", text, re.I)}
    old_sizes = sizes(original)
    for slot, size in sizes(replacement).items():
        if size > old_sizes.get(slot, 0):
            raise ValueError(f"Constant buffer b{slot} reads beyond original range")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.capture / "manifest.json").read_text())
    if manifest["ClientBuild"] != BUILD:
        raise ValueError("Unreviewed client build; extract and review before updating the whitelist")
    if args.output.exists():
        raise FileExistsError("Use a fresh package output directory")
    compiler = Compiler(ROOT / "d3dcompiler_46.dll")
    records = {s["Hash"]: s for s in manifest["Shaders"] if s["Profile"] == "ps_5_0"}
    compiled = []
    for hash_value, effect in SHADERS.items():
        record = records[hash_value]
        original = (args.capture / record["File"]).read_bytes()
        if hashlib.sha256(original).hexdigest() != record["Sha256"]:
            raise ValueError(f"Corrupted extracted shader: {hash_value}")
        fnv = 0
        for value in original:
            fnv = ((fnv * 0x100000001b3) & 0xffffffffffffffff) ^ value
        if f"{fnv:016x}" != hash_value:
            raise ValueError(f"Wrong original hash: {hash_value}")
        source = ROOT / "ShaderFixes" / f"{hash_value}-ps_replace.txt"
        data, diagnostics = compiler.compile(source)
        original_asm, patched_asm = compiler.disassemble(original), compiler.disassemble(data)
        try:
            verify_interface(original_asm, patched_asm)
        except ValueError as ex:
            raise ValueError(f"{hash_value} ({effect}): {ex}") from ex
        compiled.append((hash_value, effect, source, data, diagnostics))
    fixes = args.output / "SMSM-ShaderFixes"
    fixes.mkdir(parents=True)
    for header in (ROOT / "ShaderFixes").glob("*.h"):
        shutil.copy2(header, fixes / header.name)
    rows = []
    for hash_value, effect, source, data, diagnostics in compiled:
        shutil.copy2(source, fixes / source.name)
        (fixes / f"{hash_value}-ps_replace.bin").write_bytes(data)
        rows.append({"hash": hash_value, "effect": effect, "original_sha256": records[hash_value]["Sha256"],
                     "compiled_sha256": hashlib.sha256(data).hexdigest(), "compiler_diagnostics": diagnostics})
    for name in ("d3d11.dll", "nvapi64.dll", "d3dcompiler_46.dll", "LICENSE", "COPYING"):
        shutil.copy2(ROOT / name, args.output / name)
    config = (ROOT / "d3dx.ini").read_text()
    for old, new in {
        "hunting=0": "hunting=2", "override_directory=ShaderFixes": "override_directory=SMSM-ShaderFixes",
        "cache_directory=ShaderCache": "cache_directory=SMSM-ShaderCache",
        "storage_directory=ShaderFromGame": "storage_directory=SMSM-ShaderFromGame",
        "dump_usage=0": "dump_usage=1", "mark_snapshot=2": "mark_snapshot=1",
        ";analyse_frame = no_modifiers VK_F8": "analyse_frame = no_modifiers VK_F8",
        ";analyse_options = dump_rt jps clear_rt": "analyse_options = dump_rt jpg mono",
    }.items():
        config, count = re.subn("^" + re.escape(old) + "$", lambda match: new, config, flags=re.M)
        if count != 1:
            raise ValueError(f"Unexpected configuration template: {old}")
    (args.output / "d3dx.ini").write_text(config, encoding="utf-8")
    files = {p.relative_to(args.output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(args.output.rglob("*")) if p.is_file()}
    (args.output / "SMSM-preview.json").write_text(json.dumps({
        "client_build": BUILD, "runtime_verified": False, "shaders": rows, "files": files
    }, indent=2), encoding="utf-8")
    print(f"Built {len(rows)} shaders; original hash, compilation and interface checks passed: {args.output}")


if __name__ == "__main__":
    main()
