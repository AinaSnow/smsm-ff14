"""Freeze exact DXBC identities and expose native ambient input references without claiming producers."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from shader_compile import Compiler

TARGETS = {
    "415a922293923fa4": ("907ce4b6cc047a429a41c537a33a44c3fff04bd74ea66ad780e9b669d72dd740", [0, 1, 2, 3], [2, 3]),
    "980154264a89fba1": ("f8face0fb530f3b884c2a6b2af289fa1a8bb3ed0e4301b03efd34afadf7c76f7", [1, 2, 3, 4, 6], [6]),
}


def audit(extraction):
    compiler = Compiler()
    rows = []
    for target, (sha, slots, ambient) in TARGETS.items():
        raw = (extraction / "dxbc" / f"{target}-ps.bin").read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("Original DXBC differs from the frozen client baseline")
        asm = compiler.disassemble(raw)
        references = [{"disassembly_line": n, "instruction": line.strip()} for n, line in enumerate(asm.splitlines(), 1)
                      if not line.strip().startswith("//") and any(re.search(rf"\bcb{s}\[", line, re.I) for s in ambient)]
        rows.append({"migoto_identifier": target, "original_dxbc_sha256": sha, "selected_ps_constants": slots,
                     "ambient_candidate_slots": ambient, "constant_references": references,
                     "static_evidence_only": True, "producer_and_spatial_semantics_verified": False})
    return {"schema": 1, "client_build": "2026.09.15.0000.0000", "targets": rows,
            "migration_decision": "pending_live_data_audit", "game_lighting_changed": False}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("extraction", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(audit(args.extraction), stream, indent=2)
        stream.write("\n")
    print(f"Audited {len(TARGETS)} original DXBC identities and ambient constant references")
