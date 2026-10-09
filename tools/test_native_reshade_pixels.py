"""Verify real nonzero pixel replacement via the official ReShade hardware runtime."""
import argparse
import json
import hashlib
import shutil
import subprocess
import zipfile
from pathlib import Path
import numpy as np
from build_native_diagnostic import ROOT,compile_cpp
from shader_compile import Compiler
from validate_forward_light import fixture
from offline_render import render


def run(output,package,setup,audit=False,zero_mask=False,later_clear=False,predicated=False,reject=None,material_mode=None,visible_material=None,visible_bundle=None):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    meta=json.loads((package/'SMSM-native-package.json').read_bytes())
    addon=package/'SMSM.NativeLighting.addon64'
    assert meta.get('coverage_shader_sha256')
    assert hashlib.sha256(addon.read_bytes()).hexdigest()==meta['files'][addon.name]
    shutil.copy2(addon,output/addon.name)
    with zipfile.ZipFile(setup) as z:runtime=z.read('ReShade64.dll')
    (output/'d3d11.dll').write_bytes(runtime)
    (output/'ReShade.ini').write_text('[GENERAL]\nNoDebugInfo=1\nNoReloadOnInit=1\n')
    settings={'alpha':0} if reject=='alpha' else {'depth':.4} if reject=='sampled-depth' else {}
    target='980154264a89fba1';visible_expected=None
    if visible_material:
        if any([audit,zero_mask,later_clear,predicated,reject,material_mode]) or not visible_bundle:raise ValueError('Visible material mode requires its validated bundle only')
        from validate_visible_ambient import fixture as material_fixture,HAIR,DRESS
        from validate_native_ambient import table
        target=HAIR if visible_material=='hair' else DRESS
        f,inputs=material_fixture(Compiler(),output/'geometry',target,width=32,height=24)
        inputs['constants'][6][:3,3]=(.06,.08,.12);inputs['constants'][6][4,2]=1
        inputs['region_copy']=(14,table([{'color':(.3,.08,.02),'type':2,'inverse_extent':(.5,.7,1)}])[None])
        inputs['constants'][8]=np.array([[.5,0,0,0]],np.float32)
        bundle=json.loads(visible_bundle.read_bytes());variant=next(v for v in bundle['variants'] if v['target']==target)
        candidate=visible_bundle.parent/variant['file']
        assert hashlib.sha256(candidate.read_bytes()).hexdigest()==variant['candidate_sha256']
        visible_expected=render(candidate,output/'warp-candidate',32,24,**inputs)[0,0]
    else:f,inputs=fixture(Compiler(),output/'geometry',width=32,height=24,**settings)
    original=ROOT/'artifacts/client-2026.09.15/dxbc'/(target+'-ps.bin')
    reference=render(original,output/'warp-reference',f['width'],f['height'],**inputs)[0,0]
    job=(output/'warp-reference/job.txt').read_text()
    # Static input fixture, no animation blocks; all three frames use identical inputs.
    lines=job.splitlines()
    lines=[('frames 3' if l.startswith('frames ') else
            'output '+json.dumps((output/'hardware-pixels').as_posix()) if l.startswith('output ') else l) for l in lines]
    if not any(l.startswith('frames ') for l in lines):lines.append('frames 3')
    if visible_material:
        regions=output/'hardware-regions.f32';np.repeat(inputs['region_copy'][1],3,axis=0).tofile(regions)
        lines=[('region_copy 14 '+json.dumps(regions.as_posix()) if l.startswith('region_copy ') else l) for l in lines]
        lines.append('source_shader '+json.dumps((ROOT/'artifacts/client-2026.09.15/dxbc/415a922293923fa4-ps.bin').as_posix()))
    job_path=output/'hardware-job.txt';job_path.write_text('\n'.join(lines)+'\n')
    exe=output/'test_pixels.exe'
    extra=['/DSMSM_RESHADE_PIXEL_TEST']
    if audit:extra.append('/DSMSM_RESHADE_OUTPUT_TEST')
    if zero_mask:extra.append('/DSMSM_WRITE_MASK_ZERO')
    if later_clear:extra.append('/DSMSM_LATER_CLEAR')
    if predicated:extra.append('/DSMSM_PREDICATED')
    if visible_material:extra.append('/DSMSM_VISIBLE_AMBIENT')
    if material_mode:
        if not audit or zero_mask or later_clear or predicated or reject:raise ValueError('Material mode requires plain audit fixture')
        extra.append('/DSMSM_MATERIAL_'+material_mode.upper())
        if material_mode=='probe':
            vertex=Path(json.loads(next(l for l in lines if l.startswith('vertex '))[7:]))
            extra.append('/DSMSM_PROBE_VERTEX_SHA="'+hashlib.sha256(vertex.read_bytes()).hexdigest()+'"')
    compile_cpp(ROOT/'tools/offline/render_ps.cpp',exe,extra_args=extra)
    subprocess.run([str(exe),str(job_path)],cwd=output,check=True,timeout=60)
    pixels=[np.fromfile(output/f'hardware-pixels-f{i}-rt0.f32',np.float32).reshape(f['height'],f['width'],4) for i in range(3)]
    statuses=[json.loads((output/f'frame-{i}-status.json').read_bytes()) for i in range(3)]
    expected=np.zeros_like(reference);expected[...,:3]=(1,0,1);expected[...,3]=reference[...,3]
    if zero_mask:reference=np.zeros_like(reference);expected=np.zeros_like(expected)
    if predicated:expected=np.zeros_like(expected)
    if reject:expected=np.zeros_like(expected)
    if material_mode:expected=reference.copy()
    if visible_material:expected=visible_expected
    errors={'baseline_vs_warp':float(np.max(np.abs(pixels[0]-reference))),
            ('middle_frame_vs_expected' if material_mode or visible_material else 'coverage_vs_magenta'):float(np.max(np.abs(pixels[1]-expected))),
            'off_restores_baseline':float(np.max(np.abs(pixels[2]-pixels[0])))}
    result={'actual_runtime':True,'vertices_per_draw':3,'synthetic_geometry':True,'game_coverage_verified':False,
            'addon_sha256':meta['files'][addon.name],'errors':errors,'statuses':statuses}
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    assert all(np.isfinite(p).all() for p in pixels)
    assert max(errors.values())<1e-5,errors
    assert not statuses[0]['coverage_enabled'] and statuses[1]['coverage_enabled']==(not audit and not visible_material) and not statuses[2]['coverage_enabled']
    assert statuses[1]['coverage_draws']==(0 if material_mode or visible_material else 1) and statuses[2]['coverage_draws']==statuses[1]['coverage_draws']
    if visible_material:
        assert statuses[1]['enabled'] and not statuses[2]['enabled'] and statuses[1]['copies']==1 and statuses[1]['overrides']==1
        assert statuses[1]['ambient_variant_overrides'][variant['original_sha256']]==1
        delta=float(np.max(np.abs(pixels[1][...,:3]-pixels[0][...,:3])))
        assert delta>.01,'No material pixel response'
        result['visible_ambient']={'target':target,'half_strength':True,'max_rgb_delta':delta,'per_variant_dispatch_verified':True}
        (output/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['visible_ambient']));return
    if audit:
        directory=output/'SMSM-native-captures'/statuses[1]['output_audit_directory']
        report=json.loads((directory/'report.json').read_bytes())
        assert report['status']=='complete' and report['observed_target_draws']==1,report
        if material_mode in ('census','skip'):
            assert report['mode']==('census' if material_mode=='census' else 'sample')
            assert report['recorded_draws']==(1 if material_mode=='census' else 0)
            if material_mode=='census':
                draw=report['draws'][0]
                assert draw['pixel_shader']=='980154264a89fba1' and draw['packages']=='hair' and not draw['shader_replaced']
                assert draw['occlusion_samples']==768 and not draw['images']
            result['material_mode']={'mode':material_mode,'passed':True,'unchanged_pixels':True,'recorded_draws':report['recorded_draws']}
            (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result['material_mode']));return
        draw=report['draws'][0]
        if material_mode in ('sample','probe'):
            assert report['mode']==material_mode and draw['pixel_shader']=='980154264a89fba1' and not draw['shader_replaced']
        if material_mode=='probe':
            from analyze_native_output import analyze
            verified=analyze(directory)
            assert report['selected_elements']==3 and report['selected_vertex_sha256']==hashlib.sha256(vertex.read_bytes()).hexdigest()
            assert len(draw['inputs'])==11
            for item in draw['inputs']:
                slot=item['slot'];kind='b' if '-ps-b' in item['label'] else 't'
                expected_file=output/'warp-reference'/f'{kind}{slot}.f32'
                if item['status']!='captured':
                    assert not expected_file.exists()
                    assert item['status'] in ('missing','missing_binding') or (item['status']=='unsupported_view_dimension' and (output/'warp-reference'/f'structured{slot}.bin').exists())
                    continue
                expected_raw=expected_file.read_bytes()
                assert (directory/item['file']).read_bytes()==expected_raw,'Pre-draw input differs from fixture'
            result['probe_inputs']={'verified_bytes':verified['verified_bytes'],'original_inputs_exact':True}
        assert draw['replacement_executed']==1 and (draw['occlusion_samples']>0)==(not predicated),draw
        assert draw['predication_bound']==int(predicated),draw
        assert draw['outputs'][0]['write_mask']==(0 if zero_mask else 15)
        raw=[]
        for item in draw['images']:
            data=(directory/item['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==item['sha256']
            raw.append(np.frombuffer(data,np.float32).reshape(f['height'],f['width'],4))
        assert len(raw)==3 and np.array_equal(raw[1],pixels[1])
        end_expected=np.empty_like(raw[2]);end_expected[...]=(.125,.125,.125,1)
        assert np.array_equal(raw[2],end_expected if later_clear else raw[1])
        assert np.array_equal(raw[0],np.zeros_like(raw[0]))
        changed=not zero_mask and not predicated and not reject
        assert bool(np.any(raw[1]!=raw[0]))==bool(changed)
        result['output_audit']={'passed':True,'write_mask':draw['outputs'][0]['write_mask'],
                                'original_material_sample':material_mode=='sample',
                                'occlusion_samples':draw['occlusion_samples'],'color_changed':bool(changed),
                                'native_shader_rejection':reject,
                                'predication_restored':predicated,
                                'later_overwrite_verified':later_clear,'before_after_end_readback_verified':True}
        (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result['output_audit']))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--package',type=Path,required=True);p.add_argument('--setup',type=Path,required=True)
    p.add_argument('--audit',action='store_true');p.add_argument('--zero-mask',action='store_true')
    p.add_argument('--later-clear',action='store_true')
    p.add_argument('--predicated',action='store_true')
    p.add_argument('--reject',choices=['alpha','sampled-depth'])
    p.add_argument('--material-mode',choices=['census','sample','skip','probe'])
    p.add_argument('--visible-material',choices=['hair','dress']);p.add_argument('--visible-bundle',type=Path)
    a=p.parse_args();run(a.output,a.package,a.setup,a.audit,a.zero_mask,a.later_clear,a.predicated,a.reject,a.material_mode,a.visible_material,a.visible_bundle)
