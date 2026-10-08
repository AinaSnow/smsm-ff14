"""Actual original/candidate material draws with native ambient region inputs; offline only."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
from PIL import Image
from manage_preview import ROOT, encoded, digest
from patch_native_ambient import build, TARGET
from shader_compile import Compiler
from offline_render import render
from validate_forward_light import fixture


def table(local=None, global_color=(.06,.08,.12)):
    data=np.zeros((772,4),np.float32)
    entries=[] if local is None else local
    data.view(np.uint32)[0,0]=len(entries)+1
    for i,entry in enumerate([*entries,{'color':global_color,'type':0}]):
        b=4+12*i
        data[b:b+3,3]=entry['color'];data[b+3,3]=1
        data[b+4,2]=1;data[b+5,2]=1
        data[b+6:b+9,:3]=np.eye(3)
        data[b+6:b+9,3]=-np.array(entry.get('center',(0,0,5)))
        data[b+6:b+9]*=np.array(entry.get('inverse_extent',(1,1,1)))[:,None]
        data[b+9,:3]=entry.get('minus',(2,2,2))
        data[b+9,3],data[b+10,0],data[b+10,1]=entry.get('plus',(2,2,2))
        data.view(np.int32)[b+10,3]=entry['type']
    return data


def cpu_weight(entry,position):
    # Geometry-based reference: normalized distances to six faces and radial
    # distance to sphere/cylinder surfaces; no shader parsing or shader output.
    q=(position-np.array(entry.get('center',(0,0,5))))*np.array(entry.get('inverse_extent',(1,1,1)))
    inv=np.where(q>=0,entry.get('plus',(2,2,2)),entry.get('minus',(2,2,2)))
    faces=inv*(1-np.abs(q));inside=np.all(faces>0,axis=-1)
    if entry['type']==2:return np.where(inside,np.clip(faces.min(-1),0,1),0)
    radial=q if entry['type']==1 else q[...,[0,2]]
    ranges=inv if entry['type']==1 else inv[...,[0,2]]
    radius=np.linalg.norm(radial,axis=-1)
    direction=np.abs(radial)/np.maximum(radius[...,None],1e-12)
    transition=np.sum(direction/ranges,axis=-1)
    weight=np.where(radius<1e-6,1,np.clip((1-radius)/np.maximum(transition,1e-12),0,1))
    if entry['type']==3:weight=np.minimum(weight,np.clip(faces[...,1],0,1))
    return np.where(inside & (radius<1),weight,0)


def run(output,extraction,decompiler):
    output.mkdir(parents=True,exist_ok=False);compiler=Compiler()
    candidate,meta=build(extraction,output/'patch',compiler,decompiler)
    original=output/'patch/original.bin'
    checks=[];serial=0
    def check(name,a,b,tolerance=4e-6):
        error=float(np.max(np.abs(a-b)))
        ok=bool(np.isfinite(a).all() and np.isfinite(b).all() and error<=tolerance)
        checks.append({'name':name,'passed':ok,'max_abs_error':error,'tolerance':tolerance})
        if not ok:raise AssertionError(f'{name}: {error}')
    def draw(label,shader,f,inputs,fmt='rgba32f'):
        nonlocal serial
        serial+=1
        return render(shader,output/(str(serial)+'-'+label),f['width'],f['height'],**inputs,target_format=fmt)[0,0]
    def configure(inputs,regions,strength=1):
        inp=deepcopy(inputs);inp['region_copy']=(12,regions[None]);inp['constants'][8]=np.array([[strength,0,0,0]],np.float32)
        inp['constants'][6][:3,3]=(.06,.08,.12);inp['constants'][6][4,2]=1
        return inp
    previews=[]
    for name,settings in [('white',{}),('skin',{'albedo':(.62,.34,.23)}),('metal',{'metal':1}),
                          ('wet',{'wetness':.6}),('tilted',{'normal_xy':(.7,.6)}),('alpha',{'alpha':.5}),
                          ('discard',{'alpha':0}),('depth-reject',{'depth':.4}),('type1',{'material_type':1}),
                          ('type2',{'material_type':2}),('type3',{'material_type':3})]:
        f,inputs=fixture(compiler,output/(name+'-geometry'),**settings)
        inp=configure(inputs,table())
        # Keep nonzero reflected environment to exercise unchanged native logic.
        inp['cubes'][7][...,:3]=.15
        base=draw(name+'-base',original,f,inp)
        on=draw(name+'-global',candidate,f,inp)
        check(name+' global-only native identity',on,base)
        local=[{'color':(.3,.08,.02),'type':2,'inverse_extent':(.5,.7,1)}]
        disabled=configure(inp,table(local),0)
        check(name+' disabled identity',draw(name+'-disabled',candidate,f,disabled),base)
    f,inputs=fixture(compiler,output/'spatial-geometry',width=65,height=41)
    inp=configure(inputs,table());base=draw('spatial-base',original,f,inp)
    global_color=np.array([.06,.08,.12])
    for kind in (1,2,3):
        entry={'color':(.3,.08,.02),'type':kind,'inverse_extent':(.5,.7,1),
               'minus':(.4,2,3),'plus':(4,1.5,.7)}
        inp=configure(inputs,table([entry]))
        result=draw('region-'+str(kind),candidate,f,inp)
        weight=cpu_weight(entry,f['position'])
        ambient=global_color+(np.array(entry['color'])-global_color)*weight[...,None]
        expected=np.sqrt(.8*(.25+.6*ambient))
        check('region geometry '+str(kind),result[...,:3],expected)
        check('region alpha retained '+str(kind),result[...,3],base[...,3],0)
        previews.append(result)
    # Blend control changes the one ambient term, not the final encoded image.
    inp['constants'][8][0,0]=.5
    half=draw('half-strength',candidate,f,inp)
    check('linear ambient strength',half[...,:3],np.sqrt((base[...,:3]**2+previews[-1][...,:3]**2)*.5))
    for name,modify in [('count-zero',lambda r:r.view(np.uint32).__setitem__((0,0),0)),
                        ('count-oversized',lambda r:r.view(np.uint32).__setitem__((0,0),65)),
                        ('unknown-type',lambda r:r.view(np.uint32).__setitem__((14,3),9)),
                        ('missing-global',lambda r:r.view(np.uint32).__setitem__((26,3),2))]:
        invalid=table([{'color':(.3,.08,.02),'type':2}]);modify(invalid)
        invalid_inputs=configure(inputs,invalid)
        check(name+' falls back',draw(name,candidate,f,invalid_inputs),base)
    missing=configure(inputs,table());missing.pop('region_copy')
    check('missing region SRV falls back',draw('missing-regions',candidate,f,missing),base)
    mismatch=configure(inputs,table(global_color=(.8,.6,.4)))
    check('global-only differing object light retained',draw('global-mismatch',candidate,f,mismatch),base)
    # Nonconstant SH confirms the helper uses the host's final normal unchanged.
    directional=np.array([[.03,-.01,.02,.2],[-.02,.04,.01,.15],[.01,.03,-.04,.1]],np.float32)
    for i,normal_xy in enumerate(((.5,.5),(.7,.6),(.3,.65))):
        df,di=fixture(compiler,output/('direction-'+str(i)),normal_xy=normal_xy)
        regions=table([{'type':2,'color':(.1,.1,.1),'inverse_extent':(.01,.01,.01)}]);regions[4:7]=directional;regions[7,3]=1.4
        di=configure(di,regions);di['constants'][6][:3]=directional;di['constants'][6][3,3]=1.4
        check('directional full-region native identity '+str(i),draw('direction-on',candidate,df,di),draw('direction-base',original,df,di))
    # Multiple overlaps follow the native first-three ordering, with the third
    # selected entry as the base. This is not a normalized all-volume average.
    entries=[{'type':2,'color':color,'center':(center,0,5),'inverse_extent':(.25,.25,.25)}
             for center,color in ((-.4,(.3,.02,.05)),(.4,(.02,.2,.06)),(0,(.04,.06,.25)))]
    multi=configure(inputs,table(entries));actual=draw('three-overlaps',candidate,f,multi)
    selected_colors=np.zeros((*f['position'].shape[:2],3));weights=[cpu_weight(e,f['position']) for e in entries]
    for y in range(f['height']):
        for x in range(f['width']):
            picked=[]
            for e,w in zip(entries,weights):
                if w[y,x]>0:
                    picked.append((np.array(e['color']),w[y,x]))
                    if len(picked)==3 or w[y,x]>=1:break
            picked += [(global_color,1)]*(3-len(picked))
            value=picked[2][0]
            for color,w in reversed(picked[:2]):value=value+(color-value)*w
            selected_colors[y,x]=value
    check('three overlap ordering',actual[...,:3],np.sqrt(.8*(.25+.6*selected_colors)))
    fp16=draw('three-overlaps-fp16',candidate,f,multi,'rgba16f')
    from capture_reprojection import half_ulp
    check('FP16 output storage',np.abs(fp16-actual)/half_ulp(actual),np.zeros_like(actual),1.001)
    # Native field updates, using the SAME shader binary and renderer device.
    frames=[]
    for x in (-2,-1,0,1,2):frames.append(table([{'color':(.3,.08,.02),'type':2,'center':(x,0,5),'inverse_extent':(1,.7,1)}]))
    inp=configure(inputs,frames[0]);inp['region_copy']=(12,np.stack(frames))
    animation=render(candidate,output/'moving-regions',f['width'],f['height'],**inp)[...,0,:,:,:]
    for i,x in enumerate((-2,-1,0,1,2)):
        weight=cpu_weight({'type':2,'center':(x,0,5),'inverse_extent':(1,.7,1)},f['position'])
        ambient=global_color+(np.array([.3,.08,.02])-global_color)*weight[...,None]
        check('moving native region '+str(i),animation[i,...,:3],np.sqrt(.8*(.25+.6*ambient)))
    # Real captured regional parameters, re-used by a synthetic mesh plane.
    capture=ROOT/'artifacts/native-live-audit/night-cafe/stationary-1'
    m=json.loads((capture/'manifest.json').read_bytes());d=next(d for d in m['draws'] if d['target']=='415a922293923fa4')
    row=next(r for r in d['resources'] if r['label']=='ps-b2')
    raw=(capture/row['file']).read_bytes()
    if digest(raw)!=row['sha256']:raise ValueError('Captured native region payload changed')
    native=np.frombuffer(raw,dtype='<f4').reshape(-1,4)[:772].copy()
    inp=configure(inputs,native)
    real=draw('captured-native-parameters',candidate,f,inp)
    if not np.isfinite(real).all():raise AssertionError('Captured parameters produced nonfinite pixels')
    checks.append({'name':'captured native parameters real draw finite','passed':True})
    # Cross a real captured local region in view space. Geometry is synthetic;
    # no claim is made that these samples identify the player's mesh.
    local_matrix=native[10:13].astype(np.float64)
    inverse=np.linalg.inv(local_matrix[:,:3]);center=-inverse@local_matrix[:,3]
    dx=inverse[:,0]*1.25;dy=inverse[:,1]*1.25
    vector=lambda v:'float3('+','.join(format(float(x),'.9g') for x in v)+')'
    source=Path(inputs['vertex']).with_suffix('.hlsl').read_text()
    original_position='float4((uv.x*2-1)*3,(1-uv.y*2)*2,5,'
    if original_position not in source:raise ValueError('Synthetic plane anchor changed')
    source=source.replace(original_position,'float4('+vector(center)+'+(uv.x*2-1)*'+vector(dx)+'+(1-uv.y*2)*'+vector(dy)+',')
    vs=output/'captured-region-plane.hlsl';vs.write_text(source);vertex=output/'captured-region-plane.bin';vertex.write_bytes(compiler.compile(vs,'vs_5_0')[0])
    inp=configure(inputs,native);inp['vertex']=vertex
    last=int(native.view(np.uint32)[0,0])-1;inp['constants'][6][:3]=native[4+12*last:7+12*last];inp['constants'][6][3,3]=native[7+12*last,3]
    captured_base=draw('captured-region-base',original,f,inp);captured_on=draw('captured-region-surface',candidate,f,inp)
    delta=float(np.max(np.abs(captured_on[...,:3]-captured_base[...,:3])))
    if not np.isfinite(captured_on).all() or delta<=1e-6:raise AssertionError('Captured region crossing did not produce finite material response')
    checks.append({'name':'captured region crossing changes native material output','passed':True,'max_abs_rgb_delta':delta})
    # Save illustrative synthetic comparisons, not a game screenshot.
    cells=[base,*previews]
    grid=np.concatenate(cells,axis=1)
    Image.fromarray(np.uint8(np.clip(grid[...,:3],0,1)*255)).resize((1040,164)).save(output/'synthetic-comparison.png')
    Image.fromarray(np.uint8(np.clip(np.concatenate([captured_base,captured_on],axis=1)[...,:3],0,1)*255)).resize((780,246)).save(output/'captured-parameters-synthetic-plane.png')
    report={**meta,'checks':checks,'all_passed':True,'actual_draw_jobs':serial+1,
            'game_installed':False,'game_visual_benefit_verified':False,'performance_verified':False,
            'limits':['Synthetic geometry and material swatches; no player object association',
                      'Geometric region selection plus native SH only; background sky/AO weighting is not copied',
                      'Original mesh attenuation/reflection/AO logic remains intact',
                      'Captured regions are frozen inputs here; GPU CB-to-owned-SRV copy tested, live bridge not yet implemented']}
    (output/'report.json').write_bytes(encoded(report))
    print(json.dumps({'checks':len(checks),'all_passed':True,'candidate_sha256':meta['candidate_sha256']},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--extraction',type=Path,default=ROOT/'artifacts/client-2026.09.15')
    p.add_argument('--decompiler',type=Path,default=ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe')
    a=p.parse_args();run(a.output,a.extraction,a.decompiler)
