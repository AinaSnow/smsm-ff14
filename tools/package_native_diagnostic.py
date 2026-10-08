"""Package the default-off add-on and its tools, excluding the official ReShade runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from build_native_diagnostic import ROOT


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("package", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument('--allow-shader-experiment',action='store_true')
    args = p.parse_args()
    manifest = json.loads((args.package / "SMSM-native-package.json").read_bytes())
    if manifest["default_enabled"] is not False or (manifest["shader_replacement"] is not False and not args.allow_shader_experiment):
        raise ValueError("Diagnostic package must default off and not replace shaders")
    entries = {"package/" + name: args.package / name for name in (*manifest["files"], "SMSM-native-package.json")}
    for name in manifest["files"]:
        if hashlib.sha256((args.package / name).read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError("Candidate integrity failure")
    for name in ("native_environment.py", "manage_preview.py", "request_native_capture.py", "analyze_native_capture.py", "record_validation.py"):
        entries["tools/" + name] = ROOT / "tools" / name
    if manifest['shader_replacement']:
        entries['tools/request_native_ambient.py']=ROOT/'tools/request_native_ambient.py'
        entries['docs/NATIVE-AMBIENT-SURFACE.md']=ROOT/'docs/NATIVE-AMBIENT-SURFACE.md'
        entries['docs/validation/native-ambient-r4-2026-10-09.json']=ROOT/'docs/validation/native-ambient-r4-2026-10-09.json'
        entries['docs/validation/native-hair-identity-2026-10-09.json']=ROOT/'docs/validation/native-hair-identity-2026-10-09.json'
    if manifest.get('coverage_shader_sha256'):
        entries['docs/NATIVE-COVERAGE.md']=ROOT/'docs/NATIVE-COVERAGE.md'
        entries['docs/validation/native-coverage-r5-2026-10-09.json']=ROOT/'docs/validation/native-coverage-r5-2026-10-09.json'
        entries['docs/validation/native-coverage-pixels-2026-10-09.json']=ROOT/'docs/validation/native-coverage-pixels-2026-10-09.json'
    if manifest.get('output_audit'):
        entries['docs/NATIVE-OUTPUT-AUDIT.md']=ROOT/'docs/NATIVE-OUTPUT-AUDIT.md'
        entries['docs/validation/native-output-r6-2026-10-09.json']=ROOT/'docs/validation/native-output-r6-2026-10-09.json'
        entries['tools/analyze_native_output.py']=ROOT/'tools/analyze_native_output.py'
    if manifest.get('material_roster_sha256'):
        entries['docs/NATIVE-MATERIAL-CENSUS.md']=ROOT/'docs/NATIVE-MATERIAL-CENSUS.md'
        entries['docs/validation/native-material-r7-2026-10-09.json']=ROOT/'docs/validation/native-material-r7-2026-10-09.json'
        entries['tools/summarize_native_materials.py']=ROOT/'tools/summarize_native_materials.py'
    if manifest.get('ambient_variants'):
        entries['docs/NATIVE-VISIBLE-AMBIENT.md']=ROOT/'docs/NATIVE-VISIBLE-AMBIENT.md'
        entries['docs/validation/native-visible-r8-2026-10-09.json']=ROOT/'docs/validation/native-visible-r8-2026-10-09.json'
    for name in ("NATIVE-DIAGNOSTIC.md", "NATIVE-DIAGNOSTIC-R2.md", "NATIVE-PRODUCERS.md", "NATIVE-LIGHTING-AUDIT.md", "NATIVE-LIGHTING-PLAN.md", "MANAGEMENT.md",
                 "validation/native-diagnostic-2026-10-08.json", "validation/native-diagnostic-r2-2026-10-08.json",
                 "validation/native-producer-r3-2026-10-09.json",
                 "validation/native-live-first-capture-2026-10-08.json", "validation/native-live-camera-comparison-2026-10-08.json",
                 "validation/native-live-scene-switch-2026-10-08.json"):
        entries["docs/" + name] = ROOT / "docs" / name
    entries["LICENSE"] = ROOT / "LICENSE"
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name,path in entries.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "x", zipfile.ZIP_DEFLATED) as archive:
        for name,path in sorted(entries.items()):
            archive.writestr(name, path.read_bytes())
        archive.writestr("SHA256SUMS.json", json.dumps(hashes, indent=2) + "\n")
    with zipfile.ZipFile(args.output) as archive:
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == sha for name,sha in hashes.items())
    sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".zip.sha256").write_text(f"{sha}  {args.output.name}\n", encoding="utf-8")
    print(f"Verified native candidate archive: {sha}")


if __name__ == "__main__":
    main()
