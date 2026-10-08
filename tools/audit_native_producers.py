"""Bounded historical input-writer audit; binding history is not pixel provenance."""
import argparse
import json
import re
from pathlib import Path
from audit_light_capture import log_blocks
from manage_preview import digest, encoded

TARGETS = {"415a922293923fa4": (10, 5), "980154264a89fba1": (4,)}


def entries(block):
    return {int(m[1]): m[2].lower() for line in block[1:]
            if (m := re.match(r"\s+(\d+):.*resource=(0x[0-9a-fA-F]+)", line))}


def brief(value):
    if value is None:
        return None
    return {k: value[k] for k in ("call", "draw", "line", "ps", "vs", "cs", "output_slot", "uav_slot") if k in value}


def audit(raw):
    shaders = {}; srvs = {}; rt = {}; uavs = {}; writes = {}; counts = {}; rows = []; gaps = []
    for line_number, block in log_blocks(raw):
        first = block[0]
        match = re.match(r"^(\d+) (\w+)\(", first)
        draw, call = int(match[1]), match[2]
        if call in ("ClearState", "ExecuteCommandList", "SwapDeviceContextState"):
            shaders = {}; srvs = {}; rt = {}; uavs = {}
            if call != "ClearState":
                writes = {}; counts = {}; gaps.append({"line": line_number, "call": call})
        elif call in ("PSSetShader", "VSSetShader", "CSSetShader"):
            found = re.search(r"\bhash=([0-9a-fA-F]{16})", first)
            shaders[call[:2]] = found[1].lower() if found else None
        elif call in ("PSSetShaderResources", "CSSetUnorderedAccessViews"):
            start, count = map(int, re.search(r"StartSlot:(\d+), Num(?:Views|UAVs):(\d+)", first).groups())
            state = srvs if call.startswith("PS") else uavs
            for slot in range(start, start + count):
                state.pop(slot, None)
            state.update({s: r for s, r in entries(block).items() if start <= s < start + count})
            if call.startswith("PS"):
                srvs = {s: r for s, r in srvs.items() if r not in rt.values() and r not in uavs.values()}
        elif call == "OMSetRenderTargets":
            rt = entries(block)
            srvs = {s: r for s, r in srvs.items() if r not in rt.values()}
        elif call.startswith("Draw"):
            ps = shaders.get("PS")
            if ps in TARGETS:
                rows.append({"draw": draw, "consumer_ps": ps, "inputs": {slot: {
                    "resource": srvs.get(slot), "last_observed_write": writes.get(srvs.get(slot)),
                    "observed_draw_writes_since_reset": counts.get(srvs.get(slot), 0)} for slot in TARGETS[ps]}})
            node = {"call": call, "draw": draw, "line": line_number, "ps": ps, "vs": shaders.get("VS"),
                    "input_bindings": {s: {"resource": r, "writer_reference": brief(writes.get(r))} for s, r in srvs.items()}}
            for slot, resource in rt.items():
                writes[resource] = {**node, "output_slot": slot}
                counts[resource] = counts.get(resource, 0) + 1
        elif call.startswith("Dispatch"):
            for slot, resource in uavs.items():
                writes[resource] = {"call": call, "draw": draw, "line": line_number, "cs": shaders.get("CS"), "uav_slot": slot}
                counts[resource] = 0
        elif call in ("CopyResource", "CopySubresourceRegion", "CopySubresourceRegion1", "ResolveSubresource"):
            dest = re.search(r"pDstResource:(0x[0-9a-fA-F]+)", first)
            source = re.search(r"pSrcResource:(0x[0-9a-fA-F]+)", first)
            if dest and source:
                src, dst = source[1].lower(), dest[1].lower()
                writes[dst] = {"call": call, "draw": draw, "line": line_number, "source": src,
                               "source_writer_at_copy": brief(writes.get(src))}
                counts[dst] = 0
            else:
                writes = {}; counts = {}; gaps.append({"line": line_number, "call": call, "reason": "unparsed copy destination"})
        elif call in ("ClearRenderTargetView", "ClearUnorderedAccessViewUint", "ClearUnorderedAccessViewFloat"):
            found = re.search(r"resource=(0x[0-9a-fA-F]+)", "\n".join(block))
            if found:
                resource = found[1].lower()
                writes[resource] = {"call": call, "draw": draw, "line": line_number}; counts[resource] = 0
        elif call in ("Map", "UpdateSubresource", "UpdateSubresource1"):
            if call == "Map" and "MapType:1," in first:
                continue
            found = re.search(r"p(?:Resource|DstResource):(0x[0-9a-fA-F]+)", first)
            if found:
                resource = found[1].lower(); writes[resource] = {"call": call, "draw": draw, "line": line_number}; counts[resource] = 0
        elif call == "OMSetRenderTargetsAndUnorderedAccessViews":
            rt = {}; writes = {}; counts = {}; gaps.append({"line": line_number, "call": call})
    return {"source_kind": "historical_3dmigoto_log", "source_sha256": digest(raw), "targets": rows, "gaps": gaps,
            "current_live_producer_verified": False, "pixel_provenance_verified": False,
            "limits": ["Pointers only associate objects within this old capture; destruction/reuse not established",
                       "Draw/dispatch and output binding do not prove successful writes or RGB/stencil coverage",
                       "Source copies retain one immutable writer reference; no full transitive graph is claimed",
                       "Shader input bindings may be unused; static bytecode review is required"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.log.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(encoded(result))
    print(f"Recorded {len(result['targets'])} historical target draws; pixel provenance remains unverified")
