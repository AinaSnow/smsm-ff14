"""Actual two-path native rendering of an optional angular diffuse response.

Synthetic material swatches, not game skin/cloth, and no physical area light/SSS.
"""
import argparse
import json
from pathlib import Path
import shutil
import numpy as np
from PIL import Image, ImageDraw
from manage_preview import ROOT, digest, encoded
from shader_compile import Compiler
from patch_shader_asm import instructions
from patch_material_light import load_original, compile_helper, patch
from patch_forward_light import compile_helper as mesh_helper, patch_forward, TARGET as MESH
from validate_single_light import fixture
from validate_material_light import material_inputs
from validate_forward_light import fixture as mesh_fixture
from validate_light_visibility import scene
from validate_material_visibility import visibility_constants
from offline.fuse_material_visibility import fuse
from offline_render import render


def response(cosine, strength, bounded=True):
    x=np.clip(cosine,0,1)
    # Cubic Bernstein basis; bounded has endpoint slopes 0/1, balanced 0/0.
    return ((1-strength)*x+strength*(x**3+(2 if bounded else 3)*x*x*(1-x)))/np.pi


def cpu_style(f,position,color=(1,1,1),intensity=18,radius=9,strength=.5,bounded=True):
    d=np.asarray(position)-f['position'];squared=np.sum(d*d,-1)
    cosine=np.sum(f['normal']*d,-1)/np.sqrt(np.maximum(squared,1e-8))
    attenuation=np.clip(1-squared/radius**2,0,1)**2/(1+squared)
    result=response(cosine,strength,bounded)[...,None]*attenuation[...,None]*intensity*np.asarray(color)
    result[~f['mask']]=0
    return result


def run(output,extraction,decompiler):
    output.mkdir(parents=True,exist_ok=False);compiler=Compiler(ROOT/'d3dcompiler_46.dll')
    for name in ('diffuse_response.hlsl','material_light.hlsl','material_visibility.hlsl','visibility_march.hlsl'):
        shutil.copy2(ROOT/'tools/patches'/name,output/name)
    checks=[];headroom=[];previews=[]
    def check(name,passed,**metrics):
        checks.append(dict(name=name,passed=bool(passed),**metrics))
        if not passed:raise AssertionError(f'{name}: {metrics}')
    def close(name,a,b,tol=3e-6):
        error=float(np.max(np.abs(a-b)))
        check(name,np.isfinite(a).all() and np.isfinite(b).all() and error<=tol,error=error,tolerance=tol)
    def compile_source(name,text):
        source=output/(name+'.hlsl');source.write_text(text)
        data,warnings=compiler.compile(source)
        if warnings:raise ValueError(warnings)
        path=output/(name+'.bin');path.write_bytes(data);return path
    def draw(name,shader,f,inputs,**kwargs):
        return render(shader,output/name,f['width'],f['height'],**inputs,**kwargs)[0,0]
    # Angular sweep includes exact endpoints and the whole back-facing half.
    ramp=compile_source('angular-ramp','#include "diffuse_response.hlsl"\n'
        'Texture2D<float4> input:register(t0); cbuffer C:register(b0){float4 controls;}'
        'float4 main(float4 p:SV_POSITION):SV_TARGET{float v=smsmDiffuseResponse(input.Load(int3(p.xy,0)).x,controls.x);return float4(v,v,v,0);}')
    cosines=np.linspace(-1,1,2049);tex=np.zeros((1,len(cosines),4),np.float32);tex[0,:,0]=cosines
    strengths=(0,.25,.5,1)
    ramps=render(ramp,output/'angular-render',len(cosines),1,textures={0:tex},
                 animation=(0,[[[s,0,0,0]] for s in strengths]))[:,0,0]
    curve_metrics=[]
    for i,s in enumerate(strengths):
        y=ramps[i,:,0];close(f'angular {s} Bernstein oracle',y,response(cosines,s),1e-7)
        check(f'angular {s} no backside light',np.all(y[cosines<=0]==0))
        check(f'angular {s} finite monotonic bounded',np.isfinite(y).all() and np.all(np.diff(y)>=-1e-7) and y.max()<=1/np.pi+1e-7)
        close(f'angular {s} RGB neutral',ramps[i,:,:3],np.broadcast_to(y[:,None],(len(y),3)),0)
        integral=float(2*np.pi*np.trapezoid(y[cosines>=0],cosines[cosines>=0]))
        check(f'angular {s} bounded below Lambert',np.all(y<=response(cosines,0)+1e-7))
        check(f'angular {s} uniform hemisphere response integral',abs(integral-(1-s/6))<2e-6,value=integral,expected=1-s/6)
        slope=float((y[1025]-y[1024])/(cosines[1025]-cosines[1024]))
        curve_metrics.append(dict(strength=s,terminator_slope=slope,uniform_hemisphere_integral=integral))
    check('full softness lowers terminator slope',curve_metrics[-1]['terminator_slope']<.01*curve_metrics[0]['terminator_slope'])
    balanced=compile_source('angular-balanced','#define SMSM_DIFFUSE_BOUNDED 0\n'+(output/'angular-ramp.hlsl').read_text())
    balanced_ramp=render(balanced,output/'angular-balanced-render',len(cosines),1,textures={0:tex},constants={0:[[.5,0,0,0]]})[0,0,0,:,0]
    close('balanced angular Bernstein oracle',balanced_ramp,response(cosines,.5,False),1e-7)
    check('balanced angular intermediate gain exposed',np.max(balanced_ramp-response(cosines,0))>.01)

    original=load_original(extraction);native=output/'native.bin';native.write_bytes(original)
    mesh_original=load_original(extraction,MESH);mesh_native=output/'mesh-native.bin';mesh_native.write_bytes(mesh_original)
    # Existing default helpers must retain the exact executable instructions.
    for name,builder,previous in [('material',compile_helper,'material-light-validation-v5'),('mesh',mesh_helper,'forward-light-validation-v5')]:
        data=builder(output/(name+'-default'),compiler)
        old=(ROOT/'artifacts'/previous/'lamp-audit/helper.bin').read_bytes()
        check(name+' default helper instructions unchanged',instructions(data)==instructions(old))
        for bad in (-.1,1.1,float('nan'),float('inf')):
            try:builder(output/(name+'-invalid'),compiler,softness=bad)
            except ValueError:passed=True
            else:passed=False
            check(name+' rejects invalid softness '+str(bad),passed)
    lamp=(-2,1,1);candidates={};mesh_candidates={}
    for s in (0,.5,1):
        helper=compile_helper(output/f'helper-{s}',compiler,lamp,intensity=18,radius=9,softness=s)
        _,data=patch(original,helper,output/f'patch-{s}',decompiler,compiler)
        candidates[s]=output/f'candidate-{s}.bin';candidates[s].write_bytes(data)
        helper=mesh_helper(output/f'mesh-helper-{s}',compiler,lamp,intensity=18,radius=9,softness=s)
        _,data=patch_forward(mesh_original,helper,output/f'mesh-patch-{s}',decompiler,compiler)
        mesh_candidates[s]=output/f'mesh-candidate-{s}.bin';mesh_candidates[s].write_bytes(data)
    f=fixture(width=128,height=96,geometry='sphere',rotation=37)
    cases=[('white',{}),('skin-swatch',dict(albedo=(.62,.34,.23))),('blue',dict(albedo=(.25,.35,.65))),
        ('ao',dict(ao=.25)),('no-ao',dict(ao=0)),('metal',dict(metal=1,spec=.2,environment=.3)),
        ('mixed-metal',dict(metal=.5,spec=.1,environment=.2,alpha_weights=(.8,.4))),
        ('emission',dict(emission=.4,alpha_weights=(.8,.4))),('exposure',dict(exposure=1.5))]
    for label,settings in cases:
        inputs=material_inputs(f,**settings);base=draw(label+'-native',native,f,inputs);pixels=[]
        for s in (0,.5,1):
            actual=draw(f'{label}-{s}',candidates[s],f,inputs)
            reference=dict(inputs);reference['textures']=dict(inputs['textures'])
            tex=inputs['textures'][3].copy();tex[...,:3]+=cpu_style(f,lamp,strength=s)
            reference['textures'][3]=tex;expected=draw(f'{label}-{s}-oracle',native,f,reference)
            close(f'{label} {s} complete native RGBA oracle',actual,expected)
            if label in ('no-ao','metal'):close(f'{label} {s} suppresses added diffuse',actual,base,0)
            if label in ('white','skin-swatch','blue'):
                albedo=np.array(settings.get('albedo',(.8,.8,.8)))
                close(f'{label} {s} linear chromaticity',actual[...,:3]**2-base[...,:3]**2,cpu_style(f,lamp,strength=s)*albedo,2e-6)
                pixels.append(actual[...,:3])
        if pixels:previews.append((label,*pixels))
        print('PASS full material',label,flush=True)
    # Same algorithm in mesh path; preserve native cutout/depth and alpha.
    for label,settings in [('white',{}),('skin',dict(albedo=(.62,.34,.23))),('normal-map',dict(normal_xy=(.7,.6))),
            ('grazing',dict(basis_angle=80)),('alpha-half',dict(alpha=.5)),('alpha-zero',dict(alpha=0)),('depth-rejected',dict(depth=.4))]:
        mf,inputs=mesh_fixture(compiler,output/(label+'-mesh-fixture'),**settings)
        base=draw(label+'-mesh-native',mesh_native,mf,inputs);alignment=-mf['normal'][...,2]
        for s in (.5,1):
            actual=draw(f'{label}-mesh-{s}',mesh_candidates[s],mf,inputs)
            ref=dict(inputs);ref['textures']=dict(inputs['textures']);tex=inputs['textures'][0].copy()
            tex[...,:3]+=cpu_style(mf,lamp,strength=s)/alignment[...,None];ref['textures'][0]=tex
            expected=draw(f'{label}-mesh-{s}-oracle',mesh_native,mf,ref)
            close(f'{label} mesh {s} native RGBA oracle',actual,expected)
            close(f'{label} mesh {s} alpha preserved',actual[...,3],base[...,3],0)
            if label in ('alpha-zero','depth-rejected'):close(f'{label} mesh {s} discard unchanged',actual,base,0)
        print('PASS mesh material',label,flush=True)
    # Integrate styling with visibility and native composition in one draw.
    fused={};audit=None
    for s in (0,.5):
        prefix='' if not s else f'#define SMSM_DIFFUSE_SOFTNESS {s}\n'
        helper=compile_source(f'fused-helper-{s}',prefix+'#define MATERIAL_PLANE_REFINE 1\n#define MATERIAL_VISIBILITY_ADD_ONLY 1\n#include "material_visibility.hlsl"\n')
        fused[s]=fuse(original,helper.read_bytes(),output/f'fused-{s}',decompiler,compiler)
    helper=compile_source('fused-balanced','#define SMSM_DIFFUSE_SOFTNESS .5\n#define SMSM_DIFFUSE_BOUNDED 0\n#define MATERIAL_PLANE_REFINE 1\n#define MATERIAL_VISIBILITY_ADD_ONLY 1\n#include "material_visibility.hlsl"\n')
    fused['balanced']=fuse(original,helper.read_bytes(),output/'fused-balanced',decompiler,compiler)
    audit=compile_source('visibility-audit','#define MATERIAL_PLANE_REFINE 1\n#define MATERIAL_VISIBILITY_AUDIT 1\n#include "material_visibility.hlsl"\n')
    sf=scene();inputs=material_inputs(sf);inputs['constants'][12]=visibility_constants(sf,bias=.0125,thickness=.2,steps=128)
    params=[[[x,.5,1.5,9],[1,1,1,18]] for x in np.linspace(-.8,-.5,13)]
    visible=render(audit,output/'moving-visibility',sf['width'],sf['height'],**inputs,animation=(13,params))[:,0,...,0]
    moving=render(fused[.5],output/'moving-fused',sf['width'],sf['height'],**inputs,animation=(13,params))[:,0]
    baseline=draw('shadow-native',native,sf,inputs)
    for i,p in enumerate(params):
        ref=dict(inputs);ref['textures']=dict(inputs['textures']);tex=inputs['textures'][3].copy()
        tex[...,:3]+=cpu_style(sf,p[0][:3],strength=.5)*visible[i,...,None];ref['textures'][3]=tex
        expected=draw(f'moving-reference-{i}',native,sf,ref)
        close(f'moving styled shadow {i} native oracle',moving[i],expected)
        blocked=(visible[i]==0)&~sf['plate'];check(f'moving styled shadow {i} contains blocked receiver',blocked.sum()>30)
        close(f'moving styled shadow {i} retains native light',moving[i][blocked],baseline[blocked],0)
    # Screen-response clipping is measured, not hidden by clipping render values.
    # This is pre-display native output and not a monitor/HDR calibration.
    for label,albedo in [('white',(.8,.8,.8)),('skin',(.62,.34,.23))]:
        for intensity in (18,60,120):
            f=fixture(width=96,height=64,geometry='sphere');inputs=material_inputs(f,albedo=albedo)
            inputs['constants'][12]=visibility_constants(f,enable=0,bias=.0125,thickness=.2,steps=128)
            inputs['constants'][13]=[[*lamp,9],[1,1,1,intensity]]
            outputs={}
            for key in (0,.5,'balanced'):
                s=.5 if key=='balanced' else key
                actual=draw(f'headroom-{label}-{intensity}-{key}',fused[key],f,inputs)
                outputs[key]=actual
                ref=dict(inputs);ref['textures']=dict(inputs['textures']);tex=inputs['textures'][3].copy()
                tex[...,:3]+=cpu_style(f,lamp,intensity=intensity,strength=s,bounded=key!='balanced');ref['textures'][3]=tex
                close(f'headroom {label} {intensity} {key} oracle',actual,draw(f'headroom-ref-{label}-{intensity}-{key}',native,f,ref))
                headroom.append(dict(material=label,intensity=intensity,softness=s,profile='balanced' if key=='balanced' else 'bounded',maximum=float(actual[...,:3].max()),
                    pixels_above_one=int(np.any(actual[...,:3]>1,axis=-1).sum()),pixels=f['width']*f['height']))
            check(f'bounded {label} {intensity} never brighter than Lambert',np.all(outputs[.5][...,:3]<=outputs[0][...,:3]+2e-6))
            check(f'bounded {label} {intensity} no extra pixels above one',
                np.any(outputs[.5][...,:3]>1,axis=-1).sum()<=np.any(outputs[0][...,:3]>1,axis=-1).sum())
    # Exact back-facing fixture: neither algorithm turns a point light into fill.
    f=fixture(width=48,height=32);inputs=material_inputs(f);inputs['constants'][12]=visibility_constants(f,enable=0)
    inputs['constants'][13]=[[0,0,7,9],[1,1,1,18]]
    close('back-facing plane remains native',draw('backface-styled',fused[.5],f,inputs),draw('backface-native',native,f,inputs),0)
    # FP16 storage does not change the intended composition.
    f=fixture(width=96,height=64,geometry='sphere');inputs=material_inputs(f)
    actual=draw('fp16-styled',candidates[.5],f,inputs,target_format='rgba16f')
    inputs['textures'][3][...,:3]+=cpu_style(f,lamp,strength=.5)
    expected=draw('fp16-reference',native,f,inputs,target_format='rgba16f')
    ulp=np.spacing(np.maximum(np.abs(actual),np.abs(expected)).astype(np.float16)).astype(np.float32)
    check('FP16 within one storage ULP',np.isfinite(actual).all() and np.all(np.abs(actual-expected)<=ulp),
        maximum_ulp_error=float((np.abs(actual-expected)/ulp).max()))
    panel=Image.new('RGB',(960,720),'#191d23');labels=ImageDraw.Draw(panel)
    for col,title in enumerate(('Lambert','Bounded softness 0.5','Bounded softness 1','Signed difference x8')):labels.text((col*240+5,8),title,fill='white')
    for row,(label,base,half,full) in enumerate(previews):
        y=30+row*226;labels.text((5,y),label+' (synthetic native material)',fill='white')
        for col,pixels in enumerate((base,half,full,.5+(half-base)*8)):
            panel.paste(Image.fromarray(np.uint8(np.clip(pixels,0,1)*255)).resize((240,180)),(col*240,y+20))
    panel.save(output/'soft-diffuse-comparison.png')
    report=dict(check_count=len(checks),all_passed=True,checks=checks,angular_metrics=curve_metrics,headroom=headroom,
        source_sha256={n:digest((ROOT/'tools/patches'/n).read_bytes()) for n in ('diffuse_response.hlsl','material_light.hlsl','forward_material_light.hlsl')},
        candidate_sha256={str(s):digest(p.read_bytes()) for s,p in candidates.items()},
        mesh_candidate_sha256={str(s):digest(p.read_bytes()) for s,p in mesh_candidates.items()},
        default_softness=0,preferred_experimental_profile='bounded',game_package_created=False,game_runtime_verified=False,performance_verified=False,
        limits=['Angular cubic style is not area-light diffusion, SSS, indirect light or a soft shadow',
            'Bounded profile darkens intermediate angles; its uniform-hemisphere response integral is 1-strength/6',
            'Balanced comparison can brighten intermediate angles; both profiles can still clip under high exposure',
            'Synthetic white/skin swatches do not establish naturalness on game materials',
            'Offline fused b12/b13 are not game bindings; hard screen-space visibility and missing geometry limits remain',
            'No temporal stability or actual GPU cost improvement claimed'])
    (output/'report.json').write_bytes(encoded(report))
    print(json.dumps(dict(checks=len(checks),headroom=headroom),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--extraction',type=Path,default=ROOT/'artifacts/client-2026.09.15')
    p.add_argument('--decompiler',type=Path,default=ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe')
    a=p.parse_args();run(a.output,a.extraction,a.decompiler)
