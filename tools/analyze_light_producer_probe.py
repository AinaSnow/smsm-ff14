"""Associate same-frame producer candidates, then reflect exact captured PS identities.

Output contains private resource/constant evidence and belongs in local artifacts.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import struct
from analyze_native_output import analyze
from shader_compile import Compiler


def associate(report):
    result=[]
    for draw in report['draws']:
        for item in draw.get('inputs',[]):
            if not any(item['label'].endswith(s) for s in ('-ps-t0','-ps-t1')):continue
            history=item.get('producer_history',{})
            current=history.get('writer_observation_scope')=='current_capture_frame_and_enable_epoch'
            candidates=[]
            for producer in report.get('producer_records',[]):
                if not current or producer['frame']!=draw['frame'] or producer['draw']>=draw['draw']:continue
                for output in producer['outputs']:
                    if (output['resource']==item['resource'] and output.get('generation')==history.get('generation')
                        and output.get('generation',0)>0):
                        candidates.append({'draw':producer['draw'],'pixel_sha256':producer['pixel_sha256'],'slot':output['slot']})
            last=history.get('last_observed_rtv_draw',{})
            last_matches=[p for p in candidates if p['draw']==last.get('draw') and p['pixel_sha256']==last.get('pixel_sha256') and p['slot']==last.get('output_slot')]
            result.append({'consumer_draw':draw.get('draw'),'input':item['label'],
                           'same_frame_generation_candidates':candidates,'last_writer_record_captured':len(last_matches)==1,
                           'last_event':history.get('last_observed_event'),
                           'limits':'RTV binding intent only; multiple lights, blend, partial coverage or untracked writes may contribute'})
    return result


def reflect_light(extraction, sha, compiler):
    manifest=json.loads((extraction/'manifest.json').read_bytes())
    candidates=[r for r in manifest['Shaders'] if r['Profile']=='ps_5_0' and r['Sha256']==sha]
    if not candidates:return {'status':'shader_not_in_extraction'}
    record=candidates[0];path=(extraction/record['File']).resolve(strict=True)
    if not path.is_relative_to(extraction.resolve()):raise ValueError('Shader path escapes extraction')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Shader identity mismatch')
    text=compiler.disassemble(data)
    match=re.search(r'// cbuffer g_LightParam\s*\n(.*?)\n// }',text,re.S)
    bind=re.search(r'^// g_LightParam\s+cbuffer\s+NA\s+NA\s+cb(\d+)\s+1',text,re.M)
    if not match or not bind:return {'status':'no_reflected_light_param','hash':record['Hash']}
    fields={name:int(offset) for name,offset in re.findall(r'//\s+float[234]?\s+(m_\w+);\s*// Offset:\s*(\d+)',match[1])}
    return {'status':'reflected','hash':record['Hash'],'constant_slot':int(bind[1]),'fields':fields}


def run(capture,extraction,output):
    verified=analyze(capture);report=json.loads((capture/'report.json').read_bytes())
    if 'producer_records' not in report:raise ValueError('Capture has no producer trace')
    compiler=Compiler();layouts={};parameters=[]
    for p in report['producer_records']:
        sha=p['pixel_sha256']
        if sha not in layouts:layouts[sha]=reflect_light(extraction,sha,compiler)
        layout=layouts[sha]
        if layout['status']!='reflected':continue
        cb=next((x for x in p['inputs'] if x['slot']==layout['constant_slot']),None)
        if cb is None or cb['status']!='captured':continue
        raw=(capture/cb['file']).read_bytes();base=cb['constant_first']*16
        values={}
        for field,components in [('m_Position',3),('m_DiffuseColor',3),('m_SpecularColor',3),('m_Attenuation',4)]:
            if field not in layout['fields']:continue
            offset=layout['fields'][field]
            if offset+components*4>cb['constant_count']*16 or base+offset+components*4>len(raw):raise ValueError('Reflected field outside bound range')
            values[field]=list(struct.unpack_from('<'+'f'*components,raw,base+offset))
        parameters.append({'draw':p['draw'],'pixel_sha256':sha,'fields':values,'semantics':'reflected fields; coordinate space and link to Stagehand still require controlled comparison'})
    result={'verified_bytes':verified['verified_bytes'],'truncated':report['producer_trace_truncated'],
            'associations':associate(report),'layouts':layouts,'parameters':parameters,
            'current_live_light_correspondence_verified':False}
    with output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({'producer_records':len(report['producer_records']),'reflected_layouts':len(layouts),'output':str(output),'truncated':result['truncated']}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);p.add_argument('extraction',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();run(a.capture,a.extraction,a.output)
