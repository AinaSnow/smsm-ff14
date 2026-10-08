"""Select visibility settings on three scenes, then report held-out geometry/motion.

No settings are written into game packages. Step counts are workload bounds,
not GPU timing. Final material motion is measured by actual native PS draws.
"""
import argparse
import json
import shutil
from pathlib import Path
import numpy as np
from manage_preview import ROOT,encoded,digest
from offline_render import render
from shader_compile import Compiler
from patch_material_light import load_original
from validate_light_visibility import scene,exact_shadow
from validate_material_light import material_inputs
from validate_material_visibility import visibility_constants
from validate_single_light import cpu_light

PRESETS={
    'baseline':(.025,.35,96),
    'fine-bias':(.005,.35,96),
    'fine-128':(.005,.35,128),
    'thin-128':(.005,.12,128),
    'balanced-128':(.0125,.2,128),
    'balanced-64':(.0125,.35,64),
}


def run(output,extraction):
    output.mkdir(parents=True,exist_ok=False);compiler=Compiler(ROOT/'d3dcompiler_46.dll');shaders={}
    for filename in ('material_light.hlsl','material_visibility.hlsl'):
        shutil.copy2(ROOT/'tools/patches'/filename,output/filename)
    for audit in (0,1):
        source=output/f'pass-{audit}.hlsl'
        source.write_text(f'#define MATERIAL_PLANE_REFINE 1\n#define MATERIAL_VISIBILITY_AUDIT {audit}\n#include "material_visibility.hlsl"\n')
        binary,warnings=compiler.compile(source)
        if warnings:raise ValueError(warnings)
        shaders[audit]=output/f'pass-{audit}.bin';shaders[audit].write_bytes(binary)
    original=output/'original.bin';original.write_bytes(load_original(extraction));rows=[];checks=[]
    def settings(f,preset,lamp):
        bias,thickness,steps=PRESETS[preset];inputs=material_inputs(f)
        inputs['constants'][12]=visibility_constants(f,bias=bias,thickness=thickness,steps=steps)
        inputs['constants'][13]=[[*lamp,9],[1,1,1,18]];return inputs
    def validate(name,pixels):
        if not np.isfinite(pixels).all():raise AssertionError(name+' nonfinite')
        checks.append(dict(name=name,passed=True))
    training=[('flat',{}),('tilted',dict(angle=25)),('thin',dict(half_size=(.08,.65)))]
    holdout=[('grazing',dict(angle=65)),('high-resolution',dict(width=256,height=160)),
             ('jitter',dict(jitter=(.013,-.021))),('reverse-z',dict(reverse=True)),
             ('right-handed',dict(right_handed=True)),('viewport',dict(viewport=(9,5,108,68)))]
    selected=None
    for partition,configs in [('training',training),('holdout',holdout)]:
        for label,config in configs:
            f=scene(**config);lamp=[-.65,.5,1.5*f['sign']];truth=exact_shadow(f,lamp);receiver=~f['plate']&f['mask']
            for preset in PRESETS:
                inputs=settings(f,preset,lamp)
                image=render(shaders[1],output/f'{partition}-{label}-{preset}',f['width'],f['height'],**inputs,viewport=f['viewport'])[0,0]
                validate(partition+' '+label+' '+preset,image)
                shadow=image[...,0]<.5
                fp=int((shadow&~truth&receiver).sum());fn=int((~shadow&truth&receiver).sum())
                rows.append(dict(partition=partition,scene=label,preset=preset,false_shadow=fp,missed_shadow=fn,
                    errors=fp+fn,receiver_pixels=int(receiver.sum()),unsupported_pixels=int(((image[...,1]==0)&receiver).sum())))
        if partition=='training':
            # Freeze selection before rendering any held-out input. Ties prefer
            # fewer steps, then existing order; no retrospective selection.
            selected=min(PRESETS,key=lambda p:(sum(r['errors'] for r in rows if r['preset']==p),PRESETS[p][2]))
            (output/'selection.json').write_bytes(encoded(dict(selected=selected,training_rows=rows.copy(),
                criterion='minimum sum of full receiver errors on flat/tilted/thin; ties prefer fewer steps')))
            print('Training selected',selected,flush=True)
    temporal={};f=scene();receiver=~f['plate']
    for sweep,xvalues in [('prior-motion',np.linspace(-.8,-.5,13)),('held-out-motion',np.linspace(.2,.6,13))]:
        truth=[];params=[];ideal=[];inputs=material_inputs(f)
        for index,x in enumerate(xvalues):
            lamp=[x,.5,1.5];params.append([[*lamp,9],[1,1,1,18]]);truth.append(exact_shadow(f,lamp))
            texture=inputs['textures'][3].copy();texture[...,:3]+=cpu_light(f,lamp,intensity=18,radius=9)*(~truth[-1])[...,None]
            data=dict(inputs);data['textures']=dict(inputs['textures']);data['textures'][3]=texture
            ideal.append(render(original,output/f'{sweep}-reference-{index}',f['width'],f['height'],**data)[0,0])
        ideal=np.stack(ideal);truth=np.array(truth,dtype=np.float32)
        temporal[sweep]={}
        for preset in dict.fromkeys(('baseline',selected)):
            controls=settings(f,preset,params[0][0][:3]);del controls['constants'][13]
            masks=render(shaders[1],output/f'{sweep}-{preset}-audit',f['width'],f['height'],**controls,animation=(13,params))[:,0]
            textures=render(shaders[0],output/f'{sweep}-{preset}-diffuse',f['width'],f['height'],**controls,animation=(13,params))[:,0]
            finals=[]
            for index,texture in enumerate(textures):
                data=dict(controls);data['textures']=dict(controls['textures']);data['textures'][3]=texture
                finals.append(render(original,output/f'{sweep}-{preset}-material-{index}',f['width'],f['height'],**data)[0,0])
            finals=np.stack(finals);validate(sweep+' '+preset+' material',finals)
            shadow=1-masks[...,0]
            temporal[sweep][preset]=dict(visibility_mae=float(np.abs(shadow-truth)[:,receiver].mean()),
                visibility_change_error=float(np.abs(np.diff(shadow,axis=0)-np.diff(truth,axis=0))[:,receiver].mean()),
                final_rgb_mae=float(np.abs(finals-ideal)[:,receiver,:3].mean()),
                final_rgb_change_error=float(np.abs(np.diff(finals,axis=0)-np.diff(ideal,axis=0))[:,receiver,:3].mean()))
    totals={part:{p:sum(r['errors'] for r in rows if r['partition']==part and r['preset']==p) for p in PRESETS}
            for part in ('training','holdout')}
    regressions=[r['scene'] for r in rows if r['partition']=='holdout' and r['preset']==selected and
        r['errors']>next(b['errors'] for b in rows if b['scene']==r['scene'] and b['preset']=='baseline')]
    report=dict(selected=selected,presets={p:dict(bias=v[0],assumed_thickness=v[1],max_steps=v[2]) for p,v in PRESETS.items()},
        selection_uses_holdout=False,checks=checks,check_count=len(checks),all_passed=True,rows=rows,totals=totals,
        holdout_regressions=regressions,temporal=temporal,
        heldout_spatial_improved=totals['holdout'][selected]<totals['holdout']['baseline'],
        all_motion_metrics_nonregressing=all(temporal[s][selected][metric]<=temporal[s]['baseline'][metric]
            for s in temporal for metric in temporal[s]['baseline']),
        eligible_for_default=False,game_package_created=False,game_runtime_verified=False,performance_verified=False,
        source_sha256={n:digest((output/n).read_bytes()) for n in ('material_light.hlsl','material_visibility.hlsl')},
        limits=['Fixed synthetic geometry family; held-out views do not establish real-world generalization',
                'No temporal filter or stabilizer; hard shadow rasterization still aliases',
                'Step counts bound iterations but do not measure GPU cost',
                'No automatic parameter promotion, package modification or game installation'])
    (output/'report.json').write_bytes(encoded(report))
    print(json.dumps(dict(selected=selected,totals=totals,holdout_regressions=regressions,temporal=temporal),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--extraction',type=Path,default=ROOT/'artifacts/client-2026.09.15')
    a=p.parse_args();run(a.output,a.extraction)
