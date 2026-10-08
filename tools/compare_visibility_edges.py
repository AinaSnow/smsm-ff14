"""Measure default and refined screen-space visibility against held-out geometry/motion."""
import argparse
import json
import shutil
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from manage_preview import ROOT, encoded, digest
from shader_compile import Compiler
from offline_render import render
from validate_light_visibility import scene, exact_shadow


def run(output):
    output.mkdir(parents=True,exist_ok=False)
    for name in ("single_light.hlsl","single_light_visibility.hlsl"):
        shutil.copy2(ROOT/"tools/patches"/name,output/name)
    compiler=Compiler(ROOT/"d3dcompiler_46.dll"); shaders={}; rows=[]; images=[]
    for mode in (0,1):
        path=output/f"mode{mode}.hlsl"
        path.write_text(f'#define VISIBILITY_AUDIT 1\n#define VISIBILITY_PLANE_REFINE {mode}\n#include "single_light_visibility.hlsl"\n')
        binary,diagnostics=compiler.compile(path)
        if diagnostics: raise ValueError(diagnostics)
        shaders[mode]=output/f"mode{mode}.bin"; shaders[mode].write_bytes(binary)
    configs=[("flat",{}),("tilted",dict(angle=25)),("grazing",dict(angle=65)),
             ("thin",dict(half_size=(.08,.65))),("high-resolution",dict(width=256,height=160)),
             ("jitter",dict(jitter=(.013,-.021)))]
    for label,settings in configs:
        f=scene(**settings); lamp=[-.65,.5,1.5]
        truth=exact_shadow(f,lamp); receiver=~f["plate"]&f["mask"]
        masks=[]; errors=[]
        for mode in (0,1):
            constants=dict(f["constants"]); constants[12]=[[1,.025,.35,96]]; constants[13]=[[*lamp,9],[1,1,1,18]]
            result=render(shaders[mode],output/f"{label}-mode{mode}",f["width"],f["height"],f["textures"],constants)[0,0]
            if not np.isfinite(result).all(): raise AssertionError("Non-finite visibility")
            mask=result[...,0]<.5; masks.append(mask)
            fp=int((mask&~truth&receiver).sum()); fn=int((~mask&truth&receiver).sum())
            errors.append(fp+fn)
            rows.append(dict(scene=label,refine=bool(mode),false_shadow_pixels=fp,missed_shadow_pixels=fn,
                             total_error=fp+fn,receiver_pixels=int(receiver.sum()),
                             unsupported_receiver_pixels=int(((result[...,1]==0)&receiver).sum())))
        print(label,errors,flush=True)
        np.savez(output/(label+"-reference.npz"),shadow=truth,receiver=receiver,baseline=masks[0],refined=masks[1])
        if label in ("flat","tilted","thin"):
            tile=Image.new("RGB",(960,230),(24,27,32)); painter=ImageDraw.Draw(tile)
            for col,(name,mask) in enumerate((("Baseline",masks[0]),("Plane verification",masks[1]),("Geometry",truth))):
                rgb=np.full((*mask.shape,3),180,np.uint8); rgb[mask]=40; rgb[f["plate"]]=230
                tile.paste(Image.fromarray(rgb).resize((320,200),Image.Resampling.NEAREST),(col*320,30))
                painter.text((col*320+8,9),label+" / "+name,fill="white")
            images.append(tile)
    # Subpixel light sweep: compare changes to actual moving-shadow reference,
    # not zero motion (a real moving hard edge necessarily changes pixels).
    f=scene(); receiver=~f["plate"]; temporal={}; truth=[]
    params=[]
    for x in np.linspace(-.8,-.5,13):
        params.append([[x,.5,1.5,9],[1,1,1,18]])
        truth.append(exact_shadow(f,[x,.5,1.5]).astype(np.float32))
    truth=np.stack(truth); truth_delta=np.diff(truth,axis=0)
    for mode in (0,1):
        constants=dict(f["constants"]); constants[12]=[[1,.025,.35,96]]
        frames=render(shaders[mode],output/f"sweep-mode{mode}",f["width"],f["height"],f["textures"],constants,animation=(13,params))[:,0]
        if not np.isfinite(frames).all(): raise AssertionError("Non-finite motion output")
        shadows=1-frames[...,0]
        temporal[str(mode)]=dict(visibility_mae=float(np.abs(shadows-truth)[:,receiver].mean()),
                                change_error=float(np.abs(np.diff(shadows,axis=0)-truth_delta)[:,receiver].mean()))
    totals=[sum(r["total_error"] for r in rows if r["refine"]==bool(mode)) for mode in (0,1)]
    improved=totals[1]<totals[0]
    regressions=[label for label,_ in configs if next(r["total_error"] for r in rows if r["scene"]==label and r["refine"])>
                 next(r["total_error"] for r in rows if r["scene"]==label and not r["refine"])]
    report=dict(rows=rows,aggregate_error=totals,aggregate_improved=improved,regressed_scenes=regressions,
                temporal=temporal,game_runtime_verified=False,default_refinement_enabled=False,
                source_sha256={n:digest((output/n).read_bytes()) for n in ("single_light.hlsl","single_light_visibility.hlsl")},
                limits=["Nearest depth rasterization, finite sampling and thickness remain approximate",
                        "Normals may be shading normals, not geometric tangent normals in game",
                        "No temporal filter; motion metrics compare synthetic inputs on WARP only"])
    (output/"report.json").write_bytes(encoded(report))
    sheet=Image.new("RGB",(960,230*len(images)))
    for i,picture in enumerate(images): sheet.paste(picture,(0,230*i))
    sheet.save(output/"edge-comparison.png")
    print(json.dumps(dict(aggregate_error=totals,regressions=regressions,temporal=temporal)))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("output",type=Path)
    run(p.parse_args().output)
