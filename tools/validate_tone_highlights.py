"""Real WARP draws on synthetic inputs; numerical checks do not certify appearance."""
import argparse
from pathlib import Path
import numpy as np
from manage_preview import encoded, read_package, digest
from build_tone_highlights import BINARY, BASELINE
from offline_render import render


def validate(baseline, candidate, output):
    old, receipt = read_package(baseline)
    new, _ = read_package(candidate)
    if digest(receipt) != BASELINE or new.get('tone_experiment', {}).get('baseline_manifest_sha256') != BASELINE:
        raise ValueError('Unexpected comparison packages')
    output.mkdir(parents=True, exist_ok=False)
    # Neutral, warm skin-like ratios, saturated red, green, blue and cyan.
    colors = np.array([[1,1,1], [1,.65,.45], [1,.08,.02], [.08,1,.05], [.03,.08,1], [.05,1,1]], dtype=np.float32)
    levels = np.concatenate(([0], np.geomspace(.0001, 16, 511))).astype(np.float32)
    source = np.ones((len(colors),len(levels),4), dtype=np.float32)
    source[:,:,:3] = colors[:,None,:]*levels[None,:,None]
    source[:,:,3] = np.linspace(0,1,len(levels))
    reports = []
    for index, (exposure, gain) in enumerate(((.25,1), (1,1), (4,1), (1,.25))):
        lut = np.ones((1,256,4), dtype=np.float32)
        lut[:,:,:3] = gain
        constants = {0:[[0,exposure,1,0]], 1:[[0,0,1,0],[0,1,0,0]]}
        arrays = []
        for name, package in (('baseline',baseline),('candidate',candidate)):
            arrays.append(render(package/BINARY, output/f'{index}-{name}',len(levels),len(colors),
                textures={0:source,1:lut},constants=constants)[0,0])
        before, after = arrays
        assert np.isfinite(before).all() and np.isfinite(after).all(), 'Non-finite shader output'
        peak = before[:,:,:3].max(axis=-1)
        low = peak<=.85
        assert low.any() and (~low).any(), 'Fixture must cover unchanged and rolled regions'
        low_error = float(np.max(np.abs(after[low]-before[low])))
        assert low_error<2e-6, 'Dark/mid tones changed'
        alpha_error = float(np.max(np.abs(after[:,:,3]-source[:,:,3])))
        assert alpha_error<2e-6, 'Alpha changed'
        assert after[:,:,:3].min()>=-1e-6 and after[:,:,:3].max()<1.000001, 'Shoulder bounds failed'
        neutral_step = np.diff(after[0,:,:3],axis=0)
        assert neutral_step.min()>-2e-6, 'Neutral curve reverses'
        valid = peak>1e-5
        new_peak = after[:,:,:3].max(axis=-1)
        ratio_error = float(np.max(np.abs(before[:,:,:3][valid]/peak[valid,None] - after[:,:,:3][valid]/new_peak[valid,None])))
        assert ratio_error<2e-5, 'RGB ratios shifted'
        high = np.flatnonzero(peak[0]>1)
        assert len(high)>2
        before_display = np.clip(before[0,high,:3],0,1)
        after_display = np.clip(after[0,high,:3],0,1)
        old_steps = int(np.count_nonzero(np.diff(before_display[:,0])>1e-6))
        new_steps = int(np.count_nonzero(np.diff(after_display[:,0])>1e-6))
        assert new_steps>old_steps, 'No additional synthetic highlight separation'
        reports.append({'exposure':exposure,'synthetic_lut_gain':gain,'dark_mid_max_error':low_error,
            'alpha_max_error':alpha_error,'rgb_ratio_max_error':ratio_error,
            'baseline_peak':float(peak.max()),'candidate_peak':float(new_peak.max()),
            'baseline_display_highlight_steps':old_steps,'candidate_display_highlight_steps':new_steps})
    report = {'status':'numerical-checks-pass','source':'synthetic HDR ramps and constant-gain LUTs; not game captures',
        'baseline_shader_sha256':old['files'][BINARY],'candidate_shader_sha256':new['files'][BINARY],
        'game_verified':False,'visual_improvement_verified':False,'cases':reports}
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path); p.add_argument('candidate', type=Path); p.add_argument('output', type=Path)
    a = p.parse_args(); validate(a.baseline,a.candidate,a.output)
