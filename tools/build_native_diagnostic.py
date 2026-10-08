"""Build the default-off x64 ReShade diagnostic using the locked official SDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

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


def compile_cpp(source, output, include=None, dll=False):
    compiler, env, versions = compiler_environment()
    output.parent.mkdir(parents=True, exist_ok=True)
    args = [str(compiler), "/nologo", "/EHsc", "/std:c++17", "/O2", "/W4", "/utf-8", "/MT", "/Brepro",
            "/DNOMINMAX", str(source), "/Fe:" + str(output), "/Fo:" + str(output.with_suffix(".obj"))]
    if include:
        args += ["/I" + str(include)]
    if dll:
        args += ["/LD"]
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
    args = p.parse_args()
    commit = subprocess.check_output(["git", "-C", str(args.sdk), "rev-parse", "HEAD"], text=True).strip()
    if commit != SDK_COMMIT or subprocess.check_output(["git", "-C", str(args.sdk), "status", "--porcelain"]):
        raise ValueError("SDK must be the unmodified locked ReShade v6.8.0 commit")
    if args.output.exists():
        raise ValueError("Use a new immutable build output directory")
    output = args.output.resolve()
    addon = output / "SMSM.NativeLighting.addon64"
    versions = compile_cpp(ROOT / "addons/native_lighting/addon.cpp", addon, args.sdk / "include", dll=True)
    manifest = {"schema": 1, "reshade_version": SDK_VERSION, "sdk_commit": SDK_COMMIT, "api_version": 20,
                "architecture": "x64", "compiler": versions, "default_enabled": False, "runtime_verified": False,
                "capture_budget_bytes": 256 * 1024 * 1024, "shader_replacement": False,
                "files": {addon.name: hashlib.sha256(addon.read_bytes()).hexdigest()},
                "sources": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in (ROOT / "addons/native_lighting").glob("*.*")}}
    (output / "SMSM-native-package.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
