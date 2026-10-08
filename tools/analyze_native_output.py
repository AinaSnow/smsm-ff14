"""Validate bounded RTV snapshots and compare actual before/after/end pixel bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def analyze(directory):
    directory=directory.resolve()
    report=json.loads((directory/'report.json').read_bytes())
    if report['status']!='complete' or report['selected_bytes']>report['byte_budget']:
        raise ValueError('Incomplete or over-budget audit')
    total=0
    def read(item):
        nonlocal total
        if item.get('status')!='captured':return None
        name=item['file'];path=directory/name
        if Path(name).name!=name or '\\' in name or ':' in name or path.is_symlink() or path.resolve().parent!=directory:
            raise ValueError('Unsafe snapshot path')
        raw=path.read_bytes()
        if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise ValueError('Damaged snapshot')
        total+=len(raw)
        pixels=item['width']*item['height']
        if pixels<=0 or len(raw)%pixels:raise ValueError('Invalid snapshot layout')
        return np.frombuffer(raw,np.uint8).reshape(item['height'],item['width'],-1)
    results=[]
    for draw in report['draws']:
        row={k:v for k,v in draw.items() if k!='images'}
        images=draw.get('images',[]);raw=[read(i) for i in images]
        if len(raw)==3 and all(r is not None for r in raw):
            if len({(i['width'],i['height'],i['format'],i['resource'],i['subresource']) for i in images})!=1:
                raise ValueError('Snapshots are not the same target/subresource')
            before,after,end=raw
            changed=np.any(before!=after,axis=-1)
            overwritten=np.any(after!=end,axis=-1)
            row['comparison']={'pixels':int(changed.size),'changed_by_draw':int(changed.sum()),
                               'changed_after_draw_by_frame_end':int(overwritten.sum()),
                               'draw_changed_pixels_altered_later':int((changed&overwritten).sum()),
                               'byte_comparison_includes_alpha':True}
            fmt=images[0].get('view_format') or images[0]['format']
            widths={1:12,2:12,9:6,10:6,11:6,27:3,28:3,29:3,87:3,90:3,91:3,26:4}
            if fmt in widths:
                n=widths[fmt]
                rgb_changed=np.any(before[...,:n]!=after[...,:n],axis=-1)
                rgb_later=np.any(after[...,:n]!=end[...,:n],axis=-1)
                row['comparison'].update(rgb_changed_by_draw=int(rgb_changed.sum()),
                    rgb_draw_changed_pixels_altered_later=int((rgb_changed&rgb_later).sum()))
            else:row['comparison']['rgb_only_status']='unsupported_format; do not infer RGB change from alpha-inclusive comparison'
        results.append(row)
    read(report['present_backbuffer'])
    if total!=report['selected_bytes']:raise ValueError('Captured bytes differ from selected budget')
    return {'scope':'same-target raw pixel byte comparisons; not proof of player identity or final compositing',
            'observed_target_draws':report['observed_target_draws'],'verified_bytes':total,'draws':results}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();result=analyze(a.directory);text=json.dumps(result,indent=2)
    if a.output:
        with a.output.open('x',encoding='utf-8') as f:f.write(text+'\n')
    else:print(text)
