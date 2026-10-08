"""Verify official ReShade callback wiring in an isolated hardware host with zero vertices."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
from build_native_diagnostic import ROOT, compile_cpp


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--setup", type=Path, required=True)
    p.add_argument("--extraction", type=Path, default=ROOT / "artifacts/client-2026.09.15")
    args = p.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise ValueError("Use a new immutable host directory")
    root.mkdir(parents=True)
    manifest = json.loads((args.package / "SMSM-native-package.json").read_text())
    addon = args.package / "SMSM.NativeLighting.addon64"
    assert hashlib.sha256(addon.read_bytes()).hexdigest() == manifest["files"][addon.name]
    shutil.copy2(addon, root / addon.name)
    with zipfile.ZipFile(args.setup) as archive:
        runtime = archive.read("ReShade64.dll")
    (root / "d3d11.dll").write_bytes(runtime)
    (root / "ReShade.ini").write_text("[GENERAL]\nNoDebugInfo=1\nNoReloadOnInit=1\n[OVERLAY]\nShowClock=0\nShowFPS=0\nShowFrameTime=0\n", encoding="utf-8")
    exe = root / "test_reshade_host.exe"
    compile_cpp(ROOT / "addons/native_lighting/test_reshade_host.cpp", exe)
    subprocess.run([str(exe), str(root), str(args.extraction.resolve())], cwd=root, check=True, timeout=90)
    captures = sorted(root.glob("SMSM-native-captures/*/manifest.json"))
    assert len(captures) == 2, "Plugin did not capture exactly two manually requested frames; inspect ReShade.log"
    hashes = []
    for path in captures:
        report = json.loads(path.read_text())
        assert report["status"] == "snapshots_complete", report
        assert {d["target"] for d in report["draws"]} == {"415a922293923fa4", "980154264a89fba1"}
        assert len(report["draws"]) == 2
        for draw in report["draws"]:
            assert draw["viewports"] == [[3, 2, 57, 27, 0.10000000149, 0.899999976158]]
            for item in draw["resources"]:
                if item["status"] == "captured":
                    raw = (path.parent / item["file"]).read_bytes()
                    assert len(raw) == item["selected_bytes"]
                    assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        hashes.append(report["draws"][0]["resources"][0]["sha256"])
    assert hashes[0] != hashes[1], "Old capture mixed into new frame"
    log = (root / "ReShade.log").read_text(encoding="utf-8", errors="replace")
    assert "SMSM Native Lighting Diagnostic" in log
    result = {"source_kind": "synthetic_host", "actual_reshade_runtime": True, "driver": "hardware", "vertices": 0, "game_verified": False,
              "runtime_sha256": hashlib.sha256(runtime).hexdigest(),
              "setup_sha256": hashlib.sha256(args.setup.read_bytes()).hexdigest(),
              "addon_sha256": manifest["files"][addon.name], "captures": [str(p.relative_to(root)) for p in captures]}
    (root / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
