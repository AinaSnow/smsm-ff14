"""Actual R11G11B10 target writes: calibration and small lamp increments on native shaders."""
import argparse
import json
from pathlib import Path
import numpy as np
from build_single_light import TARGETS
from manage_preview import ROOT, encoded, read_package, digest
from shader_compile import Compiler
from offline_render import render
from validate_single_light import fixture, original_inputs


def run(output,package):
    output.mkdir(parents=True,exist_ok=False); manifest,receipt=read_package(package)
    source=output/"calibration.hlsl"
    source.write_text("cbuffer C:register(b0){float4 value;} float4 main(float4 p:SV_POSITION):SV_TARGET{return value;}")
    binary,diagnostics=Compiler(ROOT/"d3dcompiler_46.dll").compile(source)
    if diagnostics: raise ValueError(diagnostics)
    shader=output/"calibration.bin"; shader.write_bytes(binary)
    values=np.array([[0,0,0,.3],[1,2,4,.3],[.5,.25,.125,.3],
                     [2**-20,2**-19,2**-19,.3],[65024,65024,64512,.3],[.2,.4,.8,.3],
                     [.203,.407,.81,.3]],np.float32)
    expected=values[:,:3].copy(); expected[-2]=[.19921875,.3984375,.796875]
    # This WARP backend truncates these non-representable positive values.
    # Do not assume round-to-nearest or apply its half-ULP bound to GPU writes.
    expected[-1]=[.201171875,.40625,.796875]
    actual=render(shader,output/"calibration",8,6,animation=(0,values[:,None,:]),target_format="r11g11b10")[:,0]
    if not np.array_equal(actual[...,:3],np.broadcast_to(expected[:,None,None,:],actual[...,:3].shape)):
        raise AssertionError("R11G11B10 GPU/decoder calibration mismatch")
    checks=[dict(name="known values including subnormal and maximum finite",passed=True)]
    rows=[]; f=fixture(width=64,height=40,geometry="sphere")
    for target in TARGETS:
        original=package/"build-audit"/target/"original.bin"
        if digest(original.read_bytes())!=next(r["original_sha256"] for r in manifest["shaders"] if r["hash"]==target):
            raise ValueError("Original integrity mismatch")
        patched=package/"SMSM-ShaderFixes"/f"{target}-ps.bin"
        for scale in (.25,1,4,16):
            textures,constants,structured=original_inputs(f); constants[2][2,:3]*=scale
            draws={}
            for fmt in ("rgba32f","r11g11b10"):
                for label,ps in (("base",original),("lamp",patched)):
                    draws[fmt,label]=render(ps,output/f"{target}-{scale}-{fmt}-{label}",f["width"],f["height"],
                                           textures,constants,structured,targets=2,target_format=fmt)[0,...,:3]
            for label in ("base","lamp"):
                ref=draws["rgba32f",label]; packed=draws["r11g11b10",label]
                exponent=np.floor(np.log2(np.maximum(ref,2**-14)))
                ulp=np.exp2(exponent-np.array([6,6,5]))
                if not np.isfinite(packed).all() or np.any(np.abs(packed-ref)>ulp+2e-6):
                    raise AssertionError("Packed target exceeds one-ULP conversion bound")
                checks.append(dict(name=f"{target} {scale} {label} conversion bound",passed=True,
                                   max_error_ulps=float(np.max(np.abs(packed-ref)/ulp))))
            if not np.array_equal(draws["r11g11b10","lamp"][1],draws["r11g11b10","base"][1]):
                raise AssertionError("Packed specular target changed")
            checks.append(dict(name=f"{target} {scale} specular unchanged",passed=True))
            reference_delta=draws["rgba32f","lamp"][0]-draws["rgba32f","base"][0]
            packed_delta=draws["r11g11b10","lamp"][0]-draws["r11g11b10","base"][0]
            eligible=np.any(reference_delta>1e-7,axis=-1)
            rows.append(dict(target=target,native_diffuse_scale=scale,
                             eligible_pixels=int(eligible.sum()),
                             lost_all_channels_fraction=float(np.all(packed_delta==0,axis=-1)[eligible].mean()),
                             lost_per_channel_fraction=(packed_delta[eligible]==0).mean(0).tolist(),
                             mean_float32_delta=reference_delta[eligible].mean(0).tolist(),
                             mean_packed_delta=packed_delta[eligible].mean(0).tolist()))
    report=dict(check_count=len(checks),checks=checks,all_passed=True,measurements=rows,package_sha256=digest(receipt),
                backend="D3D11 WARP Draw -> R11G11B10_FLOAT staging Copy/Map -> raw packed readback",
                game_runtime_verified=False,real_gpu_performance_measured=False,
                limits=["Synthetic native-light brightness sweep, not a gameplay measurement",
                        "Observed WARP truncation is not a promise of identical rounding on every GPU",
                        "R11G11B10 stores no alpha; returned alpha=1 is only a Python convenience",
                        "No claim that changing intensity solves material, blend, or downstream tone issues"],
                format_reference="https://learn.microsoft.com/en-us/windows/win32/api/dxgiformat/ne-dxgiformat-dxgi_format")
    (output/"report.json").write_bytes(encoded(report))
    print(json.dumps(dict(checks=len(checks),measurements=rows),indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("output",type=Path)
    p.add_argument("--package",type=Path,default=ROOT/"artifacts/experimental-2026.09.15-single-light-v1")
    a=p.parse_args(); run(a.output,a.package)
