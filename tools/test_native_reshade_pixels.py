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


def run(output,package,setup,audit=False,zero_mask=False,later_clear=False,predicated=False):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    meta=json.loads((package/'SMSM-native-package.json').read_bytes())
    addon=package/'SMSM.NativeLighting.addon64'
    assert meta.get('coverage_shader_sha256')
    assert hashlib.sha256(addon.read_bytes()).hexdigest()==meta['files'][addon.name]
    shutil.copy2(addon,output/addon.name)
    with zipfile.ZipFile(setup) as z:runtime=z.read('ReShade64.dll')
    (output/'d3d11.dll').write_bytes(runtime)
    (output/'ReShade.ini').write_text('[GENERAL]\nNoDebugInfo=1\nNoReloadOnInit=1\n')
    f,inputs=fixture(Compiler(),output/'geometry',width=32,height=24)
    original=ROOT/'artifacts/client-2026.09.15/dxbc/980154264a89fba1-ps.bin'
    reference=render(original,output/'warp-reference',f['width'],f['height'],**inputs)[0,0]
    job=(output/'warp-reference/job.txt').read_text()
    # Static input fixture, no animation blocks; all three frames use identical inputs.
    lines=job.splitlines()
    lines=[('frames 3' if l.startswith('frames ') else
            'output '+json.dumps((output/'hardware-pixels').as_posix()) if l.startswith('output ') else l) for l in lines]
    if not any(l.startswith('frames ') for l in lines):lines.append('frames 3')
    job_path=output/'hardware-job.txt';job_path.write_text('\n'.join(lines)+'\n')
    exe=output/'test_pixels.exe'
    extra=['/DSMSM_RESHADE_PIXEL_TEST']
    if audit:extra.append('/DSMSM_RESHADE_OUTPUT_TEST')
    if zero_mask:extra.append('/DSMSM_WRITE_MASK_ZERO')
    if later_clear:extra.append('/DSMSM_LATER_CLEAR')
    if predicated:extra.append('/DSMSM_PREDICATED')
    compile_cpp(ROOT/'tools/offline/render_ps.cpp',exe,extra_args=extra)
    subprocess.run([str(exe),str(job_path)],cwd=output,check=True,timeout=60)
    pixels=[np.fromfile(output/f'hardware-pixels-f{i}-rt0.f32',np.float32).reshape(f['height'],f['width'],4) for i in range(3)]
    statuses=[json.loads((output/f'frame-{i}-status.json').read_bytes()) for i in range(3)]
    expected=np.zeros_like(reference);expected[...,:3]=(1,0,1);expected[...,3]=reference[...,3]
    if zero_mask:reference=np.zeros_like(reference);expected=np.zeros_like(expected)
    if predicated:expected=np.zeros_like(expected)
    errors={'baseline_vs_warp':float(np.max(np.abs(pixels[0]-reference))),
            'coverage_vs_magenta':float(np.max(np.abs(pixels[1]-expected))),
            'off_restores_baseline':float(np.max(np.abs(pixels[2]-pixels[0])))}
    result={'actual_runtime':True,'vertices_per_draw':3,'synthetic_geometry':True,'game_coverage_verified':False,
            'addon_sha256':meta['files'][addon.name],'errors':errors,'statuses':statuses}
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    assert all(np.isfinite(p).all() for p in pixels)
    assert max(errors.values())<1e-5,errors
    assert not statuses[0]['coverage_enabled'] and statuses[1]['coverage_enabled']==(not audit) and not statuses[2]['coverage_enabled']
    assert statuses[1]['coverage_draws']==1 and statuses[2]['coverage_draws']==1
    if audit:
        directory=output/'SMSM-native-captures'/statuses[1]['output_audit_directory']
        report=json.loads((directory/'report.json').read_bytes())
        assert report['status']=='complete' and report['observed_target_draws']==1,report
        draw=report['draws'][0]
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
        assert bool(np.any(raw[1]!=raw[0]))==(not zero_mask and not predicated)
        result['output_audit']={'passed':True,'write_mask':draw['outputs'][0]['write_mask'],
                                'occlusion_samples':draw['occlusion_samples'],'color_changed':not zero_mask and not predicated,
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
    a=p.parse_args();run(a.output,a.package,a.setup,a.audit,a.zero_mask,a.later_clear,a.predicated)
