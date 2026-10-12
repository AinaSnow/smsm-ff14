"""Real WARP draws: S2c medium/strong equal S2b, light sits between off and medium; synthetic inputs."""
import argparse
from pathlib import Path
import numpy as np
from manage_preview import encoded, read_package
from build_dither_t2 import FIXES, TONE
from offline_render import render
from validate_sharpen_s2 import gaussian, params

W, H = 256, 128
ROW = 80
S_ROWS = (15, 16, 16, 14, 1, 1, 30)


def validate(baseline, s2b, candidate, output, runtime_check=False):
    read_package(baseline); read_package(s2b)
    new, _ = read_package(candidate)
    if new.get('sharpen_experiment', {}).get('id') != 'sharpen-s2c':
        raise ValueError('Not an S2c sharpen package')
    output.mkdir(parents=True, exist_ok=False)
    lut = np.ones((1, 256, 4), dtype=np.float32)
    constants = {0: [[0, 1, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
    def tone(package, name, image, **controls):
        return render(package/FIXES/f'{TONE}-ps_replace.bin', output/name, W, H, textures={0: image, 1: lut},
                      constants=constants, textures1d=params(**controls))[0, 0]

    # Same DLAA-like fixture as S2 plus a glowing lamp.
    rng = np.random.default_rng(1)
    sharp = np.full((H, W), .15)
    sharp[:, 48:96] = .6
    for c in range(110, 150, 6): sharp[:, c] = .9
    sharp[:, 160:] = .3 + rng.normal(0, .06, (H, W - 160))
    sharp[100:112, 20:32] = 8.0
    soft = np.maximum(gaussian(sharp, 1.2), 0) + gaussian(np.where(sharp > 1, sharp, 0), 6) * .25
    image = np.ones((H, W, 4), dtype=np.float32)
    image[..., :3] = soft.astype(np.float32)[..., None] * np.array([1, .8, .65], np.float32)
    report = {'status': 'pass', 'source': 'synthetic Gaussian-softened inputs; not game captures',
              'game_verified': False, 'visual_improvement_verified': False, 'modes': {}}

    for label, z in ((0, 0), (1, 1)):
        assert np.array_equal(tone(baseline, f't2b-l{label}', image, label=label, z=z),
                              tone(candidate, f'off-l{label}', image, label=label, z=z)), 'Off changed'
    def lum(img): return img[..., :3].mean(-1)
    def metrics(img, off):
        row = lum(img)[ROW, 30:70]; lo, hi = row[:10].mean(), row[-10:].mean(); t = (row - lo) / (hi - lo)
        xs = np.arange(len(t))
        width = float(np.interp(.9, t[10:30], xs[10:30]) - np.interp(.1, t[10:30], xs[10:30]))
        halo = float(max(row.max() - hi, lo - row.min()) / (hi - lo) * 100)
        ring = np.zeros((H, W), dtype=bool); ring[94:118, 14:38] = True; ring[100:112, 20:32] = False
        return {'edge_width_px': width, 'edge_halo_pct': halo, 'strand_contrast': float(np.ptp(lum(img)[ROW, 108:152])),
                'lamp_rim_darkening': float(np.max(lum(off)[ring] - lum(img)[ring]))}
    for mode in (0, 1):
        off = tone(candidate, f'm{mode}-off', image, mode=mode)
        info = {'off': metrics(off, off)}
        for level, s2b_level, name in ((2, 1, 'medium'), (3, 2, 'strong')):
            mine = tone(candidate, f'm{mode}-{name}', image, mode=mode, level=level)
            ref = tone(s2b, f'm{mode}-s2b-{name}', image, mode=mode, level=s2b_level)
            assert np.array_equal(mine, ref), f'Mode {mode} {name} must equal S2b exactly'
            info[name] = metrics(mine, off)
        light = tone(candidate, f'm{mode}-light', image, mode=mode, level=1)
        info['light'] = metrics(light, off)
        o, l, m = info['off'], info['light'], info['medium']
        assert m['edge_width_px'] < l['edge_width_px'] < o['edge_width_px'], f'Mode {mode}: light edge not between off and medium'
        assert o['strand_contrast'] < l['strand_contrast'] < m['strand_contrast'], f'Mode {mode}: light strands not between'
        assert l['edge_halo_pct'] <= m['edge_halo_pct'] and l['lamp_rim_darkening'] <= m['lamp_rim_darkening'] + 1e-6
        # Still clearly visible: at least a third of medium's edge and strand gain.
        assert (o['edge_width_px'] - l['edge_width_px']) > (o['edge_width_px'] - m['edge_width_px']) / 3, 'Light too weak on edges'
        assert (l['strand_contrast'] - o['strand_contrast']) > (m['strand_contrast'] - o['strand_contrast']) / 3, 'Light too weak on strands'
        report['modes'][f'mode{mode}'] = info

    labelled = np.zeros((H, W), dtype=bool); labelled[24:46, 24:72] = True
    for level, rgb in ((1, (.5, 1.0, .45)), (2, (.45, .8, 1.0)), (3, (1.0, .55, .15))):
        shown = tone(candidate, f'label-{level}', image, label=1, level=level)
        hidden = tone(candidate, f'nolabel-{level}', image, label=0, level=level)
        assert np.array_equal(shown[~labelled], hidden[~labelled]), 'Label changed pixels outside its bounds'
        for y, bits in enumerate(S_ROWS):
            for x in range(5):
                if (bits >> (4 - x)) & 1:
                    assert np.allclose(shown[28 + y * 2, 52 + x * 2, :3], rgb, atol=1e-6), f'S glyph colour at level {level}'
    report['indicator'] = {'light': 'green', 'medium': 'light blue', 'strong': 'orange'}

    if runtime_check:
        shipped = render(candidate/FIXES/f'{TONE}-ps_replace.bin', output/'runtime-tone', W, H,
                         textures={0: image, 1: lut}, constants=constants, runtime_package=candidate)[0, 0]
        expected = tone(candidate, 'runtime-ref', image, mode=1, label=0, z=1, level=1)
        error = float(np.abs(shipped - expected).max())
        assert error < 1e-4, f'Shipped startup must be A + dither + light sharpening ({error})'
        report['official_1_3_16_runtime'] = {'startup': 'A, dither on, S2c light, labels hidden', 'max_error_vs_warp': error}
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 's2b', 'candidate', 'output'): p.add_argument(name, type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.baseline, a.s2b, a.candidate, a.output, a.runtime_check)
