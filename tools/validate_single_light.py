"""Actual rasterization, analytic-reference and patched-MRT differential tests.

Synthetic inputs are not game captures. WARP results verify math and injection,
not real GPU cost, gameplay coverage, material accuracy or shadow correctness.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from build_single_light import TARGETS, compile_helper, patch_light
from manage_preview import ROOT, digest, encoded, read_package
from offline_render import render
from shader_compile import Compiler


def fixture(width=96, height=64, reverse=False, right_handed=False, rotation=0, viewport=None, geometry="plane", jitter=(0, 0)):
    vx, vy, vw, vh = viewport or (0, 0, width, height)
    near, far = .3, 80.
    focal = 1 / np.tan(np.deg2rad(60) / 2)
    projection = np.zeros((4, 4), dtype=np.float64)
    projection[0, 0] = focal / (vw / vh); projection[1, 1] = focal
    projection[0, 2], projection[1, 2] = jitter
    projection[2, 2], projection[2, 3], projection[3, 2] = far/(far-near), -near*far/(far-near), 1
    if reverse:
        projection[2, 2], projection[2, 3] = near/(near-far), -near*far/(near-far)
    if right_handed:
        projection[:, 2] *= -1
    y, x = np.mgrid[:height, :width].astype(float); x += .5; y += .5
    ndcx, ndcy = 2*(x-vx)/vw-1, 1-2*(y-vy)/vh
    sign = -1 if right_handed else 1
    rays = np.stack(((ndcx-jitter[0])/(focal/(vw/vh)), (ndcy-jitter[1])/focal, np.full_like(x, sign)), -1)
    # Independent ray/geometry construction; positions are not reconstructed
    # with the inverse matrix used by the shader under test.
    p = rays * 5
    n = np.broadcast_to([0., 0., -sign], p.shape).copy()
    if geometry == "tilt":
        n0 = np.array([.35, .15, -sign]); n0 /= np.linalg.norm(n0)
        distance = np.dot(n0, [0, 0, sign*5]) / (rays @ n0)
        p = rays * distance[..., None]; n[:] = n0
    if geometry == "sphere":
        center = np.array([0, 0, sign*5.5]); radius = 1.6
        a = np.sum(rays*rays, -1); b = -2*(rays @ center); c = center@center-radius*radius
        disc = b*b-4*a*c; hit = disc >= 0
        distance = (-b-np.sqrt(np.maximum(disc, 0)))/(2*a)
        sphere_p = rays*distance[..., None]
        p[hit] = sphere_p[hit]; n[hit] = (sphere_p[hit]-center)/radius
    h = np.concatenate((p, np.ones((*p.shape[:2], 1))), -1) @ projection.T
    depth = np.zeros((height, width, 4), dtype=np.float32); depth[..., 0] = h[..., 2]/h[..., 3]
    angle = np.deg2rad(rotation)
    view = np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
    normals = np.zeros_like(depth); normals[..., :3] = (n @ view) * .5 + .5
    common = np.array([[1/width,1/height,0,0],[2/vw,-2/vh,-1-2*vx/vw,1+2*vy/vh]], dtype=np.float32)
    camera = np.zeros((18,4), dtype=np.float32); camera[:3,:3]=view; camera[14:18]=np.linalg.inv(projection)
    mask = (x>=vx)&(x<vx+vw)&(y>=vy)&(y<vy+vh)
    return {"textures": {0:depth,3:normals}, "constants": {0:common,1:camera}, "position":p, "normal":n,
            "mask":mask, "viewport":viewport, "width":width, "height":height}


def cpu_light(f, position=(0,0,0), color=(1,1,1), intensity=2., radius=8.):
    delta = np.asarray(position)-f["position"]
    d2 = np.sum(delta*delta, -1)
    direction = delta/np.sqrt(np.maximum(d2[...,None],1e-8))
    cosine = np.clip(np.sum(f["normal"]*direction,-1),0,1)
    cutoff = np.clip(1-d2/(radius*radius),0,1)
    value = cosine/np.pi * cutoff**2/(1+d2) * intensity
    value[~f["mask"]] = 0
    return value[...,None]*color


def original_inputs(f):
    textures = dict(f["textures"]); constants = dict(f["constants"])
    shape = (f["height"],f["width"],4)
    for slot,value in {1:(1,1,1,1),4:(0,.6,.2,.3),5:(.4,.35,.3,0),6:(.5,.5,0,0),7:(1,1,1,1),8:(1,1,1,1)}.items():
        textures[slot]=np.broadcast_to(value,shape).copy()
    light = np.zeros((25,4),np.float32)
    light[1,:3]=(0,0,-1); light[2,:3]=(.4,.4,.4); light[3,:3]=(.2,.2,.2); light[4]=(0,0,1,0)
    light[20:24]=np.eye(4)
    shadow = np.zeros((6,4),np.float32); shadow[5,3]=1
    fake = np.zeros((6,4),np.float32); fake[0,:3]=(0,0,-1); fake[2,:3]=(1,0,0); fake[4,:3]=(0,1,0)
    constants.update({2:light,3:np.zeros((1,4)),4:np.eye(4),5:shadow,6:fake})
    structured=np.zeros((256,32),dtype=np.float32)
    structured[:,2]=1 # finite subsurface width; type/index bytes remain zero
    return textures,constants,{2:(128,structured.tobytes())}


def run(output, package, decompiler):
    output.mkdir(parents=True, exist_ok=False)
    compiler=Compiler(ROOT / "d3dcompiler_46.dll")
    source=(ROOT / "tools/patches/single_light.hlsl").read_text()
    shaders={}
    for mode in (0,1,2):
        path=output/f"helper-mode{mode}.hlsl"; path.write_text(f"#define SINGLE_LIGHT_AUDIT_MODE {mode}\n"+source)
        binary,diagnostics=compiler.compile(path)
        if diagnostics: raise ValueError(diagnostics)
        shaders[mode]=output/f"helper-mode{mode}.bin"; shaders[mode].write_bytes(binary)
    checks=[]; images=[]
    def assert_error(name, actual, expected, tolerance=2e-5):
        if not np.isfinite(actual).all() or not np.isfinite(expected).all(): raise AssertionError(name+": nonfinite result")
        error=float(np.max(np.abs(actual-expected)))
        checks.append({"name":name,"max_abs_error":error,"tolerance":tolerance,"passed":error<=tolerance})
        if error>tolerance: raise AssertionError(f"{name}: {error} > {tolerance}")
    def draw(name, shader, f, constants=None, **kwargs):
        return render(shader, output/name, f["width"], f["height"], textures=f["textures"],
                      constants=f["constants"] if constants is None else constants, viewport=f["viewport"], **kwargs)
    configurations=[("perspective",{}),("reverse-z",{"reverse":True}),("right-handed",{"right_handed":True}),
                    ("rotated-normal",{"rotation":37}),("tilted-plane",{"geometry":"tilt"}),
                    ("offset-viewport",{"width":128,"height":96,"viewport":(13,7,91,65)}),
                    ("jittered-projection",{"jitter":(.013,-.021)}),("wide",{"width":128,"height":48})]
    for name,settings in configurations:
        f=fixture(**settings); mask=f["mask"]
        position=draw(name+"-position",shaders[1],f)[0,0]
        normal=draw(name+"-normal",shaders[2],f)[0,0]
        assert_error(name+" position",position[mask,:3],f["position"][mask],5e-5)
        assert_error(name+" normal",normal[mask,:3],f["normal"][mask],2e-6)
        cb=dict(f["constants"], **{})
        cb[13]=[[0,0,0,8],[1,1,1,2]]
        lit=draw(name+"-light",shaders[0],f,cb)[0,0]
        assert_error(name+" analytic light",lit[...,:3],cpu_light(f),3e-6)
        assert_error(name+" alpha zero",lit[...,3],np.zeros(mask.shape),0)
        if settings.get("viewport"):
            assert_error("outside viewport untouched",lit[~mask],np.zeros_like(lit[~mask]),0)
        print("PASS",name,flush=True)
    # True dynamic parameter updates on the same WARP device/draw pipeline.
    f=fixture(width=160,height=96,geometry="sphere")
    animation=[]
    for x in np.linspace(-3,3,13): animation.append([[x,0,1,8],[1,1,1,12]])
    motion=draw("moving-light",shaders[0],f,animation=(13,animation))[:,0]
    centroids=[]
    for i,params in enumerate(animation):
        expected=cpu_light(f,params[0][:3],params[1][:3],params[1][3],params[0][3])
        assert_error(f"moving light frame {i}",motion[i,...,:3],expected,6e-6)
        luminance=motion[i,...,:3].mean(-1)
        centroids.append(float((luminance*np.arange(f["width"])).sum()/luminance.sum()))
    if not np.all(np.diff(centroids)>0): raise AssertionError("Moving lamp highlight failed to move right monotonically")
    checks.append({"name":"moving highlight centroid", "pixels":centroids,"passed":True})
    # Repeat the same input after moving away: no hidden history in this helper.
    repeat=draw("repeat-motion",shaders[0],f,animation=(13,[animation[0],animation[-1],animation[0]]))[:,0]
    assert_error("repeat same light after movement",repeat[0],repeat[2],0)
    images.extend([(f"lamp x={animation[i][0][0]:g}",motion[i,...,:3],f) for i in (0,6,12)])
    plane=fixture(); cases=[("off",[0,0,0,8],[1,1,1,0]),("out-of-range",[0,0,0,1],[1,1,1,2]),
                          ("behind-surface",[0,0,7,8],[1,1,1,2]),("red",[0,0,0,8],[1,0,0,2]),
                          ("double",[0,0,0,8],[1,1,1,4]),("wide-range",[0,0,0,12],[1,1,1,2])]
    for name,pos,col in cases:
        cb=dict(plane["constants"]); cb[13]=[pos,col]
        actual=draw("controls-"+name,shaders[0],plane,cb)[0,0,...,:3]
        assert_error("control "+name,actual,cpu_light(plane,pos[:3],col[:3],col[3],pos[3]),3e-6)
    # Invalid/background depth and degenerate normals must add no illumination.
    invalid=fixture(); invalid["textures"][0][:,:24,0]=0; invalid["textures"][0][:,24:48,0]=1
    invalid["textures"][3][:,48:72,:3]=.5; invalid["textures"][0][:,72:,0]=np.nan
    cb=dict(invalid["constants"]); cb[13]=[[0,0,0,8],[1,1,1,2]]
    invalid_out=draw("invalid-input",shaders[0],invalid,cb)[0,0]
    assert_error("invalid pixels add nothing",invalid_out,np.zeros_like(invalid_out),0)
    # Render ORIGINAL game DXBC and the exact packaged ASM patch on identical,
    # finite synthetic buffers. Test additive RGB, alpha, and specular MRT.
    manifest,_=read_package(package)
    settings=manifest["single_light"]
    host=fixture(); textures,constants,structured=original_inputs(host)
    helper=compile_helper(output/"zero-helper",compiler,settings["position_view"],settings["color_linear"],0,settings["range"])
    for target in TARGETS:
        original=package/"build-audit"/target/"original.bin"
        patched=package/"SMSM-ShaderFixes"/f"{target}-ps.bin"
        baseline=render(original,output/(target+"-original"),host["width"],host["height"],textures,constants,structured,targets=2)[0]
        lit=render(patched,output/(target+"-injected"),host["width"],host["height"],textures,constants,structured,targets=2)[0]
        expected=cpu_light(host,settings["position_view"],settings["color_linear"],settings["intensity"],settings["range"])
        assert_error(target+" diffuse delta",lit[0,...,:3]-baseline[0,...,:3],expected,4e-6)
        assert_error(target+" alpha preserved",lit[0,...,3],baseline[0,...,3],0)
        assert_error(target+" specular MRT preserved",lit[1],baseline[1],0)
        _,zero=patch_light(original.read_bytes(),helper,output/(target+"-zero-audit"),target,decompiler,compiler)
        zero_path=output/(target+"-zero.bin"); zero_path.write_bytes(zero)
        off=render(zero_path,output/(target+"-zero"),host["width"],host["height"],textures,constants,structured,targets=2)[0]
        assert_error(target+" zero intensity baseline",off,baseline,0)
        for label,position,color,intensity,radius in (
                ("left-warm",[-2,0,1],[1,.8,.6],3,8),
                ("right-cool",[2,0,1],[.6,.8,1],3,8),
                ("short-range",[0,0,2],[1,1,1],4,2)):
            variant_helper=compile_helper(output/(target+"-"+label+"-helper"),compiler,position,color,intensity,radius)
            _,variant=patch_light(original.read_bytes(),variant_helper,output/(target+"-"+label+"-audit"),target,decompiler,compiler)
            variant_path=output/(target+"-"+label+".bin"); variant_path.write_bytes(variant)
            result=render(variant_path,output/(target+"-"+label),host["width"],host["height"],textures,constants,structured,targets=2)[0]
            expected_variant=cpu_light(host,position,color,intensity,radius)
            assert_error(target+" "+label+" diffuse delta",result[0,...,:3]-baseline[0,...,:3],expected_variant,4e-6)
            assert_error(target+" "+label+" alpha",result[0,...,3],baseline[0,...,3],0)
            assert_error(target+" "+label+" specular",result[1],baseline[1],0)
        np.save(output/(target+"-diff.npy"),lit-baseline)
        print("PASS injection",target,flush=True)
    # White light must not rotate linear RGB hue in this diffuse-only material
    # visualization. Actual game skin/material paths remain a separate gate.
    albedos=np.array([[.8,.8,.8],[.62,.34,.23],[.25,.35,.65]])
    for index,albedo in enumerate(albedos):
        material=albedo*(.12+motion[6,...,:3])
        ratio=material/material.sum(-1,keepdims=True)
        assert_error(f"neutral light material chromaticity {index}",ratio,np.broadcast_to(albedo/albedo.sum(),ratio.shape),1e-7)
    previews=[]
    for name,rgb,scene in images:
        albedo=np.full_like(rgb,.8)
        albedo[:,scene["width"]//3:2*scene["width"]//3]=(.62,.34,.23)
        linear=albedo*(.12+rgb)
        # Documented display-only Reinhard + sRGB; raw .f32 remain authoritative.
        mapped=linear/(1+linear); srgb=np.where(mapped<=.0031308,12.92*mapped,1.055*mapped**(1/2.4)-.055)
        picture=Image.fromarray(np.uint8(np.clip(srgb,0,1)*255)).resize((480,288))
        tile=Image.new("RGB",(480,320),(24,27,32)); tile.paste(picture,(0,32)); ImageDraw.Draw(tile).text((12,10),name,fill="white")
        previews.append(tile)
    sheet=Image.new("RGB",(1440,320));
    for i,picture in enumerate(previews): sheet.paste(picture,(i*480,0))
    sheet.save(output/"moving-light.png")
    # Animation encodes consecutive REAL readbacks, not generated intermediates.
    movie=[]
    for frame in motion:
        linear=.8*(.12+frame[...,:3]); mapped=linear/(1+linear)
        srgb=np.where(mapped<=.0031308,12.92*mapped,1.055*mapped**(1/2.4)-.055)
        movie.append(Image.fromarray(np.uint8(np.clip(srgb,0,1)*255)).resize((480,288)))
    movie[0].save(output/"moving-light.gif",save_all=True,append_images=movie[1:]+movie[-2:0:-1],duration=100,loop=0)
    report={"backend":"D3D11 WARP Draw + CopyResource + Map", "synthetic_inputs":True,"checks":checks,
            "check_count":len(checks),"all_passed":all(c["passed"] for c in checks),"package_sha256":digest((package/"SMSM-preview.json").read_bytes()),
            "game_runtime_verified":False,"real_gpu_performance_measured":False,"occlusion_implemented":False,
            "display_preview":"Reinhard + sRGB visualization of synthetic diffuse/albedo; not FF14 screenshot",
            "limitations":["No occlusion: surfaces can light through walls", "Visible opaque depth/normal only; no transparent/back/offscreen geometry",
                           "View-space camera-relative light; game parameters baked per immutable package", "Game stage draw count and blend/material compatibility unverified"]}
    (output/"report.json").write_bytes(encoded(report))
    print(json.dumps({"output":str(output),"checks":len(checks),"passed":report["all_passed"]}))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("output",type=Path)
    p.add_argument("--package",type=Path,default=ROOT/"artifacts/experimental-2026.09.15-single-light-v1")
    p.add_argument("--decompiler",type=Path,default=ROOT/"artifacts/decompiler/1.3.16/cmd_Decompiler.exe")
    a=p.parse_args(); run(a.output,a.package,a.decompiler.resolve())
