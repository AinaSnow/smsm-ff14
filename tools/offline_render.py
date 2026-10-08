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


def unpack_r11(words):
    """DXGI R11G11B10_FLOAT: unsigned 5-bit exponents, 6/6/5-bit mantissas.

    Alpha 1 is a readback convenience only; this target stores NO alpha.
    """
    channels=[]
    for shift,bits in ((0,6),(11,6),(22,5)):
        field=(words>>shift)&((1<<(bits+5))-1)
        exponent=(field>>bits).astype(np.int32); mantissa=(field&((1<<bits)-1)).astype(np.float32)
        value=np.where(exponent==0,np.ldexp(mantissa,-14-bits),np.ldexp(1+mantissa/(1<<bits),exponent-15))
        value=np.where(exponent==31,np.where(mantissa==0,np.inf,np.nan),value)
        channels.append(value)
    return np.stack([*channels,np.ones(words.shape,dtype=np.float32)],-1).astype(np.float32)


def render(shader, output, width, height, textures=None, constants=None, structured=None,
           targets=1, animation=None, viewport=None, vertex=None, draws=1, blend="overwrite",target_format="rgba32f",cubes=None):
    """Inputs and every raw float32 output remain on disk for replay/diff.

    animation is (constant slot, frames x vectors x float4); updated on the SAME
    D3D11 device before each draw. Synthetic input samplers are point/clamp.
    draws repeats the pass without clearing; blend is an explicit synthetic OM
    mode (overwrite/add/source-alpha), with alpha overwritten in all modes.
    r11g11b10 retains packed .r11 readbacks; returned alpha=1 is synthesized.
    rgba16f retains packed .f16 readbacks. cubes maps slots to 6 x H x H x RGBA
    arrays in +X/-X/+Y/-Y/+Z/-Z order, bound as a single-cube TextureCubeArray.
    """
    if not isinstance(draws, int) or not 1 <= draws <= 64 or blend not in ("overwrite", "add", "source-alpha"):
        raise ValueError("Invalid draw count or blend mode")
    if target_format not in ("rgba32f","r11g11b10","rgba16f"): raise ValueError("Invalid target format")
    if set(textures or {})&set(cubes or {}) or (set(textures or {})|set(cubes or {}))&set(structured or {}):
        raise ValueError("Resource slots overlap")
    output.mkdir(parents=True, exist_ok=False)
    quote = lambda p: json.dumps(str(Path(p).resolve()).replace("\\", "/"), ensure_ascii=False)
    lines = [f"size {width} {height} {targets}", "shader " + quote(shader), "output " + quote(output / "pixels")]
    lines.extend([f"draws {draws}", f"blend {blend}",f"format {target_format}"])
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
    for slot,array in (cubes or {}).items():
        array=np.ascontiguousarray(array,dtype="<f4")
        if array.ndim!=4 or array.shape[0]!=6 or array.shape[1]!=array.shape[2] or array.shape[3]!=4:
            raise ValueError("Cube must be 6 x H x H x RGBA")
        path=output/f"cube{slot}.f32"; array.tofile(path)
        lines.append(f"cube {slot} {array.shape[1]} "+quote(path))
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
    def readback(frame,rt):
        if target_format=="rgba32f":
            return np.fromfile(output/f"pixels-f{frame}-rt{rt}.f32",dtype="<f4").reshape(height,width,4)
        if target_format=="rgba16f":
            return np.fromfile(output/f"pixels-f{frame}-rt{rt}.f16",dtype="<f2").astype(np.float32).reshape(height,width,4)
        return unpack_r11(np.fromfile(output/f"pixels-f{frame}-rt{rt}.r11",dtype="<u4").reshape(height,width))
    return np.stack([np.stack([readback(frame,rt)
                               for rt in range(targets)]) for frame in range(frames)])


if __name__ == "__main__":
    print(build_renderer())
