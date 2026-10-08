"""Read-only mesh-material draw/VS audit; no per-pixel coverage inference."""
import argparse
import re
from pathlib import Path
from audit_light_capture import log_blocks
from manage_preview import ROOT, digest, encoded
from patch_material_light import load_original
from patch_forward_light import TARGET
from shader_compile import Compiler


def draws(raw):
    state={}; rows=[]
    for line_number,block in log_blocks(raw):
        line=block[0]; m=re.match(r'^(\d+) (\w+)\(',line);index,call=int(m[1]),m[2]
        if call in ('ClearState','ExecuteCommandList','SwapDeviceContextState'): state={}
        elif call in ('VSSetShader','PSSetShader'):
            h=re.search(r'\bhash=([0-9a-fA-F]{16})\b',line);state[call]=h[1].lower() if h else None
        elif call in ('OMSetBlendState','OMSetDepthStencilState','IASetInputLayout'):
            state[call]=line
        elif call.startswith('Draw') and state.get('PSSetShader')==TARGET:
            rows.append(dict(draw=index,line=line_number,call=line,state=dict(state)))
    return rows


def run(log,extraction,output):
    output.mkdir(parents=True,exist_ok=False);raw=log.read_bytes();rows=draws(raw)
    compiler=Compiler(ROOT/'d3dcompiler_46.dll'); shaders=[]
    for target in sorted({row['state'].get('VSSetShader') for row in rows}-{None}):
        data=load_original(extraction,target,'vs_5_0');asm=compiler.disassemble(data)
        (output/(target+'-vs.asm')).write_text(asm)
        # Retain exact producer/output operations for manual semantic review;
        # this is not automated proof that bone matrices have the correct space.
        operations=[s for s in asm.splitlines() if re.search(r'\bo[036]\.',s) and not s.startswith('//')]
        shaders.append(dict(hash=target,sha256=digest(data),output_operations=operations))
    (output/'report.json').write_bytes(encoded(dict(log_sha256=digest(raw),target=TARGET,draws=rows,vertex_shaders=shaders,
        per_pixel_coverage_verified=False,blend_descriptors_verified=False,
        limits=['Historical shader binding, not proof of which named character/material was drawn',
                'Vertex output trace does not replay skeletons, morphing, vertex/index buffers or stencil',
                'Repeated draws do not establish overlapping pixels or repeated lamp accumulation'])))
    print(f'Audited {len(rows)} historical draws, {len(shaders)} verified vertex shaders')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('log',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--extraction',type=Path,default=ROOT/'artifacts/client-2026.09.15')
    a=p.parse_args();run(a.log,a.extraction,a.output)
