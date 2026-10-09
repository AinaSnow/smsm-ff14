"""Match inspected geometry across OFF/WARM/COOL samples, never by draw ordinal.

Raw artifacts and this tool's output stay local. A matching mesh and visible mask
are evidence for this scene, not a universal character identity or light buffer.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from analyze_native_output import analyze


def select_draw(report, directory, vertex_sha, elements):
    matches=[]
    for draw in report['draws']:
        if draw['vertex_sha256']!=vertex_sha or draw['elements']!=elements:
            continue
        images=draw.get('images',[])
        if len(images)!=3 or any(x['status']!='captured' for x in images):
            continue
        if any((x.get('view_format') or x['format'])!=10 for x in images):
            raise ValueError('Only verified RGBA16_FLOAT snapshots are supported')
        before,after=[np.fromfile(directory/x['file'],dtype='<f2').reshape(x['height'],x['width'],4) for x in images[:2]]
        if not np.isfinite(before).all() or not np.isfinite(after).all():
            raise ValueError('Nonfinite render target values')
        mask=np.any(before[:,:,:3]!=after[:,:,:3],axis=-1)
        if mask.any():matches.append((draw,after,mask))
    if len(matches)!=1:raise ValueError('Expected exactly one nonzero geometry match; inspect masks before pairing')
    return matches[0]


def compare(root, vertex_sha, elements):
    selected=[];shader=None;viewport=None
    for name in ('Off','Warm','Cool'):
        directory=root/name
        analyze(directory) # Verify byte lengths, hashes, target identity and budget.
        report=json.loads((directory/'report.json').read_bytes())
        if report['mode']!='sample':raise ValueError('Expected original-material sample')
        if shader is not None and shader!=report['selected_shader']:raise ValueError('Different pixel shaders')
        shader=report['selected_shader']
        draw,after,mask=select_draw(report,directory,vertex_sha,elements)
        if draw['shader_replaced']:raise ValueError('Modified shader is not an original-material control')
        if viewport is not None and viewport!=draw['viewports']:raise ValueError('Different raster viewports')
        viewport=draw['viewports']
        selected.append((name,draw,after,mask))
    if len({row[3].shape for row in selected})!=1:raise ValueError('Different target dimensions')
    common=np.logical_and.reduce([row[3] for row in selected])
    # Remove three edge pixels to reduce silhouette motion contamination.
    for _ in range(3):
        padded=np.pad(common,1,constant_values=False)
        h,w=common.shape
        common=np.logical_and.reduce([padded[y:y+h,x:x+w] for y in range(3) for x in range(3)])
    if common.sum()<100:raise ValueError('Insufficient common interior pixels')
    rows=[]
    for name,draw,after,mask in selected:
        rgb=after[:,:,:3][common].astype(np.float32)
        rows.append({'preset':name,'draw_ordinal':draw['ordinal'],'rgb_changed_pixels':int(mask.sum()),
                     'mean_linear_rgb':rgb.mean(axis=0,dtype=np.float64).tolist(),
                     'median_linear_rgb':np.median(rgb,axis=0).tolist()})
    return {'scope':'inspected geometry, common interior pixels in original material RTV; no light-buffer identity',
            'output_domain':'native material encoded RGB after sqrt and scale; historical mean_linear_rgb field is not linear-energy evidence',
            'pixel_shader':shader,'elements':elements,'common_interior_pixels':int(common.sum()),'states':rows,
            'limitations':['Pose/animation and other game lighting can vary between frames',
                           'Mesh identity needs manual spatial-mask inspection; not inferred from counts alone',
                           'Three color states are not repeated OFF controls or GPU light-data correspondence']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path);p.add_argument('--vertex-sha',required=True);p.add_argument('--elements',type=int,required=True)
    p.add_argument('--output',type=Path)
    a=p.parse_args();result=compare(a.directory,a.vertex_sha,a.elements)
    text=json.dumps(result,indent=2)
    if a.output:
        with a.output.open('x',encoding='utf-8') as f:f.write(text+'\n')
    print(text)
