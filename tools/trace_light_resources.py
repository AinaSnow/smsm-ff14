"""Trace historical light outputs to PS consumers by resource identity and DXBC reads.

This is a potential dependency graph, NOT pixel provenance or blend reconstruction.
"""
import argparse
import json
import re
from pathlib import Path
from audit_light_capture import log_blocks
from build_single_light import TARGETS
from manage_preview import ROOT, encoded, digest
from shader_compile import Compiler


def trace(raw, shader_info):
    ps=None; srvs={}; outputs={}; ancestors={}; seeds={}; edges=[]; gaps=[]; direct=[]
    for number,lines in log_blocks(raw):
        line=lines[0]; m=re.match(r"^(\d+) (\w+)\(",line); index,call=int(m[1]),m[2]
        if call in ("ClearState","ExecuteCommandList","SwapDeviceContextState"):
            ps=None; srvs={}; outputs={}
            gaps.append(dict(line=number,call=call))
            if call!="ClearState": ancestors={}
        elif call=="PSSetShader":
            h=re.search(r"\bhash=([0-9a-fA-F]{16})\b",line); ps=h[1].lower() if h else None
        elif call=="PSSetShaderResources":
            start,count=map(int,re.search(r"StartSlot:(\d+), NumViews:(\d+)",line).groups())
            # Log omits null entries. Each setter replaces the specified range;
            # absent slots must NOT inherit previous bindings.
            for slot in range(start,start+count): srvs.pop(slot,None)
            for item in lines[1:]:
                entry=re.match(r"\s+(\d+):.*resource=(0x[0-9a-fA-F]+)",item)
                if entry:
                    slot,resource=int(entry[1]),entry[2].lower()
                    if resource not in outputs.values(): srvs[slot]=resource
        elif call=="OMSetRenderTargets":
            outputs={}
            for item in lines[1:]:
                entry=re.match(r"\s+(\d+):.*resource=(0x[0-9a-fA-F]+)",item)
                if entry: outputs[int(entry[1])]=entry[2].lower()
            srvs={slot:r for slot,r in srvs.items() if r not in outputs.values()}
        elif call=="ClearRenderTargetView":
            resource=re.search(r"\bresource=(0x[0-9a-fA-F]+)","\n".join(lines))
            if resource: ancestors.pop(resource[1].lower(),None)
        elif call.startswith("Draw") and ps:
            info=shader_info(ps)
            reads={slot:r for slot,r in srvs.items() if slot in info["read_slots"]}
            inherited=set()
            for slot,resource in reads.items():
                same_object=[s for s,v in seeds.items() if v["resource"]==resource]
                if same_object:
                    direct.append(dict(draw=index,line=number,shader=ps,slot=slot,resource=resource,
                                       roots=same_object,outputs=dict(outputs),shader_info=info,
                                       evidence="same resource object read later; intervening contents not proven"))
                roots=ancestors.get(resource,set()); inherited.update(roots)
                if roots:
                    edges.append(dict(draw=index,line=number,shader=ps,slot=slot,resource=resource,
                                      roots=sorted(roots),outputs=dict(outputs),shader_info=info))
            for slot,resource in outputs.items():
                if ps in TARGETS:
                    seed=f"{index}:{ps}:o{slot}"
                    seeds[seed]=dict(draw=index,shader=ps,slot=slot,resource=resource,line=number)
                    ancestors.setdefault(resource,set()).add(seed)
                # Unknown OM blend/stencil means a later write may retain old
                # contents. Union is an upper bound, not a confirmed contribution.
                if inherited: ancestors.setdefault(resource,set()).update(inherited)
        elif call in ("CopyResource","CopySubresourceRegion","ResolveSubresource","Dispatch","DispatchIndirect",
                      "OMSetRenderTargetsAndUnorderedAccessViews"):
            gaps.append(dict(line=number,call=call,reason="not modeled; graph is partial"))
            # Stop propagation across unmodeled GPU operations. Future light
            # seed writes can start fresh paths; never silently bridge a gap.
            ancestors={}
            if call=="OMSetRenderTargetsAndUnorderedAccessViews": outputs={}; srvs={}
    destinations={}
    for edge in direct:
        for resource in edge["outputs"].values():
            destinations.setdefault(resource,set()).update(seeds[s]["shader"] for s in edge["roots"])
    shared={r:sorted(s) for r,s in destinations.items() if len(s)>1}
    return dict(seeds=seeds,direct_consumers=direct,potential_edges=edges,gaps=gaps,shared_consumer_outputs=shared,
                per_pixel_energy_verified=False,complete_frame_graph=False,
                limits=["PS texture reads are static possible reads; runtime branches and channel weights are unknown",
                        "Unknown blend/stencil retains a union of possible ancestry, not exact pixel contribution",
                        "Copies, compute and unmodeled context operations break ancestry",
                        "Resource pointers distinguish same-hash textures only within this historical capture"])


def run(log, extraction, output):
    output.mkdir(parents=True,exist_ok=False)
    raw=log.read_bytes(); manifest=json.loads((extraction/"manifest.json").read_text())
    records={r["Hash"]:r for r in manifest["Shaders"] if r["Profile"]=="ps_5_0"}
    compiler=Compiler(ROOT/"d3dcompiler_46.dll"); cache={}
    def shader_info(shader):
        if shader in cache: return cache[shader]
        record=records.get(shader)
        if not record: info=dict(read_slots=[],verified=False,reason="missing extraction")
        else:
            path=(extraction/record["File"]).resolve(strict=True)
            if not path.is_relative_to(extraction.resolve()): raise ValueError("Extraction path escapes root")
            binary=path.read_bytes()
            if digest(binary)!=record["Sha256"]: raise ValueError("Shader integrity mismatch")
            asm=compiler.disassemble(binary)
            body="\n".join(s for s in asm.splitlines() if not s.startswith("//") and not s.startswith("dcl_"))
            slots=sorted({int(s) for s in re.findall(r"\bt(\d+)\b",body)})
            names={int(slot):name for name,slot in re.findall(r"^//\s+(\S+)\s+texture\s+.*?\s+(\d+)\s+1\s*$",asm,re.M)}
            info=dict(read_slots=slots,resource_names=names,verified=True,original_sha256=record["Sha256"])
            # Keep only local disassembly; no game bytecode is committed.
            (output/(shader+".asm")).write_text(asm)
        cache[shader]=info; return info
    report=trace(raw,shader_info)
    report.update(source=str(log.resolve()),source_sha256=digest(raw),client_build=manifest["ClientBuild"])
    (output/"report.json").write_bytes(encoded(report))
    summary={s:{"source":v,"consumer_draws":sorted({e["draw"] for e in report["direct_consumers"] if s in e["roots"] and e["resource"]==v["resource"]})}
             for s,v in report["seeds"].items()}
    (output/"summary.json").write_bytes(encoded(summary))
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("log",type=Path); p.add_argument("output",type=Path)
    p.add_argument("--extraction",type=Path,default=ROOT/"artifacts/client-2026.09.15")
    a=p.parse_args(); run(a.log,a.extraction,a.output)
