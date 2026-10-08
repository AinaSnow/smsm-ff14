"""Render native material composition against an independent lamp-input oracle.

Synthetic G-buffers, not extracted scene pixels. Tests actual Draw/readback,
including FP16 final output and the earlier R11G11B10 intermediate route.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from manage_preview import ROOT, digest, encoded
from offline_render import render
from patch_material_light import load_original, compile_helper, patch
from shader_compile import Compiler
from validate_single_light import fixture, cpu_light


def material_inputs(f, albedo=(.8,.8,.8), metal=0, ao=1, spec=0, emission=0, exposure=1, environment=0, alpha_weights=(0,0)):
    shape=(f['height'],f['width'],4)
    tex={slot:np.broadcast_to(value,shape).astype(np.float32).copy() for slot,value in {
        1:(1,0,0,1-ao), 3:(.3984375,.3984375,.3984375,0), 4:(spec,spec,spec,0),
        6:(.5 if spec or environment else 0,.6,metal,0),7:(*np.sqrt(albedo),0),8:(0,0,0,0),
        9:(emission,emission,emission,1 if emission else 0)}.items()}
    tex[5]=f['textures'][3].copy()
    tex[10]=np.concatenate((f['position'],np.ones((*shape[:2],1))),-1).astype(np.float32)
    common=np.zeros((4,4),np.float32); common[0]=f['constants'][0][0]; common[3,0]=exposure
    common[2,:2]=alpha_weights
    camera=np.zeros((6,4),np.float32); camera[:3]=f['constants'][1][:3]; camera[3:,:3]=camera[:3,:3].T
    ambient=np.zeros((772,4),np.float32); ambient.view(np.uint32)[0,0]=1
    ambient[0,1]=1; ambient[7,3]=1; ambient[9]=(1,0,1,0)
    ambient[10:13,:3]=np.eye(3)
    cube=np.zeros((6,2,2,4),np.float32); cube[...,:3]=environment; cube[...,3]=1
    material=np.zeros((256,32),np.float32); material[:,2]=1
    return dict(textures=tex,constants={0:common,1:camera,2:ambient,3:np.zeros((1,4),np.float32)},
                structured={2:(128,material.tobytes())},cubes={0:cube})


def run(output, extraction, decompiler):
    output.mkdir(parents=True,exist_ok=False)
    compiler=Compiler(ROOT/'d3dcompiler_46.dll'); original=load_original(extraction)
    original_path=output/'original.bin'; original_path.write_bytes(original)
    checks=[]; measurements=[]
    def check(name,actual,expected,tolerance=3e-6):
        error=float(np.max(np.abs(actual-expected)))
        ok=bool(np.isfinite(actual).all() and np.isfinite(expected).all() and error<=tolerance)
        checks.append(dict(name=name,max_abs_error=error,tolerance=tolerance,passed=ok))
        if not ok: raise AssertionError(f'{name}: {error} > {tolerance} or nonfinite')
    def compile_source(name,text):
        source=output/(name+'.hlsl'); source.write_text(text)
        data,warnings=compiler.compile(source)
        if warnings: raise ValueError(warnings)
        path=output/(name+'.bin'); path.write_bytes(data); return path
    def candidate(name,position=(0,0,0),color=(1,1,1),intensity=2,radius=8):
        helper=compile_helper(output/(name+'-helper'),compiler,position,color,intensity,radius)
        _,data=patch(original,helper,output/(name+'-audit'),decompiler,compiler)
        path=output/(name+'.bin'); path.write_bytes(data); return path
    def draw(name,shader,f,inputs,fmt='rgba32f'):
        return render(shader,output/name,f['width'],f['height'],**inputs,target_format=fmt,viewport=f['viewport'])[0,0]
    # Exercise the new cube-array binding and half-float readback independently.
    cube_ps=compile_source('cube-calibration','TextureCubeArray<float4> t:register(t0); SamplerState s:register(s0); '
        'cbuffer C:register(b0){float4 direction;} float4 main(float4 p:SV_POSITION):SV_TARGET{return t.SampleLevel(s,direction,0);}')
    faces=np.array([[1,0,0,.25],[0,1,0,.5],[0,0,1,.75],[1,1,0,1],[1,0,1,2],[0,1,1,4]],np.float32)
    directions=np.array([[1,0,0,0],[-1,0,0,0],[0,1,0,0],[0,-1,0,0],[0,0,1,0],[0,0,-1,0]],np.float32)
    cube=np.broadcast_to(faces[:,None,None,:],(6,2,2,4)).copy()
    for fmt in ('rgba32f','rgba16f'):
        actual=render(cube_ps,output/('cube-'+fmt),4,3,cubes={0:cube},animation=(0,directions[:,None,:]),target_format=fmt)[:,0]
        check('cube faces and alpha '+fmt,actual,np.broadcast_to(faces[:,None,None,:],actual.shape),0)
    lamp=candidate('lamp'); zero=candidate('zero',intensity=0)
    check('zero intensity byte identity',np.frombuffer(zero.read_bytes(),np.uint8),np.frombuffer(original,np.uint8),0)
    f=fixture(width=64,height=40,geometry='sphere',rotation=37)
    materials=[('white',{}),('skin-swatch',{'albedo':(.62,.34,.23)}),('blue-cloth',{'albedo':(.25,.35,.65)}),
               ('metal',{'metal':1,'spec':.2,'environment':.3}),('mixed-metal',{'metal':.5,'spec':.1,'environment':.2}),
               ('occluded',{'ao':.25}),('ao-zero',{'ao':0}),('emissive',{'emission':.4}),('exposure',{'exposure':1.5}),
               ('specular-alpha',{'spec':.3,'environment':.2,'alpha_weights':(.8,.4)}),
               ('emission-alpha',{'emission':.4,'alpha_weights':(.8,.4)})]
    preview=[]
    for name,settings in materials:
        inputs=material_inputs(f,**settings)
        baseline=draw(name+'-base',original_path,f,inputs)
        actual=draw(name+'-injected',lamp,f,inputs)
        inputs['textures'][3][...,:3]+=cpu_light(f).astype(np.float32)
        expected=draw(name+'-oracle',original_path,f,inputs)
        check(name+' native material oracle RGBA',actual,expected)
        if name.endswith('-alpha'):
            if not np.all(actual[...,3]>0): raise AssertionError('Alpha fixture did not exercise native nonzero alpha')
            checks.append(dict(name=name+' nonzero native alpha exercised',passed=True))
        if name in ('white','skin-swatch','blue-cloth','occluded','ao-zero','emissive','exposure'):
            albedo=np.array(settings.get('albedo',(.8,.8,.8)))
            analytic=np.sqrt(albedo*(.3984375+cpu_light(f))*settings.get('ao',1)+settings.get('emission',0)**2)*settings.get('exposure',1)
            check(name+' independent diffuse equation',actual[...,:3],analytic)
        if name in ('metal','ao-zero'): check(name+' diffuse suppressed',actual,baseline,0)
        if name in ('white','skin-swatch','blue-cloth'):
            delta_linear=actual[...,:3]**2-baseline[...,:3]**2
            expected_delta=cpu_light(f)*np.array(settings.get('albedo',(.8,.8,.8)))
            check(name+' linear color response',delta_linear,expected_delta,2e-6)
            preview.append(np.concatenate((baseline[...,:3],actual[...,:3],np.clip((actual-baseline)[...,:3]*40,0,1)),1))
        print('PASS material',name,flush=True)
    for name,settings in [('tilt',{'geometry':'tilt'}),('right-handed',{'right_handed':True}),
                           ('offset-viewport',{'width':80,'height':60,'viewport':(7,5,61,43)}),
                           ('rotated',{'rotation':-63}),('jitter',{'jitter':(.013,-.021)})]:
        geometry=fixture(**settings); inputs=material_inputs(geometry)
        actual=draw('geometry-'+name,lamp,geometry,inputs)
        inputs['textures'][3][...,:3]+=cpu_light(geometry).astype(np.float32)
        expected=draw('geometry-oracle-'+name,original_path,geometry,inputs)
        check('geometry '+name,actual,expected)
    # Baked game variants are checked through the COMPLETE native composition.
    for name,pos,col,intensity,radius in [('left',(-2,0,1),(1,.8,.6),3,8),('right',(2,0,1),(.6,.8,1),3,8),
            ('short',(0,0,2),(1,1,1),4,2),('behind',(0,0,7),(1,1,1),2,8),('range',(0,0,0),(1,1,1),2,1)]:
        path=candidate(name,pos,col,intensity,radius); inputs=material_inputs(f)
        actual=draw(name+'-injected',path,f,inputs)
        inputs['textures'][3][...,:3]+=cpu_light(f,pos,col,intensity,radius).astype(np.float32)
        expected=draw(name+'-oracle',original_path,f,inputs)
        check(name+' native control oracle',actual,expected)
    # Continuous controls use b13 ONLY in the standalone offline helper.
    dynamic=compile_source('dynamic',(ROOT/'tools/patches/material_light.hlsl').read_text())
    params=np.array([[[x,0,1,8],[1,1,1,12]] for x in np.linspace(-3,3,13)],np.float32)
    inputs=material_inputs(f)
    moving=render(dynamic,output/'moving',f['width'],f['height'],**inputs,animation=(13,params))[:,0]
    centroids=[]
    for i,p in enumerate(params):
        check(f'moving frame {i}',moving[i,...,:3],cpu_light(f,p[0,:3],p[1,:3],p[1,3],p[0,3]))
        energy=moving[i,...,:3].mean(-1); centroids.append(float((energy*np.arange(f['width'])).sum()/energy.sum()))
    if not np.all(np.diff(centroids)>0): raise AssertionError('Light footprint did not move right')
    checks.append(dict(name='moving footprint monotonic',passed=True,pixels=centroids))
    repeated=render(dynamic,output/'repeat',f['width'],f['height'],**inputs,animation=(13,params[[0,12,0]]))[:,0]
    check('repeat after motion',repeated[0],repeated[2],0)
    invalid=material_inputs(f)
    invalid['textures'][10][:,:16,:3]=0
    invalid['textures'][10][:,16:32,:3]=np.nan
    invalid['textures'][5][:,32:48,:3]=.5
    invalid['textures'][5][:,48:,:3]=np.nan
    invalid['constants'][13]=params[6]
    actual=draw('invalid-helper',dynamic,f,invalid)
    check('invalid geometry contributes zero (helper only)',actual,np.zeros_like(actual),0)
    # Quantize the actual old intermediate with a GPU texture-copy pass, then
    # feed both routes through native composition into the real FP16 RT format.
    copy=compile_source('copy','Texture2D<float4> t:register(t0); float4 main(float4 p:SV_POSITION):SV_TARGET{return t.Load(int3(p.xy,0));}')
    for brightness in (.25,1,4,16):
        inputs=material_inputs(f); inputs['textures'][3][...,:3]*=brightness
        def pack(name,tex): return render(copy,output/name,f['width'],f['height'],textures={0:tex},target_format='r11g11b10')[0,0]
        base=pack(f'packed-base-{brightness}',inputs['textures'][3]); inputs['textures'][3]=base.copy()
        baseline=draw(f'precision-base-{brightness}',original_path,f,inputs,'rgba16f')
        new=draw(f'precision-new-{brightness}',lamp,f,inputs,'rgba16f')
        inputs['textures'][3][...,:3]+=cpu_light(f).astype(np.float32)
        ideal=draw(f'precision-ideal-{brightness}',original_path,f,inputs,'rgba16f')
        reference=draw(f'precision-float32-{brightness}',original_path,f,inputs)
        old_texture=pack(f'packed-light-{brightness}',inputs['textures'][3]); inputs['textures'][3]=old_texture
        old=draw(f'precision-old-{brightness}',original_path,f,inputs,'rgba16f')
        check(f'FP16 native oracle {brightness}',new,ideal,0)
        new_mse=float(np.mean((new[...,:3]-reference[...,:3])**2)); old_mse=float(np.mean((old[...,:3]-reference[...,:3])**2))
        if new_mse>=old_mse: raise AssertionError('New route failed to improve precision')
        checks.append(dict(name=f'precision improvement {brightness}',passed=True))
        eligible=np.any(cpu_light(f)>1e-7,axis=-1)
        measurements.append(dict(brightness_scale=brightness,old_mse=old_mse,new_mse=new_mse,eligible_pixels=int(eligible.sum()),
            old_lost_all_channels=float(np.all(old[...,:3]==baseline[...,:3],-1)[eligible].mean()),
            new_lost_all_channels=float(np.all(new[...,:3]==baseline[...,:3],-1)[eligible].mean())))
    panel=Image.new('RGB',(768,564),'#16191d'); labels=ImageDraw.Draw(panel)
    for i,label in enumerate(('Native baseline','Material-stage lamp','Positive difference x40')): labels.text((i*256+8,8),label,fill='white')
    for i,(row,label) in enumerate(zip(preview,('White swatch','Skin-colored swatch (not game skin)','Blue cloth swatch'))):
        y=28+i*176; labels.text((8,y),label,fill='white')
        panel.paste(Image.fromarray((np.clip(row,0,1)*255).astype(np.uint8)).resize((768,152)),(0,y+20))
    panel.save(output/'material-comparison.png')
    report=dict(check_count=len(checks),all_passed=True,checks=checks,precision=measurements,
        original_sha256=digest(original),patched_sha256=digest(lamp.read_bytes()),
        backend='D3D11 WARP actual Draw/Copy/Map',game_runtime_verified=False,performance_verified=False,
        limits=['Synthetic material swatches are not actual game skin/cloth captures','Only audited 415a922293923fa4 material path',
                'Dynamic b13 is offline only; game variant bakes constants','No occlusion, transparency or world-locked control',
                'Native AO/specular/emission/alpha/exposure logic retained; lamp does not implement its own specular lobe',
                'Point samplers, one cube mip, simplified ambient fixture; no gameplay coverage or hardware cost evidence'])
    (output/'report.json').write_bytes(encoded(report))
    print(json.dumps(dict(checks=len(checks),precision=measurements),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('output',type=Path)
    p.add_argument('--extraction',type=Path,default=ROOT/'artifacts/client-2026.09.15')
    p.add_argument('--decompiler',type=Path,default=ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe')
    a=p.parse_args(); run(a.output,a.extraction,a.decompiler.resolve())
