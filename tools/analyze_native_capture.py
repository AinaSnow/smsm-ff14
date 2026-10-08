"""Verify native snapshots and compare candidate bytes; never infer lighting semantics from change alone."""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import struct

CAMERA = {
    "415a922293923fa4": ("907ce4b6cc047a429a41c537a33a44c3fff04bd74ea66ad780e9b669d72dd740", "ps-b1"),
    "980154264a89fba1": ("f8face0fb530f3b884c2a6b2af289fa1a8bb3ed0e4301b03efd34afadf7c76f7", "ps-b3"),
}


def candidate_matrices(raw, resource):
    # Offsets come from reflection of the exact original PS, not heuristic matrix scans.
    base = resource["constant_first"] * 16
    bound_end = min(len(raw), base + resource["constant_count"] * 16)
    result = {}
    for name, offset, rows in (("m_ViewMatrix", 0, 3), ("m_InverseViewMatrix", 48, 3),
                              ("m_ViewProjectionMatrix", 96, 4), ("m_InverseViewProjectionMatrix", 160, 4),
                              ("m_InverseProjectionMatrix", 224, 4), ("m_ProjectionMatrix", 288, 4),
                              ("m_MainViewToProjectionMatrix", 352, 4), ("m_MainViewToWorldMatrix", 880, 3)):
        start = base + offset
        if start + rows * 16 > bound_end:
            result[name] = {"status": "outside_bound_range", "reflected_offset": offset}
            continue
        values = struct.unpack_from(f"<{rows * 4}f", raw, start)
        if not all(map(math.isfinite, values)):
            result[name] = {"status": "nonfinite_candidate", "reflected_offset": offset}
        else:
            result[name] = {"status": "candidate_only", "reflected_offset": offset,
                            "row_major_values": [list(values[i:i + 4]) for i in range(0, len(values), 4)]}
    return result


def analyze(path):
    report = json.loads(path.read_bytes())
    if report.get("schema") != 1 or report["selected_raw_bytes"] > report["budget_bytes"]:
        raise ValueError("Invalid capture schema/budget")
    rows = {}
    total = 0
    for draw in report["draws"]:
        if draw["frame"] != report["source_frame"] or len(draw["viewports"]) == 0:
            raise ValueError("Missing viewport or cross-frame draw")
        for resource in draw["resources"]:
            if resource["frame"] != draw["frame"] or resource["draw"] != draw["draw"] or resource["phase"] != "pre_draw":
                raise ValueError("Mixed resource snapshot")
            key = draw["target"] + ":" + resource["label"]
            if key in rows:
                raise ValueError("Duplicate target resource")
            rows[key] = {k: resource[k] for k in ("status", "semantic", "generation", "last_observed_event") if k in resource}
            if resource["status"] == "captured":
                filename = resource["file"]
                if PurePosixPath(filename).name != filename or "\\" in filename or ":" in filename:
                    raise ValueError("Unsafe capture payload path")
                payload = path.parent / filename
                if payload.is_symlink() or not payload.resolve().is_relative_to(path.parent.resolve()):
                    raise ValueError("Payload escapes capture")
                raw = payload.read_bytes()
                sha = hashlib.sha256(raw).hexdigest()
                if sha != resource["sha256"] or len(raw) != resource["selected_bytes"]:
                    raise ValueError(f"Damaged payload: {key}")
                total += len(raw)
                rows[key]["sha256"] = sha
                rows[key]["bytes"] = len(raw)
                identity = CAMERA.get(draw["target"])
                if identity and draw["pixel_sha256"] == identity[0] and resource["label"] == identity[1]:
                    rows[key]["candidate_matrices"] = candidate_matrices(raw, resource)
    if total > report["selected_raw_bytes"]:
        raise ValueError("Payload exceeds declared selected bytes")
    return {"source_frame": report["source_frame"], "status": report["status"], "raw_bytes_verified": total,
            "semantics_verified": False, "resources": rows}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("capture", type=Path)
    p.add_argument("--compare", type=Path)
    args = p.parse_args()
    result = analyze(args.capture)
    if args.compare:
        previous = analyze(args.compare)
        result["changed_candidate_payloads"] = [key for key, row in result["resources"].items()
            if row.get("sha256") and previous["resources"].get(key, {}).get("sha256") != row["sha256"]]
        result["comparison_note"] = "Changed bytes alone do not establish world-space lighting, camera semantics or draw correspondence"
    print(json.dumps(result, indent=2))
