"""Replay the original depth-to-position PS; agreement does not establish live producer identity."""
import argparse
import json
from pathlib import Path
import numpy as np
from analyze_native_capture import analyze
from capture_reprojection import half_ulp
from manage_preview import ROOT, digest, encoded
from offline_render import render
from patch_material_light import load_original
from shader_compile import Compiler

PRODUCER = "edf9243383ddcd52"
PRODUCER_SHA = "acb10d73d882b5fd238cc5cf3bb3091cae3fcde8c09395a84195ff22024170d9"
VERTEX = """struct O {float4 p:SV_POSITION;float2 ndc:TEXCOORD0;};
O main(uint id:SV_VertexID) {O o;float2 uv=float2((id<<1)&2,id&2);
o.p=float4(uv*float2(2,-2)+float2(-1,1),0,1);o.ndc=o.p.xy;return o;}"""


def replay(shader, vertex, out, depth, common, camera, viewport):
    height, width = depth.shape
    tex = np.zeros((height, width, 4), dtype=np.float32)
    tex[..., 0] = depth
    # A half-pixel viewport legitimately extends beyond the original target.
    # Allocate one extra row/column, keep its viewport, then crop to source size.
    return render(shader, out, width + 1, height + 1, textures={0: tex},
                  constants={0: common, 1: camera}, vertex=vertex,
                  viewport=viewport[:4], target_format="rgba16f")[0, 0, :height, :width]


def run(capture, output, extraction):
    analyze(capture)  # Validate all paths, snapshot identities, lengths and hashes first.
    output.mkdir(parents=True, exist_ok=False)
    original = load_original(extraction, PRODUCER)
    if digest(original) != PRODUCER_SHA:
        raise ValueError("Unexpected original producer")
    shader = output / "original-producer.bin"
    shader.write_bytes(original)
    source = output / "replay-vs.hlsl"
    source.write_text(VERTEX, encoding="utf-8")
    vertex = output / "replay-vs.bin"
    vertex.write_bytes(Compiler().compile(source, "vs_5_0")[0])
    checks = []
    inv = np.array([[.8, 0, .05, .02], [0, .6, -.03, -.01],
                    [0, 0, .4, 1.2], [0, 0, -.5, 1]], dtype=np.float32)
    width, height = 64, 48
    camera = np.zeros((64, 4), dtype=np.float32); camera[14:18] = inv
    common = np.array([[1 / width, 1 / height, 0, 0]], dtype=np.float32)
    x, y = np.meshgrid(np.arange(width), np.arange(height))
    depth = (.05 + .85 * (x + y) / (width + height - 2)).astype(np.float32)
    depth[0, 0] = 0
    outputs = []
    for name, values in (("synthetic", depth), ("changed-depth", depth * .8 + .07)):
        actual = replay(shader, vertex, output / name, values, common, camera, [.5, .5, width, height])
        coords = np.stack([2*x/width-1, 1-2*y/height, np.maximum(values, 1e-6), np.ones_like(values)], -1)
        homogeneous = coords @ inv.astype(np.float64).T
        expected = homogeneous[..., :3] / homogeneous[..., 3:4]
        error = np.abs(actual[..., :3] - expected)
        passed = bool(np.all(error <= half_ulp(expected) + 2e-6) and np.all(actual[..., 3] == 1))
        checks.append({"name": name, "passed": passed, "max_abs_error": float(error.max())})
        outputs.append(actual)
    checks.append({"name": "depth_changes_actual_output", "passed": bool(np.max(np.abs(outputs[0]-outputs[1])) > .01)})
    if not all(c["passed"] for c in checks):
        (output / "report.json").write_bytes(encoded({"checks": checks}))
        raise ValueError("Original producer replay failed synthetic formula checks")

    manifest = json.loads(capture.read_bytes())
    draw = next(d for d in manifest["draws"] if d["target"] == "415a922293923fa4")
    if draw["pixel_sha256"] != "907ce4b6cc047a429a41c537a33a44c3fff04bd74ea66ad780e9b669d72dd740":
        raise ValueError("Unexpected consumer identity")
    inputs = {r["label"]: r for r in draw["resources"]}
    pos, dep = inputs["ps-t10"], inputs["om-depth"]
    if (pos.get("view_format"), dep.get("resource_format"), dep.get("view_format")) != (10, 44, 45):
        raise ValueError("Only explicitly typed RGBA16F position and D24S8 attachment are supported")
    width, height = pos["width"], pos["height"]
    if (dep["width"], dep["height"]) != (width, height) or draw["viewports"] != [[.5, .5, width, height, 0, 1]]:
        raise ValueError("This replay requires the observed half-pixel full-size viewport")
    packed = np.fromfile(capture.parent / dep["file"], dtype="<u4").reshape(height, width)
    depth = ((packed & 0xffffff).astype(np.float64) / 0xffffff).astype(np.float32)
    def cb(label):
        row = inputs[label]
        raw = np.fromfile(capture.parent / row["file"], dtype="<f4").reshape(-1, 4)
        return raw[row["constant_first"]:row["constant_first"] + row["constant_count"]]
    common, camera = cb("ps-b0"), cb("ps-b1")
    if len(common) < 1 or len(camera) < 18:
        raise ValueError("Camera/common declared ranges are insufficient")
    actual = replay(shader, vertex, output / "captured-input-replay", depth, common, camera, draw["viewports"][0])
    captured = np.fromfile(capture.parent / pos["file"], dtype="<f2").reshape(height, width, 4).astype(np.float32)
    finite = np.isfinite(captured[..., :3]).all(-1) & np.isfinite(actual[..., :3]).all(-1)
    error = np.abs(actual[..., :3] - captured[..., :3])
    report = {"source_kind": "original_shader_replay_with_synthetic_and_captured_inputs",
              "producer_hash": PRODUCER, "original_producer_sha256": PRODUCER_SHA, "checks": checks,
              "actual_warp_draws": 3, "live_comparison": {"finite_pixels": int(finite.sum()),
                  "fraction_xyz_exact": float(np.mean(np.all(actual[..., :3] == captured[..., :3], -1)[finite])),
                  "fraction_xyz_within_one_fp16_ulp": float(np.mean(np.all(error <= half_ulp(captured[..., :3]), -1)[finite])),
                  "max_abs_error": float(error[finite].max())},
              "live_producer_verified": False, "independent_position_evidence": False,
              "limits": ["Historical log links this producer; current r2 snapshot lacks writer shader identity",
                         "Replay uses point/clamp sampling and supplied consumer-stage depth/camera, not recorded producer-stage state",
                         "A matching depth reconstruction is circular evidence, not independent geometry verification"]}
    (output / "report.json").write_bytes(encoded(report))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--extraction", type=Path, default=ROOT / "artifacts/client-2026.09.15")
    args = parser.parse_args()
    run(args.capture, args.output, args.extraction)
