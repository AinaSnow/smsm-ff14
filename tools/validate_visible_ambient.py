"""Exact currently visible hair/dress material fixtures; synthetic geometry only."""
from copy import deepcopy
from pathlib import Path
import numpy as np
from validate_forward_light import fixture as hair_fixture

HAIR='1c5c89ac035f9a44'
DRESS='e86f0d4916054deb'


def fixture(compiler,work,target,**settings):
    f,old=hair_fixture(compiler,work,**settings)
    if target==HAIR:
        old['textures'][1][...,:3]=0
        return f,old
    if target!=DRESS:raise ValueError('Unreviewed visible fixture')
    height,width=f['height'],f['width']
    tex={i:np.broadcast_to(v,(height,width,4)).astype(np.float32).copy() for i,v in {
        0:(.25,.25,.25,0),1:(0,0,0,0),2:(0,.6,0,0),3:(.8,.8,.8,0),
        5:(.5,.5,0,0),6:(.5,.5,.5,1),7:(1,1,1,1),8:(0,0,0,0),13:(1,1,1,1)}.items()}
    table=np.zeros((32,8,4),np.float32)
    table[:,1]=(*settings.get('albedo',(.8,.8,.8)),1)
    table[:,2]=(0,0,0,1)
    table[:,3]=(1,0,1,0)
    table[:,4]=(0,0,0,1)
    table[:,6]=(0,-1/64,0,0)
    table[:,7]=(1,0,0,1)
    tex[9]=table
    cb=deepcopy(old['constants']);cb[0]=np.zeros((20,4),np.float32);cb[0][11,1]=1
    cb[5]=np.ones((1,4),np.float32)
    tiles=np.ones((1,2,2,4),np.float32)
    inp=dict(textures=tex,constants=cb,structured={4:old['structured'][3]},cubes={12:old['cubes'][7]},
             arrays={10:tiles,11:tiles.copy()},vertex=old['vertex'])
    return f,inp


def run(output):
    import json
    from shader_compile import Compiler
    from offline_render import render
    from patch_native_ambient import build
    from validate_native_ambient import table,cpu_weight
    from manage_preview import ROOT,digest
    output.mkdir(parents=True,exist_ok=False);compiler=Compiler();checks=[];variants=[];serial=0
    def check(name,a,b,tolerance=5e-6):
        error=float(np.max(np.abs(a-b)))
        if not np.isfinite(a).all() or not np.isfinite(b).all() or error>tolerance:raise AssertionError((name,error))
        checks.append(dict(name=name,passed=True,max_abs_error=error))
    for target in (HAIR,DRESS):
        code,meta=build(ROOT/'artifacts/client-2026.09.15',output/target/'patch',compiler,ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe',target)
        original=code.parent/'original.bin'
        f,inputs=fixture(compiler,output/target/'geometry',target,width=33,height=25)
        def configure(regions,strength=1):
            p=deepcopy(inputs);p['constants'][6][:3,3]=(.06,.08,.12);p['constants'][6][4,2]=1
            p['region_copy']=(14,regions[None]);p['constants'][8]=np.array([[strength,0,0,0]],np.float32);return p
        def draw(name,shader,p,fmt='rgba32f'):
            nonlocal serial
            serial+=1
            return render(shader,output/target/(str(serial)+'-'+name),f['width'],f['height'],**p,target_format=fmt)[0,0]
        inp=configure(table());base=draw('baseline',original,inp)
        if not np.all(base[...,:3]>.01):raise AssertionError('Fixture failed to exercise visible material')
        check(target+' global-only fallback',draw('global-only',code,inp),base)
        for kind in (1,2,3):
            entry={'color':(.3,.08,.02),'type':kind,'inverse_extent':(.5,.7,1),'minus':(.4,2,3),'plus':(4,1.5,.7)}
            regions=table([entry]);inp=configure(regions)
            actual=draw('region-'+str(kind),code,inp)
            delta=cpu_weight(entry,f['position'])[...,None]*(np.array(entry['color'])-np.array([.06,.08,.12]))
            # Independent geometry -> native direct-diffuse INPUT oracle. Pure
            # diffuse fixtures have AO=1 and zero reflection/specular, so adding
            # 0.6 * regional SH delta follows the original combine equation.
            oracle=deepcopy(inp);oracle['textures'][0][...,:3]+=(.6*delta).astype(np.float32)
            expected=draw('native-oracle-'+str(kind),original,oracle)
            check(target+' region '+str(kind)+' full material oracle',actual,expected)
            if kind==2:
                if np.max(np.abs(actual[...,:3]-base[...,:3]))<.01:raise AssertionError('No meaningful test response')
                off=configure(regions,0);check(target+' disabled',draw('disabled',code,off),base)
                half=configure(regions,.5);oracle=deepcopy(half);oracle['textures'][0][...,:3]+=(.3*delta).astype(np.float32)
                check(target+' half strength oracle',draw('half',code,half),draw('half-oracle',original,oracle))
                attenuated=configure(regions);attenuated['constants'][6][4]=(.03,0,0,0)
                oracle=deepcopy(attenuated);oracle['textures'][0][...,:3]+=(.6*(.03*5)**2*delta).astype(np.float32)
                check(target+' native attenuation retained',draw('attenuated',code,attenuated),draw('attenuated-oracle',original,oracle))
                stored=draw('fp16',code,inp,'rgba16f')
                check(target+' FP16 output',stored,actual.astype(np.float16).astype(np.float32),.00098)
        # Nonzero reflection and alternate normals/SH: equal coefficients must
        # produce the original result without corrupting cube/array bindings.
        inp=configure(table([{'color':(.06,.08,.12),'type':2,'inverse_extent':(.5,.7,1)}]))
        inp['textures'][4 if target==HAIR else 5][...,:3]=(.8,.4,.4)
        coefficients=np.array([[.03,-.02,.01,.08],[-.01,.02,.04,.1],[.02,.01,-.03,.12]],np.float32)
        inp['constants'][6][:3]=coefficients
        for start in (4,16):inp['region_copy'][1][0,start:start+3]=coefficients
        cube_slot=7 if target==HAIR else 12;inp['cubes'][cube_slot][...,:3]=.25
        inp['constants'][1][2,0]=.3  # Exercise native alpha/bloom encoding.
        if target==DRESS:
            inp['textures'][9][:,6]=(0,0,.5,0) # Nonzero array layer and tile weight.
            inp['arrays'][10][...]=(.45,.65,.8,1);inp['arrays'][11][...]=(.7,.6,.5,1)
        original_rich=draw('rich-original',original,inp)
        check(target+' normal SH reflection and material tables retained',draw('rich-noop',code,inp),original_rich)
        # Both reviewed opaque paths have native discard controlled by this
        # material threshold; preserve the entire original rejected output.
        reject=configure(table([{'color':(.3,.08,.02),'type':2}]))
        reject['constants'][0][0,3]=2
        check(target+' native discard',draw('discard',code,reject),np.zeros_like(base),0)
        missing=configure(table());del missing['region_copy']
        check(target+' missing region fallback',draw('missing',code,missing),base)
        invalid=table([{'color':(.3,.08,.02),'type':2}]);invalid.view(np.uint32)[14,3]=9
        check(target+' invalid region fallback',draw('invalid',code,configure(invalid)),base)
        meta['file']=code.relative_to(output).as_posix();variants.append(meta)
    result={'all_passed':True,'variants':variants,'checks':checks,'draw_jobs':serial,
            'game_binding_verified':False,'game_visual_benefit_verified':False,'performance_verified':False}
    (output/'bundle.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'checks':len(checks),'draw_jobs':serial,'all_passed':True}))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);run(p.parse_args().output)
