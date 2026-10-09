"""Analyze a manually inspected hair/hands ROI during bounded OFF/WARM/WARM/OFF samples."""
import argparse
import json
from pathlib import Path
import numpy as np
from analyze_native_output import analyze
from offline_render import unpack_r11
from match_stagehand_light_parameters import POINT_SHA,bound_constants

PROFILES={
    'hair':('1c5c89ac035f9a44','e513c2563b6c482750284c2f3276a10e757a03698de9dc36064ca09331d8764b',8817,[2]),
    'hands':('643c8fab6e8d0bce','5def6b43c7cb9f46447a6f5debec94d244b9e571850edebc0c1b8b5dc9a7e7f9',18924,[2,3]),
}


def run(root,material,roi):
    ps,vs,elements,gbuffers=PROFILES[material]
    events=json.loads((root/'lifecycle-controls.private.json').read_bytes());start=next(e['value'] for e in events if e['kind']=='start')
    if start['mode']!='lifecycle':raise ValueError('Expected bounded warm-only lifecycle')
    p=start['position'];world=np.array([p['X'],p['Y'],p['Z'],1]);rows=[];x0,y0,x1,y1=roi
    for state in ['Off0','Warm0','Warm1','Off1']:
        directory=root/material/state;verified=analyze(directory);r=json.loads((directory/'report.json').read_bytes())
        if r['selected_shader']!=ps or r['selected_vertex_sha256']!=vs or r['selected_elements']!=elements:raise ValueError('Wrong material identity')
        choices=[]
        for d in r['draws']:
            if d['vertex_sha256']!=vs or d['elements']!=elements or d['shader_replaced']:raise ValueError('Changed geometry or replacement')
            ims=d['images']
            if len(ims)!=3 or any(x['status']!='captured' or (x.get('view_format') or x['format'])!=10 for x in ims):continue
            before,after=[np.fromfile(directory/x['file'],dtype='<f2').reshape(x['height'],x['width'],4)[...,:3].astype(np.float32) for x in ims[:2]]
            mask=np.any(before!=after,axis=-1);selected=np.zeros(mask.shape,bool);selected[y0:y1,x0:x1]=True;mask &= selected
            choices.append((int(mask.sum()),d,after,mask))
        choices.sort(key=lambda x:x[0],reverse=True)
        if not choices or choices[0][0]<30 or (len(choices)>1 and choices[1][0]*2>=choices[0][0]):raise ValueError('ROI does not uniquely identify the inspected player material')
        pixels,d,after,mask=choices[0];bindings={x['label'].split('-ps-')[1]:x for x in d['inputs']};textures={}
        h,w=mask.shape
        for slot in [0,1]+gbuffers:
            item=bindings['t'+str(slot)]
            if item['status']!='captured' or (item['height'],item['width'])!=(h,w):raise ValueError('Missing or mismatched input')
            fmt=item.get('view_format') or item['format'];raw=(directory/item['file']).read_bytes()
            if slot<2:
                if fmt!=26:raise ValueError('Expected R11 light texture')
                textures[slot]=unpack_r11(np.frombuffer(raw,dtype='<u4').reshape(h,w))[...,:3]
            else:
                if fmt!=87:raise ValueError('Unsupported GBuffer observation')
                textures[slot]=np.frombuffer(raw,dtype=np.uint8).reshape(h,w,4)
        common=bound_constants(directory,{'inputs':[bindings['b1']]},1,16)
        if not np.allclose(common,[1/w,1/h,0,0],rtol=1e-6,atol=1e-9):raise ValueError('Screen mapping changed')
        lamp=[]
        for producer in r['producer_records']:
            if producer['pixel_sha256']!=POINT_SHA:continue
            camera=bound_constants(directory,producer,1,48).reshape(3,4);light=bound_constants(directory,producer,2,80)
            error=float(np.linalg.norm(light[:3]-camera@world))
            if error>1e-3:continue
            if state.startswith('Off'):raise ValueError('OFF control still contains this lamp')
            if not np.allclose(light[8:11],[8,2.8,.8],atol=1e-6) or not np.allclose(light[12:15],[8,2.8,.8],atol=1e-6):raise ValueError('Warm lamp parameter mismatch')
            linked=[]
            for key in ['t0','t1']:
                item=bindings[key];history=item['producer_history']
                linked.append(history['writer_observation_scope']=='current_capture_frame_and_enable_epoch' and producer['frame']==d['frame'] and producer['draw']<d['draw'] and any(o['resource']==item['resource'] and o['generation']==history['generation'] and o['generation']>0 for o in producer['outputs']))
            lamp.append({'position_error':error,'links_both_light_inputs':all(linked)})
        if state.startswith('Warm') and (len(lamp)!=2 or sum(x['links_both_light_inputs'] for x in lamp)!=1):raise ValueError('No unique warm producer path for this material')
        rows.append(dict(state=state,draw=d,output=after,mask=mask,textures=textures,lamp=lamp,bytes=verified['verified_bytes']))
    common=np.logical_and.reduce([r['mask'] for r in rows]);p=np.pad(common,1);h,w=common.shape
    common=np.logical_and.reduce([p[y:y+h,x:x+w] for y in range(3) for x in range(3)])
    if common.sum()<30:raise ValueError('Insufficient common material pixels')
    stable=common.copy()
    for slot in gbuffers:stable &= np.logical_and.reduce([np.all(r['textures'][slot]==rows[0]['textures'][slot],axis=-1) for r in rows[1:]])
    regions={}
    for name,mask in [('common_interior',common),('available_gbuffer_stable',stable)]:
        if mask.sum()<10:
            regions[name]={'pixels':int(mask.sum()),'status':'too_few_for_comparison'};continue
        measurements=[];planes={key:[r['output'][mask] if key=='output' else r['textures'][int(key[1])][mask] for r in rows] for key in ['output','t0','t1']}
        if any(not np.isfinite(a).all() for group in planes.values() for a in group):raise ValueError('Nonfinite region')
        for i,r in enumerate(rows):measurements.append({'state':r['state'],**{key:group[i].mean(axis=0,dtype=np.float64).tolist() for key,group in planes.items()}})
        regions[name]={'pixels':int(mask.sum()),'mean_rgb':measurements,'mean_absolute_delta':{key:{rows[i]['state']:np.abs(group[i]-group[0]).mean(axis=0,dtype=np.float64).tolist() for i in [1,2,3]} for key,group in planes.items()}}
    return {'material':material,'pixel_shader':ps,'states':[r['state'] for r in rows],
            'color_domains':{'output':'native material encoded RGB after sqrt and scale','t0':'diffuse light-buffer RGB','t1':'specular light-buffer RGB'},
            'input_producer_path_verified':True,'pixel_benefit_automatically_accepted':False,
            'verified_bytes':[r['bytes'] for r in rows],'selected_draws':[r['draw']['ordinal'] for r in rows],
            'lamp_paths':[r['lamp'] for r in rows],'gbuffer_slots_compared':gbuffers,'regions':regions,
            'limitations':['ROI inspected for this character/camera only','Warm-only lifecycle control; cold light not tested for this material',
                           'Hair structured t3 is unsupported; GBuffer stability filter is narrower than hands',
                           'Pose and environment residuals remain; not all skin regions or hairstyles covered']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('material',choices=list(PROFILES));p.add_argument('--roi',type=int,nargs=4,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=run(a.root,a.material,a.roi)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result))
