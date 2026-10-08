"""Package a verified immutable managed preview; never copy experimental artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from manage_preview import ROOT, RECEIPT, read_package


def package_release(package, output):
    package = package.resolve()
    manifest, _ = read_package(package)
    if manifest.get("schema_version") != 2 or manifest["profiles"][manifest["default_profile"]] != ["tone"]:
        raise ValueError("Release must be a managed package with tone-only defaults")
    entries = {"package/" + name: package / name for name in manifest["files"]}
    entries["package/" + RECEIPT] = package / RECEIPT
    for name in ("manage_preview.py", "record_validation.py", "validate_d3d11.py"):
        entries["tools/" + name] = ROOT / "tools" / name
    for name in ("MANAGEMENT.md", "RELEASE-r10.md"):
        entries["docs/" + name] = ROOT / "docs" / name
    checksums = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in entries.items()}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 8, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
        archive.writestr("SHA256SUMS.json", json.dumps(checksums, indent=2) + "\n")
    with zipfile.ZipFile(output) as archive:
        for name, sha in checksums.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != sha:
                raise ValueError(f"Archive verification failed: {name}")
    sha = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{sha}  {output.name}\n", encoding="utf-8")
    print(f"Verified {len(checksums)} files; {output.name}: {sha}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    package_release(args.package, args.output)
