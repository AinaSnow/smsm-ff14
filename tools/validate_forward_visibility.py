"""Offline depth reconstruction and visibility inside an exact native mesh PS.

Synthetic plane/occluder, explicit projection constants; no live game binding.
"""
import argparse
import json
from pathlib import Path
import shutil
import numpy as np
from PIL import Image,ImageDraw
from manage_preview import ROOT,encoded,digest
from shader_compile import Compiler
from patch_material_light import load_original
from patch_forward_light import TARGET
from offline.fuse_material_visibility import fuse
from offline_render import render
from validate_forward_light import fixture as mesh_fixture
from validate_light_visibility import exact_shadow,interior
from validate_soft_diffuse import cpu_style
from build_preview import verify_interface


def fixture(compiler,work,width=128,height=80,orthographic=False,angle=0,half_size=(.45,.65),
            viewport=None,jitter=(0,0),**material):
    f,inputs=mesh_fixture(compiler,work,width=width,height=height,**material)
    vx,vy,vw,vh=viewport or (0,0,width,height)
    y,x=np.mgrid[:height,:width].astype(float);x+=.5;y+=.5
    uv=np.stack(((x-vx)/vw,(y-vy)/vh),-1);ndc=uv*[2,-2]+[-1,1]
    p=np.concatenate(((ndc-np.array(jitter))*[3,2],np.full((height,width,1),5.)),axis=-1)
    f.update(position=p,viewport=viewport,mask=(x>=vx)&(x<vx+vw)&(y>=vy)&(y<vy+vh))
    near,far=.3,80
    projection=np.zeros((4,4))
    if orthographic:
        projection[0,0]=1/3;projection[1,1]=1/2;projection[:2,3]=jitter
        projection[2,2]=1/(far-near);projection[2,3]=-near/(far-near);projection[3,3]=1
        origin=p.copy();origin[...,2]=0;ray=np.zeros_like(p);ray[...,2]=1
    else:
        projection[0,0]=5/3;projection[1,1]=5/2;projection[:2,2]=jitter
        projection[2,2]=far/(far-near);projection[2,3]=-near*far/(far-near);projection[3,2]=1
        origin=np.zeros_like(p);ray=p/5
    theta=np.deg2rad(angle);normal=np.array([np.sin(theta),0,-np.cos(theta)])
    tangent=np.array([np.cos(theta),0,np.sin(theta)]);center=np.array([0,0,3.])
    denominator=ray@normal
    distance=np.divide((center-origin)@normal,denominator,out=np.full((height,width),-1.),where=np.abs(denominator)>1e-8)
    hit_position=origin+distance[...,None]*ray;local=hit_position-center
    hit=(distance>0)&(distance<5)&(np.abs(local@tangent)<=half_size[0])&(np.abs(local[...,1])<=half_size[1])&f['mask']
    positions=p.copy();positions[hit]=hit_position[hit]
    normals=np.broadcast_to([0,0,-1.],p.shape).copy();normals[hit]=normal
    homogeneous=np.concatenate((positions,np.ones((height,width,1))),-1)@projection.T
    depth=(homogeneous[...,2]/homogeneous[...,3]).astype(np.float32)
    depth[~f['mask']]=1
    inputs['textures'][2][...,0]=depth;inputs['textures'][4][...,:3]=normals*.5+.5
    receiver_clip=projection@np.array([0,0,5,1.]);z=float(receiver_clip[2]/receiver_clip[3])
    # Native PS requires a positive depth gap, not equality. The synthetic VS
    # receives an explicit 1e-5 raster-depth bias; this is not a recovered state.
    source=inputs['vertex'].with_suffix('.hlsl');text=source.read_text()
    text=text.replace('float2(-1,1),.5,1)',f'float2(-1,1),{z-1e-5:.12g},1)')
    text=text.replace('(uv.x*2-1)*3',f'(uv.x*2-1-({jitter[0]:.12g}))*3')
    text=text.replace('(1-uv.y*2)*2',f'(1-uv.y*2-({jitter[1]:.12g}))*2')
    source.write_text(text);data,warnings=compiler.compile(source,'vs_5_0')
    if warnings:raise ValueError(warnings)
    inputs['vertex'].write_bytes(data)
    # The standalone visibility audit needs final mesh normal/position semantics,
    # unlike the original mesh shader's color/UV input semantics.
    audit_source=work/'audit-vs.hlsl'
    n=f['normal'][0,0]
    # The standalone helper declares normal at v0 and position at v1. Supply
    # those VS output registers explicitly, instead of reusing native v1/v2 UVs.
    audit_source.write_text('struct O{float3 normal:COLOR0;float3 position:TEXCOORD0;float4 clip:SV_POSITION;};'
        'O main(uint id:SV_VertexID){O o;float2 uv=float2((id<<1)&2,id&2);'
        f'o.normal=float3({n[0]:.12g},{n[1]:.12g},{n[2]:.12g});'
        f'o.position=float3((uv.x*2-1-({jitter[0]:.12g}))*3,(1-uv.y*2-({jitter[1]:.12g}))*2,5);'
        f'o.clip=float4(uv*float2(2,-2)+float2(-1,1),{z-1e-5:.12g},1);return o;}}')
    data,warnings=compiler.compile(audit_source,'vs_5_0')
    if warnings:raise ValueError(warnings)
    audit_vertex=work/'audit-vs.bin';audit_vertex.write_bytes(data)
    controls=np.vstack(([1,.0125,.2,128],projection,
        [vw/(2*width),-vh/(2*height),(vx+vw/2)/width,(vy+vh/2)/height],np.linalg.inv(projection))).astype(np.float32)
    inputs['constants'][12]=controls
    f.update(plate=hit,plate_center=center,plate_normal=normal,plate_tangent=tangent,half_size=half_size,
             scene_position=positions,scene_normal=normals,audit_vertex=audit_vertex,raster_depth=z-1e-5)
    return f,inputs


def run(output,extraction,decompiler):
    output.mkdir(parents=True,exist_ok=False);compiler=Compiler(ROOT/'d3dcompiler_46.dll')
    names=('forward_visibility.hlsl','forward_material_light.hlsl','visibility_march.hlsl','diffuse_response.hlsl')
    for name in names:shutil.copy2(ROOT/'tools/patches'/name,output/name)
    native=output/'native.bin';native.write_bytes(load_original(extraction,TARGET));checks=[];geometry=[];pictures=[]
    def compile_source(name,text):
        source=output/(name+'.hlsl');source.write_text(text);data,warnings=compiler.compile(source)
        if warnings:raise ValueError(warnings)
        path=output/(name+'.bin');path.write_bytes(data);return path
    def check(name,passed,**values):
        checks.append(dict(name=name,passed=bool(passed),**values))
        if not passed:raise AssertionError(f'{name}: {values}')
    def close(name,a,b,tol=4e-6):
        error=float(np.max(np.abs(a-b)))
        check(name,np.isfinite(a).all() and np.isfinite(b).all() and error<=tol,error=error,tolerance=tol)
    def draw(name,shader,f,inputs,**extra):
        return render(shader,output/name,f['width'],f['height'],**inputs,viewport=f['viewport'],**extra)[0,0]
    def audit_draw(name,f,inputs):
        copy=dict(inputs);copy['vertex']=f['audit_vertex'];return draw(name,audit,f,copy)
    shaders={}
    for s in (0,.5):
        prefix='' if not s else '#define SMSM_DIFFUSE_SOFTNESS .5\n'
        helper=compile_source(f'helper-{s}',prefix+'#define VISIBILITY_PLANE_DISTANCE 1\n#define MATERIAL_PLANE_REFINE 1\n#include "forward_visibility.hlsl"\n')
        shaders[s]=fuse(native.read_bytes(),helper.read_bytes(),output/f'fused-{s}',decompiler,compiler,mesh=True)
        try:verify_interface(compiler.disassemble(native.read_bytes()),compiler.disassemble(shaders[s].read_bytes()))
        except ValueError as exc:blocked='reads beyond original range' in str(exc)
        else:blocked=False
        check(f'{s} game interface rejects offline constants',blocked)
    audit=compile_source('audit','#define VISIBILITY_PLANE_DISTANCE 1\n#define MATERIAL_PLANE_REFINE 1\n#define MATERIAL_VISIBILITY_AUDIT 1\n#include "forward_visibility.hlsl"\n')
    baseline_audit=compile_source('baseline-audit','#define MATERIAL_PLANE_REFINE 1\n#define MATERIAL_VISIBILITY_AUDIT 1\n#include "forward_visibility.hlsl"\n')
    reconstruct=compile_source('reconstruct',(output/'forward_visibility.hlsl').read_text().split('float4 main(',1)[0]+
        'float4 main(float4 pixel:SV_POSITION):SV_TARGET {uint w,h;sceneDepth.GetDimensions(w,h);'
        'bool valid;float3 p=visiblePosition(pixel.xy/float2(w,h),valid);return float4(p,valid?1:0);}')
    lamp=[-.65,.5,1.5]
    configs=[('perspective',{}),('orthographic',dict(orthographic=True)),('tilted',dict(angle=25)),
        ('grazing-plate',dict(angle=65)),('thin',dict(half_size=(.08,.65))),
        ('high-resolution',dict(width=256,height=160)),('jitter',dict(jitter=(.013,-.021))),
        ('viewport',dict(viewport=(9,5,108,68))),('heldout-negative-angle',dict(angle=-40)),
        ('heldout-angle-40',dict(angle=40)),('heldout-angle-55',dict(angle=55)),('heldout-angle-70',dict(angle=70))]
    for label,settings in configs:
        f,inputs=fixture(compiler,output/(label+'-fixture'),**settings);inputs['constants'][13]=[[*lamp,9],[1,1,1,18]]
        rec_inputs=dict(inputs);rec_inputs.pop('vertex')
        position=draw(label+'-reconstruction',reconstruct,f,rec_inputs)
        close(label+' depth reconstructed at texel centers',position[f['mask'],:3],f['scene_position'][f['mask']],8e-5)
        check(label+' depth validity',np.all(position[f['mask'],3]==1))
        base=draw(label+'-native',native,f,inputs);a=audit_draw(label+'-audit',f,inputs)
        audit_inputs=dict(inputs);audit_inputs['vertex']=f['audit_vertex']
        before=draw(label+'-baseline-audit',baseline_audit,f,audit_inputs)
        receiver=f['mask']&~f['plate'];truth=exact_shadow(f,lamp)&receiver;predicted=a[...,0]<.5
        check(label+' native receiver coverage',np.all(base[receiver,3]>0))
        close(label+' native rejects occluder-covered receiver',base[f['plate']],np.zeros_like(base[f['plate']]),0)
        core=interior(truth)&receiver
        if label in ('perspective','orthographic','jitter','viewport'):
            check(label+' geometry shadow interior',core.sum()>20 and np.all(predicted[core]),pixels=int(core.sum()))
        geometry.append(dict(scene=label,false_shadow_pixels=int((predicted&~truth&receiver).sum()),
            missed_shadow_pixels=int((~predicted&truth&receiver).sum()),unsupported_pixels=int(((a[...,1]==0)&receiver).sum()),
            geometry_shadow_pixels=int(truth.sum()),blocked_receiver_pixels=int((predicted&receiver).sum()),
            baseline_false_shadow_pixels=int(((before[...,0]<.5)&~truth&receiver).sum()),
            baseline_missed_shadow_pixels=int(((before[...,0]>=.5)&truth&receiver).sum()),
            heldout=label.startswith('heldout')))
        for s in (0,.5):
            actual=draw(f'{label}-{s}-fused',shaders[s],f,inputs)
            off=dict(inputs);off['constants']=dict(inputs['constants']);off['constants'][12]=inputs['constants'][12].copy();off['constants'][12][0,0]=0
            unshadowed=draw(f'{label}-{s}-unshadowed',shaders[s],f,off)
            ref=dict(inputs);ref['textures']=dict(inputs['textures']);tex=inputs['textures'][0].copy()
            # Receiver normal alignment is one in these geometry fixtures.
            tex[...,:3]+=cpu_style(f,lamp,strength=s)*a[...,:1];ref['textures'][0]=tex
            expected=draw(f'{label}-{s}-oracle',native,f,ref)
            close(f'{label} {s} native RGBA oracle',actual,expected)
            close(f'{label} {s} alpha preserved',actual[...,3],base[...,3],0)
            if np.any(predicted&receiver):
                close(f'{label} {s} blocked lamp retains native',actual[predicted&receiver],base[predicted&receiver],0)
            check(f'{label} {s} bounded by unshadowed',np.all(actual>=base-3e-6) and np.all(actual<=unshadowed+3e-6))
            if label=='perspective' and s==.5:
                tex=inputs['textures'][0].copy();tex[...,:3]+=cpu_style(f,lamp,strength=s)*(~truth)[...,None];ref['textures'][0]=tex
                ideal=draw('geometry-ideal',native,f,ref);pictures=[unshadowed,actual,ideal]
        print('PASS geometry',label,flush=True)
    for label,settings in [('skin',dict(albedo=(.62,.34,.23))),('normal-map',dict(normal_xy=(.7,.6))),
        ('alpha-half',dict(alpha=.5)),('alpha-zero',dict(alpha=0)),('metal',dict(metal=1)),
        ('wet',dict(wetness=.6)),('type1',dict(material_type=1)),('type2',dict(material_type=2)),('type3',dict(material_type=3))]:
        f,inputs=fixture(compiler,output/(label+'-fixture'),**settings);inputs['constants'][13]=[[*lamp,9],[1,1,1,18]]
        base=draw(label+'-native',native,f,inputs);a=audit_draw(label+'-audit',f,inputs)
        actual=draw(label+'-fused',shaders[.5],f,inputs)
        alignment=-f['normal'][...,2];ref=dict(inputs);ref['textures']=dict(inputs['textures']);tex=inputs['textures'][0].copy()
        tex[...,:3]+=cpu_style(f,lamp,strength=.5)*a[...,:1]/alignment[...,None];ref['textures'][0]=tex
        close(label+' final normal/material RGBA oracle',actual,draw(label+'-oracle',native,f,ref))
        close(label+' alpha preserved',actual[...,3],base[...,3],0)
        blocked=(a[...,0]==0)&~f['plate']
        close(label+' blocked added lamp only',actual[blocked],base[blocked],0)
        if label=='alpha-zero':close('cutout not resurrected',actual,np.zeros_like(actual),0)
    # Continuous b13 controls in the actual native mesh PS, one device per run.
    f,inputs=fixture(compiler,output/'moving-fixture');base=draw('moving-native',native,f,inputs)
    params=[[[x,.5,1.5,9],[1,1,1,18]] for x in np.linspace(-.8,-.5,13)]
    sequence=render(shaders[.5],output/'moving-fused',f['width'],f['height'],**inputs,animation=(13,params))[:,0]
    ai=dict(inputs);ai['vertex']=f['audit_vertex']
    masks=render(audit,output/'moving-audit',f['width'],f['height'],**ai,animation=(13,params))[:,0]
    old_masks=render(baseline_audit,output/'moving-baseline-audit',f['width'],f['height'],**ai,animation=(13,params))[:,0]
    truth_sequence=np.stack([exact_shadow(f,p[0][:3]) for p in params]).astype(np.float32)
    receiver=f['mask']&~f['plate'];temporal={}
    for label,values in [('depth-axis',old_masks),('plane-distance',masks)]:
        predicted=1-values[...,0]
        temporal[label]=dict(visibility_mae=float(np.abs(predicted-truth_sequence)[:,receiver].mean()),
            visibility_change_error=float(np.abs(np.diff(predicted,axis=0)-np.diff(truth_sequence,axis=0))[:,receiver].mean()))
    for i,p in enumerate(params):
        ref=dict(inputs);ref['textures']=dict(inputs['textures']);tex=inputs['textures'][0].copy()
        tex[...,:3]+=cpu_style(f,p[0][:3],strength=.5)*masks[i,...,:1];ref['textures'][0]=tex
        close(f'moving frame {i} native oracle',sequence[i],draw(f'moving-oracle-{i}',native,f,ref))
    check('moving lamp changes final material',np.max(np.abs(sequence[-1]-sequence[0]))>.01)
    temporal={'flat':temporal}
    # Exercise motion where plane-distance refinement actually changes results;
    # the flat sequence alone cannot establish stability of the new check.
    tilted,tilted_inputs=fixture(compiler,output/'tilted-moving-fixture',angle=55)
    tilted_audit=dict(tilted_inputs);tilted_audit['vertex']=tilted['audit_vertex']
    tilted_masks=render(audit,output/'tilted-moving-audit',tilted['width'],tilted['height'],**tilted_audit,animation=(13,params))[:,0]
    tilted_old=render(baseline_audit,output/'tilted-moving-old',tilted['width'],tilted['height'],**tilted_audit,animation=(13,params))[:,0]
    tilted_actual=render(shaders[.5],output/'tilted-moving-fused',tilted['width'],tilted['height'],**tilted_inputs,animation=(13,params))[:,0]
    tilted_truth=np.stack([exact_shadow(tilted,p[0][:3]) for p in params]).astype(np.float32)
    tilted_receiver=tilted['mask']&~tilted['plate'];temporal['tilted-55']={}
    for label,values in [('depth-axis',tilted_old),('plane-distance',tilted_masks)]:
        predicted=1-values[...,0]
        temporal['tilted-55'][label]=dict(visibility_mae=float(np.abs(predicted-tilted_truth)[:,tilted_receiver].mean()),
            visibility_change_error=float(np.abs(np.diff(predicted,axis=0)-np.diff(tilted_truth,axis=0))[:,tilted_receiver].mean()))
    for i,p in enumerate(params):
        ref=dict(tilted_inputs);ref['textures']=dict(tilted_inputs['textures']);tex=tilted_inputs['textures'][0].copy()
        tex[...,:3]+=cpu_style(tilted,p[0][:3],strength=.5)*tilted_masks[i,...,:1];ref['textures'][0]=tex
        close(f'tilted moving frame {i} native oracle',tilted_actual[i],draw(f'tilted-moving-oracle-{i}',native,tilted,ref))
    inputs['constants'][13]=[[*lamp,9],[1,1,1,18]]
    # Missing geometry is a measured limitation, not a success at casting shadows.
    missing=dict(inputs);missing['textures']=dict(inputs['textures']);depth=inputs['textures'][2].copy();depth[...,0]=depth[0,0,0];missing['textures'][2]=depth
    a=audit_draw('missing-audit',f,missing);truth=interior(exact_shadow(f,lamp))&~f['plate']
    check('hidden geometry remains a leak',truth.sum()>20 and np.all(a[truth,0]==1),leaked_pixels=int(truth.sum()))
    invalid=dict(inputs);invalid['textures']=dict(inputs['textures']);depth=inputs['textures'][2].copy();depth[...,0]=1;invalid['textures'][2]=depth
    a=audit_draw('invalid-depth-audit',f,invalid)
    check('far-plane depth explicitly unsupported',np.all(a[...,1]==0) and np.all(a[...,0]==1))
    singular=dict(inputs);singular['constants']=dict(inputs['constants']);singular['constants'][12]=inputs['constants'][12].copy();singular['constants'][12][6:10]=0
    a=audit_draw('singular-audit',f,singular);check('singular inverse projection unsupported',np.all(a[...,1]==0))
    # Verify fallback through the full native PS as well as diagnostic masks.
    for label,case in [('missing',missing),('invalid-depth',invalid),('singular',singular)]:
        actual=draw(label+'-fused',shaders[.5],f,case)
        off=dict(case);off['constants']=dict(case['constants']);off['constants'][12]=case['constants'][12].copy();off['constants'][12][0,0]=0
        close(label+' final material unshadowed fallback',actual,draw(label+'-off',shaders[.5],f,off))
    zero=dict(inputs);zero['constants']=dict(inputs['constants']);zero['constants'][13]=[[*lamp,9],[1,1,1,0]]
    close('zero dynamic intensity preserves native',draw('zero-fused',shaders[.5],f,zero),base,0)
    outside=dict(inputs);outside['constants']=dict(inputs['constants']);outside['constants'][13]=[[8,.5,1.5,12],[1,.8,.6,18]]
    a=audit_draw('offscreen-audit',f,outside)
    check('offscreen limitation flagged',np.count_nonzero((a[...,1]==0)&receiver)>100)
    ref=dict(outside);ref['textures']=dict(outside['textures']);tex=outside['textures'][0].copy()
    tex[...,:3]+=cpu_style(f,[8,.5,1.5],color=[1,.8,.6],radius=12,strength=.5)*a[...,:1];ref['textures'][0]=tex
    close('offscreen full material oracle',draw('offscreen-fused',shaders[.5],f,outside),draw('offscreen-reference',native,f,ref))
    # Actual native target format and source-alpha blend, not guessed game state.
    f,inputs=fixture(compiler,output/'blend-fixture',alpha=.5);inputs['constants'][13]=[[*lamp,9],[1,1,1,18]]
    actual=draw('blend-source',shaders[.5],f,inputs);blended=draw('blend-result',shaders[.5],f,inputs,blend='source-alpha')
    close('native alpha blend',blended[...,:3],actual[...,:3]*actual[...,3:4])
    fp16=draw('fp16',shaders[.5],f,inputs,target_format='rgba16f')
    ulp=np.spacing(np.maximum(np.abs(actual),2**-14).astype(np.float16)).astype(np.float32)
    check('FP16 one storage ULP',np.all(np.abs(actual-fp16)<=ulp),maximum_ulp_error=float((np.abs(actual-fp16)/ulp).max()))
    panel=Image.new('RGB',(960,230),'#191d23');labels=ImageDraw.Draw(panel)
    for i,(title,pixels) in enumerate(zip(('Unshadowed mesh','Depth-based occlusion','Geometry reference'),pictures)):
        labels.text((i*320+8,8),title,fill='white');panel.paste(Image.fromarray(np.uint8(np.clip(pixels[...,:3],0,1)*255)).resize((320,200)),(i*320,30))
    panel.save(output/'mesh-shadow-comparison.png')
    totals={}
    for heldout in (False,True):
        rows=[r for r in geometry if r['heldout']==heldout]
        totals['heldout' if heldout else 'initial']=dict(
            baseline_errors=sum(r['baseline_false_shadow_pixels']+r['baseline_missed_shadow_pixels'] for r in rows),
            candidate_errors=sum(r['false_shadow_pixels']+r['missed_shadow_pixels'] for r in rows))
    report=dict(check_count=len(checks),all_passed=True,checks=checks,geometry=geometry,temporal=temporal,geometry_totals=totals,
        source_sha256={name:digest((output/name).read_bytes()) for name in names},
        candidate_sha256={str(s):digest(path.read_bytes()) for s,path in shaders.items()},
        game_package_created=False,game_runtime_verified=False,performance_verified=False,eligible_for_default=False,
        limits=['Synthetic plane VS with explicit 1e-5 raster-depth bias; no actual game mesh/skinning replay',
            'Synthetic b12 projection/inverse projection/viewport and b13 lamp; game resource values still unverified',
            'Nearest visible depth cannot describe hidden/offscreen/transparent geometry; hard shadows, no temporal stabilization',
            'Plane-normal refinement uses shading normals, which need not equal geometry normals',
            'Standard-depth native material tested; no reverse-Z support inferred for its original discard rule',
            'No two-path overlap or real hardware cost measured'])
    (output/'report.json').write_bytes(encoded(report));print(json.dumps(dict(checks=len(checks),geometry_totals=totals,temporal=temporal),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--extraction',type=Path,default=ROOT/'artifacts/client-2026.09.15')
    p.add_argument('--decompiler',type=Path,default=ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe')
    a=p.parse_args();run(a.output,a.extraction,a.decompiler)
