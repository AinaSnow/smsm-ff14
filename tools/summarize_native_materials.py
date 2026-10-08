"""Rank original material draws for bounded follow-up sampling, not player coverage."""
import argparse
from collections import Counter
import json
from pathlib import Path
from analyze_native_output import analyze


def summarize(directory):
    report=json.loads((directory/'report.json').read_bytes())
    if report.get('mode')!='census':raise ValueError('Expected a material census')
    analysis=analyze(directory)
    groups={};indices=Counter()
    for draw in analysis['draws']:
        if draw.get('shader_replaced') is not False:raise ValueError('Census altered shader')
        shader=draw['pixel_shader'];indices[shader]+=1
        row=groups.setdefault(shader,{'shader':shader,'packages':draw['packages'],'recorded_draws':0,
            'nonzero_query_draws':0,'samples_sum':0,'max_samples':0,'unknown_queries':0,'sample_skip':0,
            'output_layouts':[],'candidate_only':True})
        row['recorded_draws']+=1
        layout=[{'slot':o['slot'],'format':o['view_format'],'write_mask':o['write_mask'],'blend_enabled':o['blend_enabled']} for o in draw['outputs']]
        if layout not in row['output_layouts']:row['output_layouts'].append(layout)
        if 'occlusion_samples' not in draw:row['unknown_queries']+=1;continue
        samples=draw['occlusion_samples'];row['samples_sum']+=samples;row['nonzero_query_draws']+=samples>0
        eligible=any(o['slot']==0 and o['write_mask']&7 for o in draw['outputs'])
        if eligible and samples>row['max_samples']:
            row['max_samples']=samples;row['sample_skip']=indices[shader]-1
    return {'observed_draws':analysis['observed_target_draws'],'recorded_draws':len(analysis['draws']),
            'truncated':analysis['observed_target_draws']>len(analysis['draws']),
            'unique_shaders':len(groups),'verified_snapshot_bytes':analysis['verified_bytes'],
            'candidates':sorted(groups.values(),key=lambda r:(-r['max_samples'],r['shader'])),
            'limits':['Query samples do not establish color writes or a named player.',
                      'Multiple render targets may be G-buffer data, not final visible color.',
                      'Sample skip is only a cross-frame selection hint; draw order can change.']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();text=json.dumps(summarize(a.directory),indent=2)
    if a.output:
        with a.output.open('x',encoding='utf-8') as f:f.write(text+'\n')
    else:print(text)
