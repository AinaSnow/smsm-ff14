"""Compare fixed-layout native ambient regions under camera changes; no light modification."""
import argparse
import json
from pathlib import Path
import struct
import numpy as np
from analyze_native_capture import analyze, CAMERA
from manage_preview import encoded

TARGET = "415a922293923fa4"


def decode_regions(raw, first_constant, constant_count):
    if min(first_constant, constant_count) < 0:
        raise ValueError("Negative constant range")
    base = first_constant * 16
    end = min(len(raw), base + constant_count * 16)
    if base + 64 > end:
        raise ValueError("Ambient header outside bound range")
    count = struct.unpack_from("<I", raw, base)[0]
    # Reflection declares 64 entries, each 12 float4s, after a 64-byte header.
    if count > 64 or base + 64 + count * 192 > end:
        raise ValueError("Ambient count exceeds shader declaration or bound range")
    regions = []
    for index in range(count):
        offset = base + 64 + index * 192
        kind = struct.unpack_from("<i", raw, offset + 172)[0]
        if kind not in (0, 1, 2, 3):
            raise ValueError("Unknown region type; do not guess its matrix semantics")
        matrix = np.array(struct.unpack_from("<12f", raw, offset + 96)).reshape(3, 4)
        signature = np.array(struct.unpack_from("<f", raw, offset + 92) +
                             struct.unpack_from("<7f", raw, offset + 144))
        sh = np.array(struct.unpack_from("<12f", raw, offset)).reshape(3, 4)
        color = np.array(struct.unpack_from("<3f", raw, offset + 48))
        if not np.isfinite(np.r_[signature, sh.ravel(), color]).all() or (kind and not np.isfinite(matrix).all()):
            raise ValueError("Nonfinite active ambient fields")
        regions.append({"type": kind, "signature": signature, "view_to_region": matrix,
                        "sh": sh, "color": color})
    return regions


def read_capture(path):
    checked = analyze(path)
    manifest = json.loads(path.read_bytes())
    draw = next(d for d in manifest["draws"] if d["target"] == TARGET)
    if draw["pixel_sha256"] != CAMERA[TARGET][0]:
        raise ValueError("The reflected layout requires the exact original shader")
    resource = next(r for r in draw["resources"] if r["label"] == "ps-b2")
    if resource["status"] != "captured":
        raise ValueError("Ambient buffer was not captured")
    regions = decode_regions((path.parent / resource["file"]).read_bytes(),
                             resource["constant_first"], resource["constant_count"])
    matrices = checked["resources"][TARGET + ":ps-b1"]["candidate_matrices"]
    world_from_view = np.eye(4)
    world_from_view[:3] = matrices["m_MainViewToWorldMatrix"]["row_major_values"]
    if not np.isfinite(world_from_view).all() or abs(np.linalg.det(world_from_view)) < 1e-8:
        raise ValueError("Invalid camera affine transform")
    return regions, world_from_view


def compare(before, after):
    left, left_camera = before; right, right_camera = after
    result = {"region_counts": [len(left), len(right)], "entries": [],
              "pairing": "same array index and unchanged type/env-index/interpolation-range/priority; no best-match search",
              "producer_and_world_semantics_independently_verified": False}
    if len(left) != len(right):
        result["status"] = "different_region_sets"
        return result
    result["status"] = "compared"
    for index, (a, b) in enumerate(zip(left, right)):
        row = {"entry": index, "types": [a["type"], b["type"]]}
        if a["type"] != b["type"] or not np.array_equal(a["signature"], b["signature"]):
            row["status"] = "identity_fields_changed_no_pair"
        elif a["type"] == 0:
            row["status"] = "global_region_matrix_unused_by_shader"
        else:
            # The shader multiplies view position by its region inverse matrix.
            # Express that mapping in the camera's named world reference.
            aw = a["view_to_region"] @ np.linalg.inv(left_camera)
            bw = b["view_to_region"] @ np.linalg.inv(right_camera)
            row.update(status="local_region_compared",
                       view_matrix_max_delta=float(np.max(np.abs(a["view_to_region"] - b["view_to_region"]))),
                       world_reference_max_delta=float(np.max(np.abs(aw - bw))))
        row["color_max_delta"] = float(np.max(np.abs(a["color"] - b["color"])))
        row["sh_payload_max_delta"] = float(np.max(np.abs(a["sh"] - b["sh"])))
        result["entries"].append(row)
    result["limits"] = ["Type zero skips the spatial matrix in the original shader",
                         "SH/color may change with time, weather and camera; this is not a frozen-light comparison",
                         "Camera field interpretation and per-pixel/object coverage still require corroboration"]
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("before", type=Path); p.add_argument("after", type=Path); p.add_argument("output", type=Path)
    args = p.parse_args()
    result = compare(read_capture(args.before), read_capture(args.after))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as output:
        output.write(encoded(result))
    print(json.dumps(result, indent=2))
