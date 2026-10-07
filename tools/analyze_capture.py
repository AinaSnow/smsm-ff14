"""Summarize observed shader stages in a 3DMigoto frame capture without copying images."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("extraction", type=Path)
    parser.add_argument("package", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    log_path = args.capture / "log.txt"
    log = log_path.read_text(encoding="utf-8", errors="replace")
    manifest = json.loads((args.extraction / "manifest.json").read_text())
    package = json.loads((args.package / "SMSM-preview.json").read_text())
    records = {s["Hash"]: s for s in manifest["Shaders"]}
    bound = set(re.findall(r"PSSetShader\([^\n]*hash=([0-9a-f]{16})", log))
    rendered = defaultdict(set)
    executed = defaultdict(set)
    active_ps = None
    armed = False
    output_gate = []
    for line in log.splitlines():
        if "PSSetShader(" in line:
            match = re.search(r"hash=([0-9a-f]{16})", line)
            active_ps = match[1] if match else None
        match = re.match(r"(\d+) Draw", line)
        if match and active_ps:
            draw = int(match[1])
            executed[active_ps].add(draw)
            if active_ps == "72a656dfd52149ad":
                armed = True
            if active_ps == "23d27700572e0c4d":
                output_gate.append({"draw": draw, "dither_would_run": armed})
                armed = False
    timeline = []
    for path in sorted(args.capture.glob("*.jpg")):
        match = re.match(r"(\d+)-.*-ps=([0-9a-f]{16})\.jpg$", path.name)
        if not match:
            continue
        draw, hash_value = int(match[1]), match[2]
        rendered[hash_value].add(draw)
        if records.get(hash_value, {}).get("ResourceMagic") == "ShCd":
            timeline.append({"draw": draw, "hash": hash_value, "image": path.name})
    rows = []
    for shader in package["shaders"]:
        hash_value = shader["hash"]
        row = {"hash": hash_value, "effect": shader["effect"], "bound_in_frame": hash_value in bound,
               "draws_in_log": sorted(executed[hash_value]),
               "draws_with_output": sorted(rendered[hash_value])}
        rows.append(row)
        print(f"{hash_value} {shader['effect']}: draws={row['draws_in_log']}, images={row['draws_with_output']}")
    report = {"client_build": manifest["ClientBuild"], "capture": str(args.capture.resolve()),
              "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
              "note": "Observed original shader hashes identify stages; this is not a GPU timing or all-settings correctness test.",
              "preview_shaders": rows, "standalone_shader_timeline": timeline,
              "predicted_output_dither_gate": output_gate}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
