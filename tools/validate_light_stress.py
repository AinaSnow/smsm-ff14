"""Actual host-shader material-branch and repeated-draw audit, using synthetic OM states."""
import argparse
import json
from pathlib import Path
import numpy as np
from build_single_light import TARGETS
from manage_preview import ROOT, encoded, read_package, digest
from offline_render import render
from shader_compile import Compiler
from validate_single_light import fixture, original_inputs, cpu_light


def run(output, package):
    output.mkdir(parents=True, exist_ok=False)
    manifest, receipt = read_package(package)
    s = manifest["single_light"]
    f = fixture(width=48, height=32, geometry="sphere")
    expected = cpu_light(f, s["position_view"], s["color_linear"], s["intensity"], s["range"])
    checks, observations = [], []

    def check(name, actual, reference, tolerance=4e-6):
        error = float(np.max(np.abs(actual-reference)))
        passed = bool(np.isfinite(actual).all() and np.isfinite(reference).all() and error <= tolerance)
        checks.append(dict(name=name, passed=passed, max_abs_error=error, tolerance=tolerance))
        if not passed:
            raise AssertionError(f"{name}: {error}")

    # Independently calibrate the new OM harness with non-binary alpha. The
    # native light fixture emits alpha 0/1, insufficient to verify SRC_ALPHA.
    source=output/"blend-calibration.hlsl"
    source.write_text("struct O { float4 a:SV_TARGET0; float4 b:SV_TARGET1; }; "
                      "O main(float4 p:SV_POSITION) { O o; o.a=float4(.2,.4,.8,.25); "
                      "o.b=float4(.8,.1,.3,.75); return o; }")
    binary,diagnostics=Compiler(ROOT/"d3dcompiler_46.dll").compile(source)
    if diagnostics: raise ValueError(diagnostics)
    shader=output/"blend-calibration.bin"; shader.write_bytes(binary)
    values=np.array([[.2,.4,.8,.25],[.8,.1,.3,.75]],dtype=np.float32)
    for mode in ("overwrite","add","source-alpha"):
        for count in (1,2,4):
            image=render(shader,output/f"calibration-{mode}-{count}",8,6,targets=2,draws=count,blend=mode)[0]
            weight=count if mode=="add" else (1-(1-values[:,3:4])**count if mode=="source-alpha" else 1)
            reference=values.copy(); reference[:,:3]*=weight
            reference=np.broadcast_to(reference[:,None,None,:],image.shape)
            check(f"OM calibration {mode} x{count}",image,reference,3e-7)

    for target in TARGETS:
        original = package / "build-audit" / target / "original.bin"
        if digest(original.read_bytes()) != next(r["original_sha256"] for r in manifest["shaders"] if r["hash"] == target):
            raise ValueError("Unverified original shader")
        patched = package / "SMSM-ShaderFixes" / f"{target}-ps.bin"
        # Numeric branch selectors only. Do not label unverified IDs skin/hair.
        cases = [(f"type-{kind}", kind, 0, 1) for kind in (0,1,2,3)]
        cases += [("semi-half", 0, .5, 1), ("semi-full", 0, 1, 1), ("zero-native-mask", 0, 0, 0)]
        for label, kind, semi, shadow in cases:
            textures, constants, structured = original_inputs(f)
            # Distinct material IDs select different records when the host's
            # SemiTransparency interpolation changes. Test unsigned bit layout.
            textures[3] = textures[3].copy(); textures[3][...,3] = 31/255
            textures[4][...,0] = 191/255
            records = np.frombuffer(structured[2][1], dtype="<f4").copy().reshape(256,32)
            records.view("<u4")[:,0] = kind
            records[:,3:8] = [.3,.15,.2,.5,.4]
            records[:,9:12] = [.1,.2,.3]
            records[:,13:16] = [.1,.2,.5]
            structured[2] = (128, records.tobytes())
            constants[3][0,0] = semi
            textures[8][...] = shadow

            def draw(name, shader, **kwargs):
                return render(shader, output/f"{target}-{label}-{name}", f["width"], f["height"],
                              textures, constants, structured, targets=2, **kwargs)[0]

            baseline, lit = draw("original", original), draw("injected", patched)
            check(f"{target} {label} additive diffuse", lit[0,...,:3]-baseline[0,...,:3], expected)
            check(f"{target} {label} alpha", lit[0,...,3], baseline[0,...,3], 0)
            check(f"{target} {label} specular", lit[1], baseline[1], 0)
            observations.append(dict(target=target, case=label, alpha_min=float(baseline[0,...,3].min()),
                                     alpha_max=float(baseline[0,...,3].max()),
                                     original_diffuse_mean=float(baseline[0,...,:3].mean()),
                                     original_specular_mean=float(baseline[1,...,:3].mean()),
                                     injected_delta_mean=float((lit[0,...,:3]-baseline[0,...,:3]).mean())))
            # Three explicitly specified OM states; clear once, draw repeatedly.
            # No assertion that FF14 actually uses any of them at this stage.
            if label in ("type-0", "semi-half", "zero-native-mask"):
                for mode in ("overwrite", "add", "source-alpha"):
                    for count in (1,2,4):
                        base_many = draw(f"{mode}-{count}-base", original, draws=count, blend=mode)
                        many = draw(f"{mode}-{count}-light", patched, draws=count, blend=mode)
                        alpha = baseline[0,...,3:4]
                        weight = count if mode == "add" else (1-(1-alpha)**count if mode == "source-alpha" else 1)
                        check(f"{target} {label} {mode} x{count} delta", many[0,...,:3]-base_many[0,...,:3],
                              expected*weight, 1e-5)
                        check(f"{target} {label} {mode} x{count} alpha", many[0,...,3], base_many[0,...,3], 0)
                        check(f"{target} {label} {mode} x{count} specular", many[1], base_many[1], 0)
            print("PASS", target, label, flush=True)
    report = dict(backend="D3D11 WARP Draw/CopyResource/Map", synthetic_inputs=True,
                  package_sha256=digest(receipt), checks=checks, check_count=len(checks), all_passed=True,
                  material_observations=observations, game_blend_state_verified=False,
                  material_semantics_verified=False, real_gpu_performance_measured=False,
                  findings=["Current injection ignores material branch selector and native shadow mask by design",
                            "Additive repeated draws multiply lamp energy; overwrite does not",
                            "Source-alpha blending can suppress injected RGB despite preserved shader alpha",
                            "Do not gate a new lamp with original directional-light shadow/alpha without stage evidence"])
    (output/"report.json").write_bytes(encoded(report))
    print(json.dumps(dict(output=str(output), checks=len(checks), passed=True)))
    return report


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("output", type=Path)
    p.add_argument("--package", type=Path, default=ROOT/"artifacts/experimental-2026.09.15-single-light-v1")
    a=p.parse_args(); run(a.output, a.package)
