"""Actual visibility and native material composition, optionally fused in one draw.

Separate GPU passes provide the reference; --fused uses explicit offline b12/b13.
No game package or GPU cost claim. Geometry oracle includes all edge pixels.
"""
import argparse
import json
import shutil
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from manage_preview import ROOT,encoded,digest
from offline_render import render
from shader_compile import Compiler
from patch_material_light import load_original
from validate_light_visibility import scene,exact_shadow,interior
from validate_material_light import material_inputs
from validate_single_light import cpu_light,fixture


def visibility_constants(f,enable=1,bias=.025,thickness=.35,steps=96):
    projection=np.linalg.inv(f['constants'][1][14:18].astype(float))
    vx,vy,vw,vh=f['viewport'] or (0,0,f['width'],f['height'])
    return np.vstack(([enable,bias,thickness,steps],projection,
        [vw/(2*f['width']),-vh/(2*f['height']),(vx+vw/2)/f['width'],(vy+vh/2)/f['height']])).astype(np.float32)


def run(output,extraction,bias=.025,thickness=.35,steps=96,fused=False):
    if not np.isfinite([bias,thickness]).all() or not 0<=bias<thickness or not isinstance(steps,int) or not 1<=steps<=128:
        raise ValueError('Finite 0 <= bias < thickness and 1..128 integer steps required')
    output.mkdir(parents=True,exist_ok=False);compiler=Compiler(ROOT/'d3dcompiler_46.dll')
    for name in ('material_light.hlsl','material_visibility.hlsl','visibility_march.hlsl'):
        shutil.copy2(ROOT/'tools/patches'/name,output/name)
    shaders={}
    for mode in (0,1):
        for audit in (0,1):
            name=f'mode{mode}-audit{audit}';source=output/(name+'.hlsl')
            source.write_text(f'#define MATERIAL_PLANE_REFINE {mode}\n#define MATERIAL_VISIBILITY_AUDIT {audit}\n#include "material_visibility.hlsl"\n')
            data,warnings=compiler.compile(source)
            if warnings:raise ValueError(warnings)
            shaders[mode,audit]=output/(name+'.bin');shaders[mode,audit].write_bytes(data)
    original=output/'original-material.bin';original.write_bytes(load_original(extraction))
    fused_shaders={}
    if fused:
        from offline.fuse_material_visibility import fuse
        decompiler=ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe'
        for mode in (0,1):
            source=output/f'fused-helper-{mode}.hlsl'
            source.write_text(f'#define MATERIAL_PLANE_REFINE {mode}\n#define MATERIAL_VISIBILITY_ADD_ONLY 1\n#include "material_visibility.hlsl"\n')
            data,warnings=compiler.compile(source)
            if warnings:raise ValueError(warnings)
            fused_shaders[mode]=fuse(original.read_bytes(),data,output/f'fused-{mode}',decompiler,compiler)
    checks=[];rows=[];pictures=[]
    def check(name,passed,**metrics):
        checks.append(dict(name=name,passed=bool(passed),**metrics))
        if not passed:raise AssertionError(f'{name}: {metrics}')
    def close(name,a,b,tol=3e-6):
        error=float(np.max(np.abs(a-b)))
        check(name,np.isfinite(a).all() and np.isfinite(b).all() and error<=tol,error=error,tolerance=tol)
    def setup(f,lamp,enable=1,**settings):
        inputs=material_inputs(f)
        inputs['constants'][12]=visibility_constants(f,enable,**dict(dict(bias=bias,thickness=thickness,steps=steps),**settings))
        inputs['constants'][13]=[[*lamp,9],[1,1,1,18]]
        return inputs
    def draw(name,shader,f,inputs,**kwargs):
        return render(shader,output/name,f['width'],f['height'],**inputs,viewport=f['viewport'],**kwargs)[0,0]
    def compose(name,f,inputs,diffuse):
        data=dict(inputs);data['textures']=dict(inputs['textures']);data['textures'][3]=diffuse
        return draw(name,original,f,data)
    configs=[('flat',{}),('tilted',dict(angle=25)),('grazing',dict(angle=65)),('thin',dict(half_size=(.08,.65))),
        ('high-resolution',dict(width=256,height=160)),('jitter',dict(jitter=(.013,-.021))),
        ('reverse-z',dict(reverse=True)),('right-handed',dict(right_handed=True)),('viewport',dict(viewport=(9,5,108,68)))]
    for label,settings in configs:
        f=scene(**settings);lamp=[-.65,.5,1.5*f['sign']];inputs=setup(f,lamp)
        truth=exact_shadow(f,lamp);receiver=~f['plate']&f['mask']
        baseline=draw(label+'-baseline',original,f,inputs)
        cpu=cpu_light(f,lamp,intensity=18,radius=9)
        ideal_input=inputs['textures'][3].copy();ideal_input[...,:3]+=cpu*(~truth)[...,None]
        ideal=compose(label+'-geometry-reference',f,inputs,ideal_input)
        unshadowed_input=inputs['textures'][3].copy();unshadowed_input[...,:3]+=cpu
        unshadowed=compose(label+'-unshadowed-reference',f,inputs,unshadowed_input)
        off_inputs=setup(f,lamp,enable=0)
        off=draw(label+'-off-input',shaders[1,0],f,off_inputs)
        off_result=compose(label+'-off-material',f,inputs,off)
        close(label+' disabled composition',off_result,unshadowed)
        if fused:
            close(label+' fused disabled visibility',draw(label+'-fused-off',fused_shaders[1],f,off_inputs),unshadowed)
        for mode in (0,1):
            audit=draw(f'{label}-mode{mode}-audit',shaders[mode,1],f,inputs)
            diffuse=draw(f'{label}-mode{mode}-diffuse',shaders[mode,0],f,inputs)
            final=compose(f'{label}-mode{mode}-material',f,inputs,diffuse)
            if fused:
                resident=draw(f'{label}-mode{mode}-fused',fused_shaders[mode],f,inputs)
                close(f'{label} {mode} fused vs separate material',resident,final)
                final=resident
            visibility=audit[...,0];supported=audit[...,1]>.5;shadow=visibility<.5
            predicted_input=inputs['textures'][3].copy();predicted_input[...,:3]+=cpu*visibility[...,None]
            oracle=compose(f'{label}-mode{mode}-oracle',f,inputs,predicted_input)
            close(f'{label} {mode} native composition oracle',final,oracle)
            close(f'{label} {mode} alpha preserved',final[...,3],baseline[...,3],0)
            check(f'{label} {mode} finite bounded output',np.isfinite(final).all() and np.all(final>=baseline-2e-6) and np.all(final<=unshadowed+2e-6))
            core=interior(truth)&receiver&supported
            if label in ('flat','reverse-z','right-handed','jitter','viewport'):
                check(f'{label} {mode} interior actually blocked',core.sum()>30 and np.all(shadow[core]))
            blocked=shadow&receiver
            check(f'{label} {mode} native light survives shadow',blocked.sum()>0 and np.max(np.abs(final[blocked]-baseline[blocked]))==0 and baseline[blocked,:3].min()>0)
            fp=int((shadow&~truth&receiver).sum());fn=int((~shadow&truth&receiver).sum())
            rows.append(dict(scene=label,refine=bool(mode),false_shadow_pixels=fp,missed_shadow_pixels=fn,total_error=fp+fn,
                receiver_pixels=int(receiver.sum()),unsupported_pixels=int((receiver&~supported).sum()),
                final_rgb_mae=float(np.abs(final[...,:3]-ideal[...,:3])[receiver].mean())))
            np.savez(output/f'{label}-mode{mode}-geometry.npz',truth=truth,predicted=shadow,receiver=receiver,supported=supported)
            if label=='flat' and mode==1:pictures=[('Unshadowed',unshadowed),('Screen-space occlusion',final),('Geometry reference',ideal)]
        print('PASS composition',label,flush=True)
    # Colored/native material stages remain downstream of lamp visibility.
    # Only added light is masked; native environment/emission must not be erased.
    f=scene();lamp=[-.65,.5,1.5]
    for label,settings in [('skin-swatch',{'albedo':(.62,.34,.23)}),('blue-cloth',{'albedo':(.25,.35,.65)}),
            ('occluded',{'ao':.25}),('emissive',{'emission':.4,'alpha_weights':(.8,.4)}),
            ('mixed-metal',{'metal':.5,'spec':.1,'environment':.2,'alpha_weights':(.8,.4)})]:
        inputs=material_inputs(f,**settings);inputs['constants'][12]=visibility_constants(f,bias=bias,thickness=thickness,steps=steps)
        inputs['constants'][13]=[[*lamp,9],[1,1,1,18]]
        baseline=draw(label+'-native-base',original,f,inputs)
        audit=draw(label+'-visibility',shaders[1,1],f,inputs)
        diffuse=draw(label+'-diffuse',shaders[1,0],f,inputs)
        actual=compose(label+'-material',f,inputs,diffuse)
        if fused:
            resident=draw(label+'-fused',fused_shaders[1],f,inputs)
            close(label+' fused vs separate RGBA',resident,actual)
            actual=resident
        expected=inputs['textures'][3].copy();expected[...,:3]+=cpu_light(f,lamp,intensity=18,radius=9)*audit[...,:1]
        oracle=compose(label+'-material-oracle',f,inputs,expected)
        close(label+' material RGBA oracle',actual,oracle)
        blocked=(audit[...,0]==0)&~f['plate']
        close(label+' native color and alpha survive blocked lamp',actual[blocked],baseline[blocked],0)
    # Same-device visibility-input animation, followed by original material
    # execution on each readback. No CPU geometry mask enters the tested pass.
    f=scene();receiver=~f['plate'];inputs=setup(f,[-.8,.5,1.5]);params=[];truth=[];ideals=[]
    for i,x in enumerate(np.linspace(-.8,-.5,13)):
        lamp=[x,.5,1.5];params.append([[*lamp,9],[1,1,1,18]]);truth.append(exact_shadow(f,lamp))
        tex=inputs['textures'][3].copy();tex[...,:3]+=cpu_light(f,lamp,intensity=18,radius=9)*(~truth[-1])[...,None]
        ideals.append(compose('motion-reference-'+str(i),f,inputs,tex))
    truth=np.array(truth,dtype=np.float32);ideals=np.stack(ideals);temporal={}
    for mode in (0,1):
        controls=dict(inputs);controls['constants']=dict(inputs['constants']);del controls['constants'][13]
        audit=render(shaders[mode,1],output/f'motion-audit-{mode}',f['width'],f['height'],**controls,animation=(13,params))[:,0]
        textures=render(shaders[mode,0],output/f'motion-diffuse-{mode}',f['width'],f['height'],**controls,animation=(13,params))[:,0]
        finals=np.stack([compose(f'motion-material-{mode}-{i}',f,inputs,tex) for i,tex in enumerate(textures)])
        if fused:
            resident=render(fused_shaders[mode],output/f'motion-fused-{mode}',f['width'],f['height'],**controls,animation=(13,params))[:,0]
            close(f'motion {mode} fused same-device sequence vs separate draws',resident,finals)
            check(f'motion {mode} changing light changes native output',float(np.max(np.abs(resident[-1]-resident[0])))>.01)
            finals=resident
        check(f'motion {mode} finite',np.isfinite(finals).all())
        predicted=1-audit[...,0]
        temporal[str(mode)]=dict(visibility_mae=float(np.abs(predicted-truth)[:,receiver].mean()),
            visibility_change_error=float(np.abs(np.diff(predicted,axis=0)-np.diff(truth,axis=0))[:,receiver].mean()),
            final_rgb_mae=float(np.abs(finals-ideals)[:,receiver,:3].mean()),
            final_rgb_change_error=float(np.abs(np.diff(finals,axis=0)-np.diff(ideals,axis=0))[:,receiver,:3].mean()))
    # Off-screen rays and missing geometry remain explicit unshadowed fallbacks.
    lamp=[2,.5,1.5];inputs=setup(f,lamp)
    audit=draw('offscreen-audit',shaders[1,1],f,inputs);tex=draw('offscreen-diffuse',shaders[1,0],f,inputs)
    unknown=(audit[...,1]==0)&receiver;known=(audit[...,0]==0)&receiver
    cpu=cpu_light(f,lamp,intensity=18,radius=9);expected=inputs['textures'][3].copy();expected[...,:3]+=cpu
    check('offscreen unsupported exposed',unknown.sum()>100,unknown_pixels=int(unknown.sum()))
    close('offscreen unshadowed fallback',tex[unknown],expected[unknown])
    check('known hit retained before offscreen',known.sum()>20 and np.all(audit[known,1]==1))
    if fused:close('fused offscreen fallback and known hit',draw('offscreen-fused',fused_shaders[1],f,inputs),compose('offscreen-native',f,inputs,tex))
    missing=fixture(width=128,height=80);lamp=[-.65,.5,1.5];inputs=setup(missing,lamp)
    tex=draw('missing-occluder',shaders[1,0],missing,inputs)
    physical=interior(exact_shadow(f,lamp));cpu=cpu_light(missing,lamp,intensity=18,radius=9)
    expected=inputs['textures'][3].copy();expected[...,:3]+=cpu
    close('missing geometry remains unshadowed',tex,expected)
    check('missing geometry leak measured',physical.sum()>100 and np.all(tex[physical,:3]>inputs['textures'][3][physical,:3]),leaked_reference_pixels=int(physical.sum()))
    if fused:close('fused missing geometry fallback',draw('missing-fused',fused_shaders[1],missing,inputs),compose('missing-native',missing,inputs,tex))
    inputs=setup(f,lamp);inputs['textures'][10][...,:3]=0
    audit=draw('invalid-position-audit',shaders[1,1],f,inputs)
    tex=draw('invalid-position-diffuse',shaders[1,0],f,inputs)
    check('invalid position marked unsupported',np.all(audit[...,1:3]==0))
    close('invalid position adds no light',tex,inputs['textures'][3],0)
    if fused:close('fused invalid position adds no light',draw('invalid-fused',fused_shaders[1],f,inputs),draw('invalid-native',original,f,inputs),0)
    inputs=setup(f,lamp);inputs['constants'][12][1:5]=0
    audit=draw('singular-projection-audit',shaders[1,1],f,inputs)
    tex=draw('singular-projection-diffuse',shaders[1,0],f,inputs)
    check('singular projection marked unsupported',np.all(audit[...,1]==0))
    expected=inputs['textures'][3].copy();expected[...,:3]+=cpu_light(f,lamp,intensity=18,radius=9)
    close('singular projection uses unshadowed fallback',tex,expected)
    if fused:close('fused singular projection fallback',draw('singular-fused',fused_shaders[1],f,inputs),compose('singular-native',f,inputs,tex))
    totals=[sum(r['total_error'] for r in rows if r['refine']==bool(mode)) for mode in (0,1)]
    check('refinement reduces aggregate error',totals[1]<totals[0],errors=totals)
    if fused:
        f=scene();lamp=[-.65,.5,1.5]
        for label,position,color,intensity,radius in [
                ('zero',lamp,[1,1,1],0,9),('red',lamp,[1,.05,.02],18,9),
                ('cool',lamp,[.2,.4,1],18,9),('short-range',lamp,[1,1,1],18,1),
                ('left',[-2,.5,1.5],[1,1,1],18,9),('bright',lamp,[1,1,1],36,9)]:
            inputs=setup(f,position,enable=0);inputs['constants'][13]=[[*position,radius],[*color,intensity]]
            expected=inputs['textures'][3].copy();expected[...,:3]+=cpu_light(f,position,color=color,intensity=intensity,radius=radius)
            oracle=compose(label+'-control-oracle',f,inputs,expected)
            actual=draw(label+'-control-fused',fused_shaders[1],f,inputs)
            close(label+' fused controls vs CPU/native oracle',actual,oracle)
            if label in ('zero','short-range'):
                close(label+' fused exactly preserves native',actual,draw(label+'-native',original,f,inputs),0)
        # Target-format readback tests the fused path at native scene precision.
        inputs=setup(f,lamp);diffuse=draw('fp16-diffuse',shaders[1,0],f,inputs)
        reference=dict(inputs);reference['textures']=dict(inputs['textures']);reference['textures'][3]=diffuse
        expected=draw('fp16-separate',original,f,reference,target_format='rgba16f')
        actual=draw('fp16-fused',fused_shaders[1],f,inputs,target_format='rgba16f')
        ulp=np.spacing(np.maximum(np.abs(actual),np.abs(expected)).astype(np.float16)).astype(np.float32)
        error=np.abs(actual-expected)
        check('FP16 fused composition within one storage ULP',np.isfinite(actual).all() and np.all(error<=ulp),
              maximum_error=float(error.max()),maximum_ulp_error=float((error/ulp).max()))
    report=dict(check_count=len(checks),all_passed=True,checks=checks,geometry=rows,aggregate_error=totals,temporal=temporal,
        settings=dict(bias=bias,assumed_thickness=thickness,max_steps=steps),
        source_sha256={n:digest((output/n).read_bytes()) for n in ('material_light.hlsl','material_visibility.hlsl','visibility_march.hlsl')},
        game_package_created=False,game_runtime_verified=False,performance_verified=False,
        single_draw_fused=bool(fused),fused_sha256={str(mode):digest(path.read_bytes()) for mode,path in fused_shaders.items()},
        limits=['Actual separate GPU passes with CPU readback/upload between; no game runtime resource binding',
                'Synthetic projection in b12; not available in audited native material interface',
                'Nearest visible surface only; hidden/offscreen/transparent occluders are missing',
                'Finite sampling, tunable bias and assumed thickness; hard edges, no temporal stabilization',
                'Visibility oracle checks implementation; full geometry metrics retain edge failures',
                'No new DoF/reflection quality evidence or actual GPU performance claim'])
    if fused:
        report['limits'][0]='Candidate runs visibility + native material in one GPU draw; separate passes are only comparison references'
        report['limits'].append('Offline b12/b13 are explicit harness resources, absent from native reflection and not game-authorized bindings')
    (output/'report.json').write_bytes(encoded(report))
    panel=Image.new('RGB',(960,230),'#181b20');draw_labels=ImageDraw.Draw(panel)
    for i,(label,pixels) in enumerate(pictures):
        draw_labels.text((i*320+8,8),label,fill='white')
        panel.paste(Image.fromarray(np.uint8(np.clip(pixels[...,:3],0,1)*255)).resize((320,200)),(i*320,30))
    panel.save(output/'material-shadow-comparison.png')
    print(json.dumps(dict(checks=len(checks),aggregate_error=totals,temporal=temporal),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--extraction',type=Path,default=ROOT/'artifacts/client-2026.09.15')
    p.add_argument('--bias',type=float,default=.025);p.add_argument('--thickness',type=float,default=.35)
    p.add_argument('--steps',type=int,default=96)
    p.add_argument('--fused',action='store_true',help='Offline synthetic b12/b13; single-draw native material, never a game package')
    a=p.parse_args();run(a.output,a.extraction,a.bias,a.thickness,a.steps,a.fused)
