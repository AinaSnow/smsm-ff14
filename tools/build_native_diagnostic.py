"""Build the default-off x64 ReShade diagnostic using the locked official SDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import re

ROOT = Path(__file__).resolve().parents[1]
SDK_COMMIT = "18deaa52de0c425a78b329e9cb3c497281cd00ec"
SDK_VERSION = "6.8.0"


def compiler_environment():
    vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    installation = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires",
                        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip())
    vc = sorted((installation / "VC/Tools/MSVC").iterdir())[-1]
    sdk = Path(os.environ["ProgramFiles(x86)"]) / "Windows Kits/10"
    version = sorted((sdk / "Include").iterdir())[-1].name
    env = dict(os.environ)
    env["VSLANG"] = "1033"
    env["INCLUDE"] = ";".join(map(str, [vc / "include"] + [sdk / "Include" / version / n for n in ("ucrt", "shared", "um", "winrt")]))
    env["LIB"] = ";".join(map(str, [vc / "lib/x64"] + [sdk / "Lib" / version / n / "x64" for n in ("ucrt", "um")]))
    return vc / "bin/Hostx64/x64/cl.exe", env, {"msvc": vc.name, "windows_sdk": version}


def compile_cpp(source, output, include=None, dll=False, extra_args=()):
    compiler, env, versions = compiler_environment()
    output.parent.mkdir(parents=True, exist_ok=True)
    args = [str(compiler), "/nologo", "/EHsc", "/std:c++17", "/O2", "/W4", "/utf-8", "/MT", "/Brepro",
            "/DNOMINMAX", str(source), "/Fe:" + str(output), "/Fo:" + str(output.with_suffix(".obj"))]
    if include:
        args += ["/I" + str(include)]
    if dll:
        args += ["/LD"]
    args += list(extra_args)
    args += ["/link", "bcrypt.lib", "d3d11.lib", "d3dcompiler.lib", "user32.lib", "/Brepro", "/INCREMENTAL:NO"]
    result = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output.with_suffix(".build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return versions


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--sdk", type=Path, default=ROOT / "artifacts/reshade-sdk-v6.8.0")
    p.add_argument("--ambient-shader", type=Path, help="Embed the explicitly experimental diffuse-only shader; default off")
    p.add_argument('--ambient-bundle',type=Path,help='Validated exact visible-material ambient variants')
    p.add_argument("--coverage-shader", type=Path, help="Optional exact hair coverage marker, requires ambient package; default off")
    p.add_argument('--material-roster',type=Path,help='Verified named-package identity roster for original material census/sample')
    args = p.parse_args()
    if args.ambient_bundle and args.ambient_shader:raise ValueError('Choose single shader or bundle')
    if args.coverage_shader and not (args.ambient_shader or args.ambient_bundle):
        raise ValueError('Coverage control requires the experimental package command channel')
    if args.material_roster and not args.coverage_shader:raise ValueError('Material census requires output-audit package')
    commit = subprocess.check_output(["git", "-C", str(args.sdk), "rev-parse", "HEAD"], text=True).strip()
    if commit != SDK_COMMIT or subprocess.check_output(["git", "-C", str(args.sdk), "status", "--porcelain"]):
        raise ValueError("SDK must be the unmodified locked ReShade v6.8.0 commit")
    if args.output.exists():
        raise ValueError("Use a new immutable build output directory")
    output = args.output.resolve()
    addon = output / "SMSM.NativeLighting.addon64"
    extra=[];ambient_sha=None;ambient_variants=[]
    if args.ambient_shader:
        data=args.ambient_shader.read_bytes()
        if not data.startswith(b'DXBC'):raise ValueError('Expected validated DXBC candidate')
        output.mkdir(parents=True)
        (output/'native_ambient_bytecode.hpp').write_text('inline const unsigned char native_ambient_bytecode[] = {'+','.join(str(b) for b in data)+'};\n')
        extra=['/DSMSM_NATIVE_AMBIENT_EXPERIMENT','/I'+str(output)]
        ambient_sha=hashlib.sha256(data).hexdigest()
    if args.ambient_bundle:
        bundle=json.loads(args.ambient_bundle.read_bytes())
        if bundle.get('all_passed') is not True or {v['target'] for v in bundle['variants']}!={'1c5c89ac035f9a44','e86f0d4916054deb'}:
            raise ValueError('Expected both validated visible material variants')
        output.mkdir(parents=True);lines=[];rows=[]
        for i,meta in enumerate(bundle['variants']):
            path=(args.ambient_bundle.parent/meta['file']).resolve()
            if not path.is_relative_to(args.ambient_bundle.parent.resolve()):raise ValueError('Variant path escapes bundle')
            data=path.read_bytes()
            if not data.startswith(b'DXBC') or hashlib.sha256(data).hexdigest()!=meta['candidate_sha256'] or meta['resource_slot']!=14:
                raise ValueError('Invalid visible candidate bytes/binding')
            if not re.fullmatch('[0-9a-f]{64}',meta['original_sha256']):raise ValueError('Invalid original shader identity')
            name='native_ambient_bytecode' if i==0 else 'native_ambient_bytecode_'+str(i)
            lines.append('inline const unsigned char '+name+'[] = {'+','.join(str(b) for b in data)+'};')
            rows.append('{"'+meta['original_sha256']+'",'+name+',sizeof('+name+'),14}')
            ambient_variants.append({k:meta[k] for k in ('target','original_sha256','candidate_sha256','resource_slot')})
        lines.append('struct NativeAmbientVariant {const char *sha;const unsigned char *data;size_t size;unsigned slot;};')
        lines.append('inline const NativeAmbientVariant native_ambient_variants[] = {'+','.join(rows)+'};')
        (output/'native_ambient_bytecode.hpp').write_text('\n'.join(lines)+'\n')
        extra=['/DSMSM_NATIVE_AMBIENT_EXPERIMENT','/DSMSM_NATIVE_AMBIENT_BUNDLE','/I'+str(output)]
    coverage_sha=None
    if args.coverage_shader:
        data=args.coverage_shader.read_bytes()
        if not data.startswith(b'DXBC'):raise ValueError('Expected validated coverage DXBC')
        (output/'native_coverage_bytecode.hpp').write_text('inline const unsigned char native_coverage_bytecode[] = {'+','.join(str(b) for b in data)+'};\n')
        extra.append('/DSMSM_NATIVE_COVERAGE')
        coverage_sha=hashlib.sha256(data).hexdigest()
    roster_sha=None;roster_count=0
    if args.material_roster:
        raw=args.material_roster.read_bytes();roster=json.loads(raw)
        if roster.get('schema')!=1 or roster.get('client_build')!='2026.09.15.0000.0000' or roster.get('verified_package_reads') is not True:
            raise ValueError('Expected verified material roster for this client build')
        lines=[];seen=set();hashes=set()
        for item in roster['shaders']:
            sha,hash_,packages=item['sha256'],item['hash'],item['packages']
            if not re.fullmatch('[0-9a-f]{64}',sha) or not re.fullmatch('[0-9a-f]{16}',hash_) or sha in seen or hash_ in hashes:
                raise ValueError('Invalid/duplicate material shader identity')
            if not packages or any(p not in ['hair','skin','character','characterlegacy','characterglass','characterstockings'] for p in packages):
                raise ValueError('Unexpected material package')
            seen.add(sha);hashes.add(hash_)
            lines.append('{"'+sha+'",{"'+hash_+'","'+'|'.join(packages)+'"}}')
        if not 1<=len(lines)<=10000:raise ValueError('Unexpected roster size')
        header='struct MaterialIdentity {std::string hash,packages;};\ninline const std::map<std::string,MaterialIdentity> native_material_roster = {\n'+',\n'.join(lines)+'\n};\n'
        (output/'native_material_roster.hpp').write_text(header)
        extra.append('/DSMSM_MATERIAL_ROSTER');roster_sha=hashlib.sha256(raw).hexdigest();roster_count=len(lines)
    versions = compile_cpp(ROOT / "addons/native_lighting/addon.cpp", addon, args.sdk / "include", dll=True, extra_args=extra)
    manifest = {"schema": 1, "reshade_version": SDK_VERSION, "sdk_commit": SDK_COMMIT, "api_version": 20,
                "architecture": "x64", "compiler": versions, "default_enabled": False, "runtime_verified": False,
                "capture_budget_bytes": 256 * 1024 * 1024, "shader_replacement": bool(args.ambient_shader or args.ambient_bundle),
                "ambient_shader_sha256":ambient_sha,
                "ambient_variants":ambient_variants,
                "coverage_shader_sha256":coverage_sha,
                "output_audit":bool(args.coverage_shader),
                "material_input_probe":bool(args.material_roster),
                "material_producer_trace":bool(args.material_roster),
                "material_roster_sha256":roster_sha,"material_shader_count":roster_count,
                "files": {addon.name: hashlib.sha256(addon.read_bytes()).hexdigest()},
                "sources": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in (ROOT / "addons/native_lighting").glob("*.*")}}
    (output / "SMSM-native-package.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
