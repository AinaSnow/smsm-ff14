"""Build and drive the real D3D11 WARP rendering harness (not CreateShader-only)."""
import json
import os
from pathlib import Path
import subprocess
import numpy as np
from manage_preview import ROOT


def build_renderer():
    output = ROOT / "artifacts/offline-renderer"
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / "tools/offline/render_ps.cpp"
    exe = output / "render_ps.exe"
    if exe.exists() and exe.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return exe
    vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    installation = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires",
                        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip())
    vc = sorted((installation / "VC/Tools/MSVC").iterdir())[-1]
    sdk = Path(os.environ["ProgramFiles(x86)"]) / "Windows Kits/10"
    version = sorted((sdk / "Include").iterdir())[-1].name
    env = dict(os.environ)
    env["INCLUDE"] = ";".join(map(str, [vc / "include"] + [sdk / "Include" / version / n for n in ("ucrt", "shared", "um", "winrt")]))
    env["LIB"] = ";".join(map(str, [vc / "lib/x64"] + [sdk / "Lib" / version / n / "x64" for n in ("ucrt", "um")]))
    compiler = vc / "bin/Hostx64/x64/cl.exe"
    result = subprocess.run([str(compiler), "/nologo", "/EHsc", "/std:c++17", "/O2", "/utf-8",
                             str(source), "/Fe:" + str(exe), "/Fo:" + str(output / "render_ps.obj"),
                             "d3dcompiler.lib"], env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return exe


def render(shader, output, width, height, textures=None, constants=None, structured=None,
           targets=1, animation=None, viewport=None, vertex=None, draws=1, blend="overwrite"):
    """Inputs and every raw float32 output remain on disk for replay/diff.

    animation is (constant slot, frames x vectors x float4); updated on the SAME
    D3D11 device before each draw. Synthetic input samplers are point/clamp.
    draws repeats the pass without clearing; blend is an explicit synthetic OM
    mode (overwrite/add/source-alpha), with alpha overwritten in all modes.
    """
    if not isinstance(draws, int) or not 1 <= draws <= 64 or blend not in ("overwrite", "add", "source-alpha"):
        raise ValueError("Invalid draw count or blend mode")
    output.mkdir(parents=True, exist_ok=False)
    quote = lambda p: json.dumps(str(Path(p).resolve()).replace("\\", "/"), ensure_ascii=False)
    lines = [f"size {width} {height} {targets}", "shader " + quote(shader), "output " + quote(output / "pixels")]
    lines.extend([f"draws {draws}", f"blend {blend}"])
    if vertex:
        lines.append("vertex " + quote(vertex))
    if viewport:
        lines.append("viewport " + " ".join(map(str, viewport)))
    for slot, array in (textures or {}).items():
        array = np.ascontiguousarray(array, dtype="<f4")
        if array.ndim != 3 or array.shape[2] != 4:
            raise ValueError("Textures must be H x W x RGBA")
        path = output / f"t{slot}.f32"; array.tofile(path)
        lines.append(f"texture {slot} {array.shape[1]} {array.shape[0]} " + quote(path))
    for slot, array in (constants or {}).items():
        path = output / f"b{slot}.f32"; np.asarray(array, dtype="<f4").tofile(path)
        lines.append(f"constant {slot} " + quote(path))
    for slot, (stride, raw) in (structured or {}).items():
        path = output / f"structured{slot}.bin"; path.write_bytes(raw)
        lines.append(f"structured {slot} {stride} " + quote(path))
    frames = 1
    if animation is not None:
        slot, array = animation
        array = np.asarray(array, dtype="<f4")
        if array.ndim != 3 or array.shape[2] != 4 or not 1 <= len(array) <= 256:
            raise ValueError("Animation must be frames x vectors x float4")
        frames = len(array)
        path = output / f"animation-b{slot}.f32"; array.tofile(path)
        lines.extend([f"frames {frames}", f"animation {slot} " + quote(path)])
    job = output / "job.txt"; job.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = subprocess.run([str(build_renderer()), str(job.resolve())], capture_output=True, text=True, timeout=120)
    (output / "render.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return np.stack([np.stack([np.fromfile(output / f"pixels-f{frame}-rt{rt}.f32", dtype="<f4").reshape(height, width, 4)
                               for rt in range(targets)]) for frame in range(frames)])


if __name__ == "__main__":
    print(build_renderer())
