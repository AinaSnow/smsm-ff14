"""Compare legacy embedded assembly with extracted client shaders; candidates need review."""
import argparse
from collections import defaultdict
import difflib
import json
from pathlib import Path
import re
from shader_compile import Compiler


def instructions(text):
    match = re.search(r"^ps_[45]_\d\s*$", text, re.M)
    if not match:
        return []
    result = []
    for line in text[match.end():].splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("~") or line == "*/":
            break
        result.append(re.sub(r"\s+", " ", line).lower())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("legacy", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.capture / "manifest.json").read_text())
    compiler = Compiler()
    asm_dir = args.capture / "asm"
    asm_dir.mkdir(exist_ok=True)
    legacy = {}
    for path in sorted(args.legacy.glob("*_replace.txt")):
        text = path.read_text()
        legacy[path.name[:16]] = {"source": path.name, "description": text.splitlines()[0].lstrip("/ "),
                                  "symbols": set(re.findall(r"^cbuffer (\w+)", text, re.M)),
                                  "instructions": instructions(text)}
    by_hash = {s["Hash"]: s for s in manifest["Shaders"] if s["Profile"].startswith("ps_")}
    candidates = defaultdict(list)
    for hash_value, shader in by_hash.items():
        data = (args.capture / shader["File"]).read_bytes()
        relevant = [old_hash for old_hash, old in legacy.items()
                    if shader["ResourceMagic"] == "ShCd" or old_hash == hash_value
                    or any(symbol.encode() + b"\0" in data for symbol in old["symbols"])]
        if not relevant and shader["ResourceMagic"] != "ShCd":
            continue
        asm_path = asm_dir / f"{hash_value}-ps.asm"
        asm = asm_path.read_text(encoding="utf-8") if asm_path.exists() else compiler.disassemble(data)
        if not asm_path.exists():
            asm_path.write_text(asm, encoding="utf-8")
        code = instructions(asm)
        for old_hash in relevant:
            old = legacy[old_hash]
            if not old["instructions"]:
                continue
            similarity = difflib.SequenceMatcher(None, old["instructions"], code, autojunk=False).ratio()
            candidates[old_hash].append({"hash": hash_value, "score": round(similarity, 5),
                                         "exact_instruction_match": old["instructions"] == code and bool(code),
                                         "resource": shader["ResourceHash"], "kind": shader["ResourceMagic"]})
    report = {"client_build": manifest["ClientBuild"], "runtime_verified": False, "shaders": []}
    for hash_value, old in legacy.items():
        ranked = sorted(candidates[hash_value], key=lambda c: c["score"], reverse=True)[:5]
        row = {"old_hash": hash_value, "description": old["description"],
               "hash_present": hash_value in by_hash, "candidates": ranked}
        report["shaders"].append(row)
        print(hash_value, "PRESENT" if row["hash_present"] else "MISSING", ranked[:2])
    (args.capture / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
