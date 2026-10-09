"""Compare verified OFF/WARM/COOL/OFF material inputs; do not infer upstream lamp IDs."""
import argparse
import json
from pathlib import Path
import numpy as np
from analyze_native_output import analyze
from compare_stagehand_material import select_draw
from offline_render import unpack_r11

PS='e86f0d4916054deb'
VS='6fcf9d7d0b2f8003165c608008f588620cc783e652201cb6ffda32d2a245df35'
CB_SIZES=[416,64,80,944,176,16,160] # Exact original shader reflection; excludes unused allocation padding.


def compare(root):
    rows=[]
    for state in ['Off0','Warm','Cool','Off1']:
        directory=root/state;verified=analyze(directory)
        report=json.loads((directory/'report.json').read_bytes())
        if report['mode']!='probe' or report['selected_shader']!=PS:raise ValueError('Wrong material probe')
        draw,output,mask=select_draw(report,directory,VS,7914)
        if draw['shader_replaced']:raise ValueError('Expected original material')
        bindings={x['label'].split('-ps-')[1]:x for x in draw['inputs']}
        if len(bindings)!=11 or any(x['status']!='captured' for x in bindings.values()):raise ValueError('Required binding missing')
        raw={key:(directory/item['file']).read_bytes() for key,item in bindings.items()}
        cb={}
        for slot,size in enumerate(CB_SIZES):
            item=bindings['b'+str(slot)];first=item['constant_first']*16
            if size>item['constant_count']*16 or first+size>len(raw['b'+str(slot)]):raise ValueError('Reflected CB outside binding')
            cb[slot]=raw['b'+str(slot)][first:first+size]
        common=np.frombuffer(cb[1],dtype='<f4')[:4]
        h,w=mask.shape
        if not np.allclose(common,[1/w,1/h,0,0],rtol=1e-6,atol=1e-9):
            raise ValueError('Screen-to-light-texture mapping requires separate verification')
        textures={}
        for slot in range(4):
            item=bindings['t'+str(slot)]
            if (item['height'],item['width'])!=(h,w):raise ValueError('Input dimensions differ from output')
            fmt=item.get('view_format') or item['format']
            if slot<2:
                if fmt!=26:raise ValueError('Expected R11G11B10_FLOAT light input')
                textures[slot]=unpack_r11(np.frombuffer(raw['t'+str(slot)],dtype='<u4').reshape(h,w))[...,:3]
            else:
                if fmt!=87:raise ValueError('Expected BGRA8 GBuffer observation')
                textures[slot]=np.frombuffer(raw['t'+str(slot)],dtype=np.uint8).reshape(h,w,4)
        rows.append(dict(state=state,draw=draw,output=output[...,:3].astype(np.float32),mask=mask,cb=cb,textures=textures,bytes=verified['verified_bytes']))
    if any(x['draw']['viewports']!=rows[0]['draw']['viewports'] for x in rows):raise ValueError('Raster viewport changed')
    common=np.logical_and.reduce([r['mask'] for r in rows])
    for _ in range(3):
        p=np.pad(common,1);h,w=common.shape
        common=np.logical_and.reduce([p[y:y+h,x:x+w] for y in range(3) for x in range(3)])
    stable=common.copy()
    for slot in (2,3):
        stable &= np.logical_and.reduce([np.all(r['textures'][slot]==rows[0]['textures'][slot],axis=-1) for r in rows[1:]])
    if stable.sum()<100:raise ValueError('Insufficient stable GBuffer pixels; do not report causal pairing')
    regions={}
    for name,mask in [('common_interior',common),('gbuffer_stable_interior',stable)]:
        records=[];planes={}
        for key in ['output','t0_diffuse','t1_specular']:
            planes[key]=[r['output'][mask] if key=='output' else r['textures'][0 if key=='t0_diffuse' else 1][mask] for r in rows]
            if not all(np.isfinite(a).all() for a in planes[key]):raise ValueError('Nonfinite input/output region')
        for i,r in enumerate(rows):
            records.append({'state':r['state'],**{key:arr[i].mean(axis=0,dtype=np.float64).tolist() for key,arr in planes.items()}})
        differences={key:{rows[i]['state']+'_vs_Off0_mean_abs_rgb':np.abs(arr[i]-arr[0]).mean(axis=0,dtype=np.float64).tolist() for i in (1,2,3)} for key,arr in planes.items()}
        regions[name]={'pixels':int(mask.sum()),'mean_linear_rgb':records,'absolute_differences':differences}
    cb_changes={str(slot):{'reflected_bytes':size,'equal_to_Off0':[r['cb'][slot]==rows[0]['cb'][slot] for r in rows]} for slot,size in enumerate(CB_SIZES)}
    sampler_verified=all(r['draw'].get('sampler0',{}).get('filter')==0 and r['draw']['sampler0'].get('address_u')==3 and r['draw']['sampler0'].get('address_v')==3 for r in rows)
    return {'scope':'one inspected skirt draw; input/output association, no upstream light-buffer identity',
            'color_domains':{'output':'native material encoded RGB after sqrt and scale; historical mean_linear_rgb field does not imply linear output','t0_diffuse':'diffuse light-buffer RGB','t1_specular':'specular light-buffer RGB'},
            'states':[r['state'] for r in rows],'verified_bytes_per_state':[r['bytes'] for r in rows],
            'regions':regions,'constant_buffer_comparison':cb_changes,
            'view_inverse_view_first_96_bytes_equal':[r['cb'][3][:96]==rows[0]['cb'][3][:96] for r in rows],
            'sampler0_point_clamp_recorded':sampler_verified,
            'limitations':[('Point/clamp sampler recorded; full original shader replay not performed' if sampler_verified else 'Pixel-coordinate observations do not reproduce the unrecorded sampler state'),
                           'Residual pose, environment and time-dependent changes remain; inspect returning OFF error',
                           'Same mesh still requires spatial-mask inspection; head/skin are separate targets']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=compare(a.directory)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result))
