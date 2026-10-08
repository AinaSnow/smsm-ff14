"""Read-only historical 3DMigoto log audit. Draw count is NOT per-pixel coverage."""
import argparse
import json
import re
from pathlib import Path
from build_single_light import TARGETS
from manage_preview import digest, encoded


def audit(raw):
    blocks=[]
    for number,line in enumerate(raw.decode("utf-8",errors="replace").splitlines(),1):
        if re.match(r"^\d+ \w+\(",line):
            blocks.append([number,[line]])
        elif blocks:
            blocks[-1][1].append(line)
    shader=None; state={}; draws=[]; uncertainty=[]
    fields={"OMSetBlendState":"blend_binding", "OMSetDepthStencilState":"depth_stencil_binding",
            "OMSetRenderTargets":"render_targets", "OMSetRenderTargetsAndUnorderedAccessViews":"render_targets",
            "RSSetViewports":"viewport_binding", "RSSetScissorRects":"scissor_binding"}
    for number,lines in blocks:
        line=lines[0]; match=re.match(r"^(\d+) (\w+)\(",line)
        index,call=int(match[1]),match[2]
        if call in ("ClearState","ExecuteCommandList","SwapDeviceContextState"):
            # A command list may restore its context, but this text format does
            # not replay that state. Invalidate it instead of guessing bindings.
            shader=None; state={}
            uncertainty.append(dict(line=number,call=call))
        elif call=="PSSetShader":
            value=re.search(r"\bhash=([0-9a-fA-F]{16})\b",line)
            shader=value[1].lower() if value else None
        elif call in fields:
            state[fields[call]]=dict(line=number,text="\n".join(lines))
        elif call.startswith("Draw") and shader in TARGETS:
            draws.append(dict(draw_index=index,line=number,shader=shader,call=line,state=dict(state)))
    return dict(draws=draws,draw_counts={target:sum(d["shader"]==target for d in draws) for target in TARGETS},
                context_invalidations=uncertainty,per_pixel_injection_count_verified=False,
                blend_descriptor_verified=False,game_light_execution_verified=False,
                limits=["Historical capture predates the single-light prototype",
                        "Pointer bindings do not disclose blend factors or depth/stencil descriptors",
                        "Draws do not prove overlapping pixels, material coverage, or current game settings",
                        "No opaque/transparent classification inferred from pass ordering"])


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("log",type=Path); p.add_argument("output",type=Path)
    a=p.parse_args(); raw=a.log.read_bytes(); report=audit(raw)
    report.update(source=str(a.log.resolve()),source_sha256=digest(raw))
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/"report.json").write_bytes(encoded(report))
    print(json.dumps({"output":str(a.output),"draw_counts":report["draw_counts"],
                      "per_pixel_count_verified":False}))
