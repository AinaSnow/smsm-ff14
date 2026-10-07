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
BLOOM_SHADERS = ("98b1bbd7925dc288", "5813cf7e6d426c37", "d0bcbd729a678569", "a617dec7fe8f1603")


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


def verify_interface(original, replacement, allow_ini_params=False):
    original_bindings, new_bindings = bindings(original), bindings(replacement)
    if not original_bindings or not new_bindings:
        raise ValueError("Cannot parse resource bindings")
    for key, value in new_bindings.items():
        if allow_ini_params and key == ("texture", 120) and value == ("float4", "1d", 1):
            continue
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


def insert_section(config, name, commands):
    # Section names also occur in prose comments. Match only a real header.
    result, count = re.subn(r"^\[" + re.escape(name) + r"\]$",
                            lambda m: m[0] + "\n" + commands, config, flags=re.M)
    if count != 1:
        raise ValueError(f"Expected one INI section: {name}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--extended", action="store_true", help="Include capture-reviewed DoF, reflection, shadow and output experiments")
    parser.add_argument("--decompiler", type=Path, help="Official cmd_Decompiler 1.3.16, required for --extended")
    parser.add_argument("--look", choices=("legacy", "game-bloom", "calibrated"), default="legacy",
                        help="game-bloom only restores Bloom; calibrated also blends the tone curve (suspended r5 experiment)")
    parser.add_argument("--capture", dest="frame_capture", action="store_true", help="Explicitly enable F8 frame capture; disabled by default")
    parser.add_argument("--tonemap-percent", type=int, default=25, help="SMSM curve contribution for calibrated look (0-100)")
    args = parser.parse_args()
    if not 0 <= args.tonemap_percent <= 100:
        parser.error("--tonemap-percent must be between 0 and 100")
    manifest = json.loads((args.capture / "manifest.json").read_text())
    if manifest["ClientBuild"] != BUILD:
        raise ValueError("Unreviewed client build; extract and review before updating the whitelist")
    if args.output.exists():
        raise FileExistsError("Use a fresh package output directory")
    compiler = Compiler(ROOT / "d3dcompiler_46.dll")
    records = {s["Hash"]: s for s in manifest["Shaders"] if s["Profile"] == "ps_5_0"}
    compiled = []
    shaders = dict(SHADERS)
    if args.extended:
        from patch_shader_asm import PATCHES, build_patch
        if not args.decompiler or not args.decompiler.is_file():
            raise ValueError("--extended requires --decompiler pointing to cmd_Decompiler 1.3.16")
        shaders.update({"00f2b6068017c6c6": "gpose depth-weighted aperture blur", "23d27700572e0c4d": "post-tonemap output dithering"})
        shaders.update(PATCHES)
    source_root = ROOT / "ShaderFixes"
    if args.look in ("game-bloom", "calibrated"):
        # Use the full game Bloom chain, not just the merge: both old blur
        # replacements change radius and energy. Do not synthesize light halos.
        for shader in BLOOM_SHADERS:
            shaders.pop(shader)
    if args.look == "calibrated":
        source_root = args.output / "build-audit" / "hlsl"
        source_root.mkdir(parents=True)
        for header in (ROOT / "ShaderFixes").glob("*.h"):
            shutil.copy2(header, source_root / header.name)
        settings = (source_root / "Configuration.h").read_text()
        for name, value in (("TONEMAP_SMSM_PERCENT", args.tonemap_percent), ("UseOriginalWhitening", 1), ("TONEMAP_RUNTIME_CONTROL", 1)):
            settings, count = re.subn(r"(#define\s+" + name + r"\s+)\d+", lambda m: m[1] + str(value), settings)
            if count != 1:
                raise ValueError(f"Expected one configuration definition: {name}")
        (source_root / "Configuration.h").write_text(settings)
        for shader in shaders:
            source = ROOT / "ShaderFixes" / f"{shader}-ps_replace.txt"
            if source.exists():
                shutil.copy2(source, source_root / source.name)
    for hash_value, effect in shaders.items():
        record = records[hash_value]
        original = (args.capture / record["File"]).read_bytes()
        if hashlib.sha256(original).hexdigest() != record["Sha256"]:
            raise ValueError(f"Corrupted extracted shader: {hash_value}")
        fnv = 0
        for value in original:
            fnv = ((fnv * 0x100000001b3) & 0xffffffffffffffff) ^ value
        if f"{fnv:016x}" != hash_value:
            raise ValueError(f"Wrong original hash: {hash_value}")
        source = source_root / f"{hash_value}-ps_replace.txt"
        if args.extended and hash_value in PATCHES:
            source, data = build_patch(hash_value, original, args.output / "build-audit", compiler, args.decompiler.resolve(), ROOT)
            diagnostics = "Original instruction stream roundtrip verified; bounded ASM insertion"
        else:
            data, diagnostics = compiler.compile(source)
        original_asm, patched_asm = compiler.disassemble(original), compiler.disassemble(data)
        try:
            verify_interface(original_asm, patched_asm, allow_ini_params=(hash_value == "23d27700572e0c4d" or
                             (args.look == "calibrated" and hash_value == "72a656dfd52149ad")))
        except ValueError as ex:
            raise ValueError(f"{hash_value} ({effect}): {ex}") from ex
        compiled.append((hash_value, effect, source, data, diagnostics))
    fixes = args.output / "SMSM-ShaderFixes"
    fixes.mkdir(parents=True)
    for header in source_root.glob("*.h"):
        shutil.copy2(header, fixes / header.name)
    rows = []
    for hash_value, effect, source, data, diagnostics in compiled:
        shutil.copy2(source, fixes / source.name)
        (fixes / source.with_suffix(".bin").name).write_bytes(data)
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
        ";analyse_frame = no_modifiers VK_F8": ("analyse_frame = no_modifiers VK_F8" if args.frame_capture
                                                 else "; F8 capture disabled: rebuild with --capture only when needed"),
        ";analyse_options = dump_rt jps clear_rt": "analyse_options = dump_rt jpg mono",
    }.items():
        config, count = re.subn("^" + re.escape(old) + "$", lambda match: new, config, flags=re.M)
        if count != 1:
            raise ValueError(f"Unexpected configuration template: {old}")
    (args.output / "d3dx.ini").write_text(config, encoding="utf-8")
    if args.extended:
        # x is reserved by this independent preview. Reset on frame boundary and
        # consume only after tone mapping, because the copy shader also runs early.
        config = config.replace("ini_params = -1", "ini_params = 120")
        config = insert_section(config, "Constants", "x = 0")
        config = insert_section(config, "Present", "post x = 0")
        config += "\n[ShaderOverrideSMSMOutputArm]\nhash = 72a656dfd52149ad\nx = 1\n"
        config += "\n[ShaderOverrideSMSMOutputConsume]\nhash = 23d27700572e0c4d\npost x = 0\n"
        (args.output / "d3dx.ini").write_text(config, encoding="utf-8")
    if args.look == "calibrated":
        config = config.replace("ini_params = -1", "ini_params = 120")
        config = insert_section(config, "Constants", "y = 1")
        # These keys isolate tone mapping, unlike F9 which bypasses every fix.
        config += "\n[KeySMSMGameTone]\nkey = no_modifiers VK_F6\ny = 0\n"
        config += "\n[KeySMSMCalibratedTone]\nkey = no_modifiers VK_F7\ny = 1\n"
        (args.output / "d3dx.ini").write_text(config, encoding="utf-8")
    files = {p.relative_to(args.output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(args.output.rglob("*")) if p.is_file() and "build-audit" not in p.relative_to(args.output).parts}
    (args.output / "SMSM-preview.json").write_text(json.dumps({
        "client_build": BUILD, "runtime_verified": False,
        "look": args.look, "tonemap_smsm_percent": args.tonemap_percent if args.look == "calibrated" else 100,
        "bloom": "game" if args.look in ("game-bloom", "calibrated") else "smsm",
        "frame_capture": args.frame_capture,
        "runtime_tone_control": args.look == "calibrated",
        "shaders": rows, "files": files
    }, indent=2), encoding="utf-8")
    print(f"Built {len(rows)} shaders; original hash, compilation and interface checks passed: {args.output}")


if __name__ == "__main__":
    main()
