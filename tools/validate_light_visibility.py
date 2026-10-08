"""Offline screen-space visibility research versus independent ray/rectangle intersections."""
import argparse
import json
import shutil
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from manage_preview import ROOT, encoded, digest
from offline_render import render
from shader_compile import Compiler
from validate_single_light import fixture


def scene(width=128,height=80,angle=0,half_size=(.45,.65),**settings):
    f=fixture(width=width,height=height,**settings)
    p=f["position"].copy(); sign=np.sign(p[0,0,2])
    theta=np.deg2rad(angle)
    normal=np.array([np.sin(theta),0,-sign*np.cos(theta)])
    tangent=np.array([np.cos(theta),0,sign*np.sin(theta)])
    center=np.array([0,0,3*sign])
    distance=np.divide(normal@center,p@normal)
    plate=p*distance[...,None]
    local=plate-center
    hit=(distance>0)&(distance<1)&(np.abs(local@tangent)<=half_size[0])&(np.abs(local[...,1])<=half_size[1])
    p[hit]=plate[hit]; f["position"]=p
    f["normal"][hit]=normal
    f["textures"][3][hit,:3]=(normal@f["constants"][1][:3,:3])*.5+.5
    projection=np.linalg.inv(f["constants"][1][14:18].astype(float))
    h=np.concatenate((p,np.ones((*p.shape[:2],1))),-1)@projection.T
    f["textures"][0][...,0]=h[...,2]/h[...,3]
    f.update(plate=hit,sign=sign,plate_center=center,plate_normal=normal,plate_tangent=tangent,half_size=half_size)
    return f


def exact_shadow(f, lamp):
    """Intersect receiver-to-lamp segments with the finite plane at z=+/-3.

    Uses known scene geometry, not the depth marcher or sampled depth texture.
    """
    p=f["position"]; delta=np.array(lamp)-p
    denom=delta@f["plate_normal"]
    t=np.divide((f["plate_center"]-p)@f["plate_normal"],denom,out=np.full(p.shape[:2],-1.),where=np.abs(denom)>1e-8)
    cross=p+t[...,None]*delta
    local=cross-f["plate_center"]
    return (t>0)&(t<1)&(np.abs(local@f["plate_tangent"])<=f["half_size"][0])&(np.abs(local[...,1])<=f["half_size"][1])&~f["plate"]


def interior(mask, radius=2):
    padded=np.pad(mask,radius,constant_values=False)
    return np.logical_and.reduce([padded[y:y+mask.shape[0],x:x+mask.shape[1]]
                                  for y in range(2*radius+1) for x in range(2*radius+1)])


def run(output, refine=False):
    output.mkdir(parents=True,exist_ok=False)
    compiler=Compiler(ROOT/"d3dcompiler_46.dll")
    for name in ("single_light.hlsl","single_light_visibility.hlsl"):
        shutil.copy2(ROOT/"tools/patches"/name,output/name)
    shaders={}
    for name,source in (("plain","single_light.hlsl"),("shadow","single_light_visibility.hlsl"),("audit","single_light_visibility.hlsl")):
        path=output/(name+".hlsl"); path.write_text(f"#define VISIBILITY_PLANE_REFINE {int(refine)}\n"+("#define VISIBILITY_AUDIT 1\n" if name=="audit" else "")+f'#include "{source}"\n')
        binary,diagnostics=compiler.compile(path)
        if diagnostics: raise ValueError(diagnostics)
        shaders[name]=output/(name+".bin"); shaders[name].write_bytes(binary)
        (output/(name+".asm")).write_text(compiler.disassemble(binary))
    checks=[]; pictures=[]; statistics=[]
    def check(name,passed,**metrics):
        checks.append(dict(name=name,passed=bool(passed),**metrics))
        if not passed: raise AssertionError(f"{name}: {metrics}")
    def draw(name,shader,f,lamp,enable=1,**kwargs):
        cb=dict(f["constants"]); cb[12]=[[enable,.025,.35,96]]; cb[13]=[[*lamp,9],[1,1,1,18]]
        return render(shaders[shader],output/name,f["width"],f["height"],f["textures"],cb,viewport=f["viewport"],**kwargs)[0,0]
    for name,settings in (("perspective",{}),("reverse",dict(reverse=True)),("right-handed",dict(right_handed=True)),
                          ("jitter",dict(jitter=(.013,-.021))),("viewport",dict(viewport=(9,5,108,68)))):
        f=scene(**settings); lamp=[-.65,.5,1.5*f["sign"]]
        raw=draw(name+"-raw","plain",f,lamp)
        off=draw(name+"-disabled","shadow",f,lamp,enable=0)
        lit=draw(name+"-lit","shadow",f,lamp)
        audit=draw(name+"-audit","audit",f,lamp)
        truth=exact_shadow(f,lamp); predicted=audit[...,0]<.5
        supported=(audit[...,1]>.5)&f["mask"]
        shadow_inside=interior(truth)&supported
        light_inside=interior(~truth&~f["plate"]&f["mask"])&supported
        detected=float(predicted[shadow_inside].mean())
        false_shadow=float(predicted[light_inside].mean())
        check(name+" nonempty test regions",shadow_inside.sum()>50 and light_inside.sum()>100,
              shadow_pixels=int(shadow_inside.sum()),lit_pixels=int(light_inside.sum()))
        check(name+" exact off switch",np.array_equal(raw,off))
        check(name+" finite bounded energy",np.isfinite(lit).all() and np.all(lit[:,:,:3]>=0) and np.all(lit<=raw+1e-7))
        check(name+" alpha zero",np.all(lit[...,3]==0))
        check(name+" plate blocks lamp",detected>=.99,interior_recall=detected)
        check(name+" no interior false shadows",false_shadow<=.005,false_shadow_rate=false_shadow)
        check(name+" actually removes light",float(raw[shadow_inside,:3].mean())>1e-4 and np.max(lit[shadow_inside,:3])<1e-7)
        statistics.append(dict(scene=name,interior_recall=detected,false_shadow_rate=false_shadow,
                               total_receiver_mismatch_pixels=int(((truth!=predicted)&supported&~f["plate"]).sum()),
                               unsupported_pixels=int((~supported&f["mask"]).sum())))
        np.savez(output/(name+"-reference.npz"),positions=f["position"],shadow=truth,
                 receiver=~f["plate"],supported=supported,shadow_interior=shadow_inside,lit_interior=light_inside)
        if name=="perspective":
            pictures=[("Unshadowed",raw[:,:,:3]),("Screen-space shadow",lit[:,:,:3]),("Geometry reference",raw[:,:,:3]*(~truth)[...,None])]
        print("PASS",name,flush=True)
    # Moving lamp: independent analytic shadow moves in the opposite direction.
    f=scene(); centroids=[]; movie=[]
    for i,x in enumerate(np.linspace(-.7,.7,7)):
        lamp=[x,.5,1.5]; audit=draw(f"motion-{i}-audit","audit",f,lamp)
        lit=draw(f"motion-{i}-lit","shadow",f,lamp)
        truth=exact_shadow(f,lamp); core=interior(truth)&(audit[...,1]>.5)
        check(f"motion {i} geometric shadow",core.sum()>20 and np.all(audit[core,0]==0))
        mask=(audit[...,0]<.5)&~f["plate"]
        centroids.append(float((mask*np.arange(f["width"])).sum()/mask.sum()))
        movie.append(preview(lit[:,:,:3]))
    check("shadow moves opposite lamp",np.all(np.diff(centroids)<0),centroids=centroids)
    repeat=draw("motion-repeat","shadow",f,[-.7,.5,1.5])
    first=np.fromfile(output/"motion-0-lit/pixels-f0-rt0.f32",dtype="<f4").reshape(repeat.shape)
    check("return to same lamp has no history",np.array_equal(first,repeat))
    # Deliberately expose failure modes as evidence, not hidden passing regions.
    outside=[2.,.5,1.5]
    audit=draw("outside-audit","audit",f,outside)
    raw=draw("outside-raw","plain",f,outside); lit=draw("outside-lit","shadow",f,outside)
    unknown=(audit[...,1]==0)&~f["plate"]
    check("offscreen unknown explicitly flagged",unknown.sum()>100,unknown_pixels=int(unknown.sum()))
    check("offscreen fallback is unshadowed",np.array_equal(raw[unknown],lit[unknown]))
    # An already observed blocker remains valid even if the remainder of the
    # segment would leave the screen. Unknown must not erase a confirmed hit.
    known=(audit[...,0]==0)&~f["plate"]
    check("known blocker survives offscreen lamp",known.sum()>20 and np.all(audit[known,1]==1),known_shadow_pixels=int(known.sum()))
    # Same receiver geometry, but no occluder in the depth buffer: impossible to
    # infer that wall from these inputs. Keep physical reference from full scene.
    missing=fixture(width=128,height=80); lamp=[-.65,.5,1.5]
    missing_raw=draw("missing-depth-raw","plain",missing,lamp)
    missing_lit=draw("missing-depth-lit","shadow",missing,lamp)
    physical_shadow=interior(exact_shadow(f,lamp))
    check("missing occluder demonstrably leaks",np.array_equal(missing_raw,missing_lit) and np.min(missing_lit[physical_shadow,:3])>0,
          leaked_reference_pixels=int(physical_shadow.sum()))
    sheet=Image.new("RGB",(384*3,272),(24,27,32))
    for i,(label,rgb) in enumerate(pictures):
        sheet.paste(preview(rgb),(384*i,32)); ImageDraw.Draw(sheet).text((384*i+12,10),label,fill="white")
    sheet.save(output/"visibility.png")
    movie[0].save(output/"visibility-motion.gif",save_all=True,append_images=movie[1:]+movie[-2:0:-1],duration=180,loop=0)
    report=dict(backend="D3D11 WARP actual Draw/CopyResource/Map",synthetic_inputs=True,checks=checks,
                plane_refinement=refine,
                check_count=len(checks),all_passed=True,geometry_statistics=statistics,
                source_sha256={name:digest((output/name).read_bytes()) for name in ("single_light.hlsl","single_light_visibility.hlsl")},
                game_package_created=False,game_runtime_verified=False,real_gpu_performance_measured=False,
                limits=["Offline-only b12 controls, default game packages unchanged",
                        "96 fixed steps with .025 bias/.35 assumed thickness; not robust arbitrary geometry",
                        "Missing/offscreen/transparent/hidden occluders cannot be reconstructed",
                        "Hard shadows, no filtering or temporal stabilization; boundary errors retained",
                        "Reinhard+sRGB previews; raw float readbacks authoritative"])
    (output/"report.json").write_bytes(encoded(report))
    print(json.dumps(dict(output=str(output),checks=len(checks),passed=True)))
    return report


def preview(rgb):
    linear=.8*(.06+rgb); mapped=linear/(1+linear)
    srgb=np.where(mapped<=.0031308,12.92*mapped,1.055*mapped**(1/2.4)-.055)
    return Image.fromarray(np.uint8(np.clip(srgb,0,1)*255)).resize((384,240))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("output",type=Path)
    p.add_argument("--refine",action="store_true",help="Experimental tangent-plane hit verification; default off")
    a=p.parse_args(); run(a.output,a.refine)
