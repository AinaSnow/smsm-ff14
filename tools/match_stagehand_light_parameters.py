"""Recheck the observed point-light candidate against logged controls and same-frame resources."""
import argparse
import json
from pathlib import Path
import numpy as np
from analyze_native_output import analyze

POINT_SHA='3d4b9ee8a82e81665d57ddc271e3f38abad71e318b728dc8ca7028081931db36'


def bound_constants(directory,producer,slot,size):
    item=next(x for x in producer['inputs'] if x['slot']==slot)
    if item['status']!='captured':raise ValueError('Required producer CB not captured')
    raw=(directory/item['file']).read_bytes();start=item['constant_first']*16
    if size>item['constant_count']*16 or start+size>len(raw):raise ValueError('Reflected producer CB outside binding')
    values=np.frombuffer(raw[start:start+size],dtype='<f4').astype(np.float64)
    if not np.isfinite(values).all():raise ValueError('Nonfinite producer constants')
    return values


def analyze_controls(root):
    events=json.loads((root/'events.private.json').read_bytes())
    controls=[x['value'] for x in events if x['kind']=='preset']
    if [x['preset'] for x in controls]!=['Off','Warm','Cool','Off']:raise ValueError('Expected bounded four-state control sequence')
    rows=[]
    for name,control in zip(['Off0','Warm','Cool','Off1'],controls):
        directory=root/name;verified=analyze(directory)
        report=json.loads((directory/'report.json').read_bytes())
        if report['producer_trace_truncated']:raise ValueError('Producer candidate trace was truncated')
        p=control['position'];world=np.array([p['X'],p['Y'],p['Z'],1.0])
        c=control['color'];expected_rgb=np.array([c['X'],c['Y'],c['Z']])*control['intensity']
        inputs=report['draws'][0]['inputs'];consumer=report['draws'][0]
        t0=next(x for x in inputs if x['label'].endswith('-ps-t0'));t1=next(x for x in inputs if x['label'].endswith('-ps-t1'))
        matches=[]
        for producer in report['producer_records']:
            if producer['pixel_sha256']!=POINT_SHA:continue
            camera=bound_constants(directory,producer,1,48).reshape(3,4)
            light=bound_constants(directory,producer,2,80)
            error=float(np.linalg.norm(light[:3]-camera@world))
            if error>1e-3:continue
            if control['preset']=='Off':raise ValueError('The logged OFF lamp still has a matching producer')
            if not np.allclose(light[8:11],expected_rgb,rtol=1e-6,atol=1e-6) or not np.allclose(light[12:15],expected_rgb,rtol=1e-6,atol=1e-6):
                raise ValueError('Position matches but GPU light colors disagree with controls')
            if abs(light[18]-1/control['range']**2)>1e-7:raise ValueError('Range-squared coefficient mismatch')
            draw_control=bound_constants(directory,producer,3,16)
            linked=[]
            for item in [t0,t1]:
                h=item['producer_history']
                linked.append(h['writer_observation_scope']=='current_capture_frame_and_enable_epoch' and
                    producer['frame']==consumer['frame'] and producer['draw']<consumer['draw'] and
                    any(o['resource']==item['resource'] and o['generation']==h['generation'] and o['generation']>0 for o in producer['outputs']))
            matches.append({'position_error':error,'diffuse_rgb':light[8:11].tolist(),'specular_rgb':light[12:15].tolist(),
                            'inverse_range_squared':float(light[18]),'draw_parameter_semistransparency':float(draw_control[0]),
                            'outputs_match_current_skirt_inputs':all(linked)})
        if control['preset']!='Off' and (len(matches)!=2 or sum(m['outputs_match_current_skirt_inputs'] for m in matches)!=1):
            raise ValueError('Expected two point-light paths and exactly one current-skirt resource pair')
        rows.append({'state':name,'verified_bytes':verified['verified_bytes'],'producer_records':len(report['producer_records']),
                     'matched_point_light_paths':matches,'consumer_sampler0':consumer.get('sampler0'),
                     't0_writer_identity_summary_truncated':t0['producer_history'].get('writer_set_truncated',False)})
    return {'scope':'one known Stagehand point light and current skirt; not complete scene provenance',
            'point_pixel_shader':'6fe15fe7984aeff9','point_pixel_sha256':POINT_SHA,'light_constant_slot':2,
            'states':rows,'position_tolerance':1e-3,'controlled_parameter_correspondence_verified':True,
            'full_m3_complete':False,'limits':['Two render paths are not evidence of double-counted lighting',
                'Later writes and partial coverage remain; no exclusive pixel attribution',
                'Hair/skin, other maps, shadows and selection limits require separate checks']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();result=analyze_controls(a.directory)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result))
