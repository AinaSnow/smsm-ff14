"""Execute actual WARP draws and independently verify captured raw bits and metadata."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from build_native_diagnostic import ROOT, compile_cpp


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise ValueError("Use a new test output directory")
    root.mkdir(parents=True)
    exe = root / "test_diagnostic.exe"
    compile_cpp(ROOT / "addons/native_lighting/test_diagnostic.cpp", exe)
    subprocess.run([str(exe), str(root / "captures")], check=True)
    reports = []
    for path in sorted((root / "captures").rglob("manifest.json")):
        report = json.loads(path.read_text())
        assert report["selected_raw_bytes"] <= report["budget_bytes"]
        assert not report["game_semantics_verified"]
        for draw in report["draws"]:
            assert draw["viewports"] == [[2, 1, 13, 7, 0.20000000298, 0.800000011921]]
            for item in draw["resources"]:
                assert item["frame"] == report["source_frame"] and item["draw"] == draw["draw"]
                if item["status"] == "captured":
                    raw = (path.parent / item["file"]).read_bytes()
                    assert len(raw) == item["selected_bytes"]
                    assert hashlib.sha256(raw).hexdigest() == item["sha256"]
                    if item["label"].startswith("ps-t"):
                        expected = struct.pack("<612f", *(i / 1024 for i in range(612)))
                        assert raw == expected, "row padding or float bits changed"
                    elif item["label"] == "om-depth":
                        assert raw == struct.pack("<153f", *([0.625] * 153))
                    elif item["label"].endswith("b0") or "-b" in item["label"]:
                        assert raw in (struct.pack("<256f", *(i + 0.25 for i in range(256))), struct.pack("<256f", *([3.5] * 256)))
        reports.append({"path": str(path.relative_to(root)), "status": report["status"], "raw_bytes": report["selected_raw_bytes"]})
    assert len(reports) == 8, reports
    normal = sorted((root / "captures/normal").rglob("manifest.json"))
    assert json.loads(normal[0].read_text())["draws"][0]["resources"][0]["sha256"] != json.loads(normal[1].read_text())["draws"][0]["resources"][0]["sha256"], "old constants reused"
    (root / "report.json").write_text(json.dumps({"source_kind": "synthetic", "actual_d3d11_draws": True,
        "game_verified": False, "captures": reports}, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(reports)} capture reports and all raw payloads")


if __name__ == "__main__":
    main()
