"""Render the CURRENT game's near/far DoF composite with controlled layer inputs.

This is a first composition/energy audit, not a complete bokeh implementation.
No game package is changed and the 48-tap experiment is retained separately.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from manage_preview import ROOT, digest, encoded
from offline_render import render

TARGET="4b85fee6dc176fb3"


def smooth(x):
    x=np.clip(x,0,1); return x*x*(3-2*x)


def reference(scene, near1, near2, far1, far2, near_alpha, far_alpha, near_scale, far_scale, exposure=1):
    far_weight=far_alpha*far_scale; near_weight=near_alpha*near_scale
    color=(scene*exposure)**2
    color=color+(far1-color)*smooth(2*far_weight)
    color=color+(far2-color)*smooth(2*far_weight-1)
    relative=np.clip(near_weight/np.maximum(far_weight+near_weight,.0001),0,1)
    color=color+(near1-color)*smooth(relative*np.clip(near_weight*2,0,1))
    color=color+(near2-color)*smooth(near_weight*2-1)
    return np.sqrt(color)/exposure


def run(extraction, output):
    output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((extraction/"manifest.json").read_text())
    if manifest["ClientBuild"]!="2026.09.15.0000.0000": raise ValueError("Unreviewed build")
    record=next(s for s in manifest["Shaders"] if s["Hash"]==TARGET)
    shader=(extraction/record["File"]).resolve()
    if not shader.is_relative_to(extraction.resolve()) or digest(shader.read_bytes())!=record["Sha256"]: raise ValueError("Original integrity mismatch")
    width,height=32,16; checks=[]
    values=[(float(n),float(f)) for n in (0,.25,.5,.75,1) for f in (0,.25,.5,.75,1)]
    values += [(0,float(f)) for f in np.linspace(0,1,41)]
    animation=np.zeros((len(values),2,4),np.float32)
    for i,(n,f) in enumerate(values): animation[i,1,2:4]=(n,f)
    y,x=np.mgrid[:height,:width]
    for case in ("uniform-exposure","colored-layers","near-coverage-edge","black"):
        exposure=2 if case=="uniform-exposure" else 1
        base=np.broadcast_to([.2,.35,.6],(height,width,3)).copy()
        colors=[base.copy() for _ in range(4)]
        near_alpha=np.ones((height,width)); far_alpha=np.ones_like(near_alpha)
        if case in ("colored-layers","near-coverage-edge"):
            for c,v in zip(colors,([.8,.1,.1],[.4,.05,.05],[.1,.7,.1],[.1,.1,.7])): c[:]=v
        if case=="near-coverage-edge": near_alpha[:,width//2:]=0
        if case=="black":
            base[:]=0
            for c in colors: c[:]=0
        textures={}
        for slot,c in enumerate([base,*colors]):
            t=np.ones((height,width,4),np.float32)
            t[...,:3]=c if slot==0 else (c*exposure)**2
            textures[slot]=t
        textures[0][...,3]=far_alpha; textures[2][...,3]=near_alpha
        constants={0:np.array([[1/exposure,exposure,0,0]]),
                   1:np.array([[1,1,1-.5/width,1-.5/height],[1,1,1-.5/width,1-.5/height]])}
        actual=render(shader,output/case,width,height,textures,constants,animation=(2,animation))[:,0]
        expected=np.stack([reference(base,*[(c*exposure)**2 for c in colors],near_alpha[...,None],far_alpha[...,None],n,f,exposure)
                           for n,f in values])
        error=float(np.max(np.abs(actual[...,:3]-expected)))
        if not np.isfinite(actual).all() or error>3e-6 or np.any(actual[...,3]!=0): raise AssertionError(f"{case}: {error}")
        row={"case":case,"frames":len(values),"max_abs_error":error,"finite":True,"alpha_zero":True}
        if case=="uniform-exposure":
            row["constant_color_error"]=float(np.max(np.abs(actual[...,:3]-base)))
            if row["constant_color_error"]>3e-6: raise AssertionError("Energy drift")
        if case=="near-coverage-edge":
            # With identical far weight and zero near coverage, changing near
            # scale must not introduce near colour on the unmasked half.
            row["zero_near_coverage_leak"]=float(np.max(np.abs(actual[0,:,width//2:,:3]-actual[20,:,width//2:,:3])))
            if row["zero_near_coverage_leak"]>3e-6: raise AssertionError("Near coverage leak")
        checks.append(row); print("PASS DoF composite",case,flush=True)
    report={"target":TARGET,"original_sha256":record["Sha256"],"backend":"D3D11 WARP actual draw/readback",
            "checks":checks,"passed":True,"frames_rendered":len(values)*len(checks),
            "scope":"Two-level near/far composition, zero coverage, exposure and focus-weight transition; synthetic layers",
            "not_yet_tested":["CoC generation from game depth/focus", "Aperture kernel and blur passes", "Full-pipeline foreground leakage", "Real GPU time", "Game capture parity"]}
    (output/"report.json").write_bytes(encoded(report)); print(output/"report.json")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("output",type=Path)
    p.add_argument("--extraction",type=Path,default=ROOT/"artifacts/client-2026.09.15")
    a=p.parse_args(); run(a.extraction,a.output)
