"""Real WARP draws for S2 radius-2 sharpening in tone mapping; synthetic DLAA-like soft inputs, not game captures."""
import argparse
from pathlib import Path
import numpy as np
from manage_preview import encoded, read_package
from build_dither_t2 import FIXES, TONE
from offline_render import render

W, H = 256, 128
S_ROWS = (15, 16, 16, 14, 1, 1, 30)
ROW = 80   # analysis row, below the label area


def gaussian(a, sigma):
    r = int(3 * sigma) + 1
    k = np.exp(-np.arange(-r, r + 1) ** 2 / (2 * sigma * sigma)); k /= k.sum()
    f = lambda v: np.convolve(np.pad(v, r, mode='edge'), k, 'valid')
    return np.apply_along_axis(f, 0, np.apply_along_axis(f, 1, a))


def params(mode=1, label=0, z=0, level=0.0):
    p = np.zeros((8, 4), dtype=np.float32); p[7, :3] = (mode, label, z); p[6, 0] = level
    return {120: p}


def validate(baseline, candidate, output, runtime_check=False):
    read_package(baseline)
    new, _ = read_package(candidate)
    if new.get('sharpen_experiment', {}).get('id') != 'sharpen-s2':
        raise ValueError('Not an S2 sharpen package')
    output.mkdir(parents=True, exist_ok=False)
    lut = np.ones((1, 256, 4), dtype=np.float32)
    constants = {0: [[0, 1, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
    def tone(package, name, image, **controls):
        return render(package/FIXES/f'{TONE}-ps_replace.bin', output/name, W, H, textures={0: image, 1: lut},
                      constants=constants, textures1d=params(**controls))[0, 0]
    report = {'status': 'pass', 'source': 'synthetic Gaussian-softened (sigma 1.2) inputs; not game captures',
              'game_verified': False, 'visual_improvement_verified': False}

    # Sharp scene softened like DLAA/TAA: step edge, 1-px bright strands (hair), texture, HDR highlight, black.
    rng = np.random.default_rng(1)
    sharp = np.full((H, W), .15)
    sharp[:, 48:96] = .6
    for c in range(110, 150, 6): sharp[:, c] = .9
    sharp[:, 160:] = .3 + rng.normal(0, .06, (H, W - 160))
    sharp[100:112, 20:32] = 8.0
    sharp[100:112, 34:46] = 0.0
    soft = np.maximum(gaussian(sharp, 1.2), 0).astype(np.float32)
    soft[100:112, 34:46] = 0       # keep an exact black patch
    image = np.ones((H, W, 4), dtype=np.float32); image[..., :3] = soft[..., None] * np.array([1, .8, .65], np.float32)
    image[..., 3] = np.linspace(0, 1, W)[None, :]

    # Off: identical to the deployed T2b tone shader.
    for mode in (0, 1):
        for label in (0, 1):
            for z in (0, 1):
                assert np.array_equal(tone(baseline, f't2b-m{mode}-l{label}-z{z}', image, mode=mode, label=label, z=z),
                                      tone(candidate, f'off-m{mode}-l{label}-z{z}', image, mode=mode, label=label, z=z)), \
                    f'Sharpen off changed mode {mode} label {label} dither {z}'
    report['off_identical_to_t2b'] = True

    flat = np.full((H, W, 4), .3, dtype=np.float32)
    flat_off = tone(candidate, 'flat-off', flat)
    flat_error = max(float(np.abs(tone(candidate, f'flat-{lv}', flat, level=lv) - flat_off).max()) for lv in (1, 2))
    assert flat_error < 1e-5, 'Sharpening changed a flat image'

    def lum(img): return img[..., :3].mean(-1)
    def edge(img):
        row = lum(img)[ROW, 30:70]; lo, hi = row[:10].mean(), row[-10:].mean(); t = (row - lo) / (hi - lo)
        xs = np.arange(len(t))
        width = float(np.interp(.9, t[10:30], xs[10:30]) - np.interp(.1, t[10:30], xs[10:30]))
        halo = float(max(row.max() - hi, lo - row.min()) / (hi - lo) * 100)
        return width, halo
    def strands(img): return float(np.ptp(lum(img)[ROW, 108:152]))
    def texture(img): return float(lum(img)[60:96, 164:252].std())
    results = {}
    for mode in (0, 1):
        off = tone(candidate, f'm{mode}-off', image, mode=mode)
        level = {'off': {'edge_width_px': edge(off)[0], 'strand_contrast': strands(off), 'texture_std': texture(off)}}
        previous = level['off']
        for lv, name, halo_limit, k in ((1, 'medium', 7, .2), (2, 'strong', 15, .4)):
            on = tone(candidate, f'm{mode}-{name}', image, mode=mode, level=lv)
            assert np.isfinite(on).all() and np.array_equal(on[..., 3], off[..., 3]), 'Alpha or finiteness changed'
            assert np.array_equal(on[102:110, 36:44], off[102:110, 36:44]), 'Black patch changed'
            assert on[..., :3].min() >= 0, 'Negative output'
            width, halo = edge(on)
            stats = {'edge_width_px': width, 'edge_halo_pct': halo, 'strand_contrast': strands(on), 'texture_std': texture(on),
                     'highlight_max': float(on[100:112, 20:32, :3].max()), 'highlight_max_off': float(off[100:112, 20:32, :3].max())}
            assert halo <= halo_limit, f'Mode {mode} {name}: halo {halo:.1f}% above {halo_limit}%'
            # Highlights: brighter by at most k of the local range (no fireflies at lamp edges).
            assert stats['highlight_max'] <= stats['highlight_max_off'] * (1 + k) * 1.01, f'Mode {mode} {name}: highlight spike'
            assert width < previous['edge_width_px'] and stats['strand_contrast'] > previous['strand_contrast'], \
                f'Mode {mode} {name}: must be clearly sharper than the previous level'
            level[name] = previous = stats
        # Visible separation targets from the numpy prototype.
        assert level['medium']['strand_contrast'] > 1.15 * level['off']['strand_contrast'], 'Medium too weak on strands'
        assert level['strong']['strand_contrast'] > 1.35 * level['off']['strand_contrast'], 'Strong too weak on strands'
        assert level['medium']['edge_width_px'] < .8 * level['off']['edge_width_px'], 'Medium too weak on edges'
        assert level['strong']['edge_width_px'] < .6 * level['off']['edge_width_px'], 'Strong too weak on edges'
        results[f'mode{mode}'] = level
    report['levels'] = results
    report['flat_image_max_change'] = flat_error

    # Indicator: S light blue at 1, orange at 2, absent at 0; only inside the label box.
    labelled = np.zeros((H, W), dtype=bool); labelled[24:46, 24:72] = True
    for lv, rgb in ((1, (.45, .8, 1.0)), (2, (1.0, .55, .15))):
        shown = tone(candidate, f'label-{lv}', image, label=1, level=lv)
        hidden = tone(candidate, f'nolabel-{lv}', image, label=0, level=lv)
        assert np.array_equal(shown[~labelled], hidden[~labelled]), 'Label changed pixels outside its bounds'
        for y, bits in enumerate(S_ROWS):
            for x in range(5):
                if (bits >> (4 - x)) & 1:
                    assert np.allclose(shown[28 + y * 2, 52 + x * 2, :3], rgb, atol=1e-6), 'S glyph mismatch'
    report['indicator'] = {'bounds': [52, 28, 62, 42], 'medium': 'light blue', 'strong': 'orange'}

    if runtime_check:
        shipped = render(candidate/FIXES/f'{TONE}-ps_replace.bin', output/'runtime-tone', W, H,
                         textures={0: image, 1: lut}, constants=constants, runtime_package=candidate)[0, 0]
        expected = tone(candidate, 'runtime-ref', image, mode=1, label=0, z=1, level=1)
        error = float(np.abs(shipped - expected).max())
        # Neighbour taps are point-sampled at texel centres, so hardware and WARP should agree closely.
        assert error < 1e-4, f'Shipped startup must be A + dither + medium sharpening ({error})'
        report['official_1_3_16_runtime'] = {'startup': 'A, dither on, sharpening medium, labels hidden',
                                             'max_error_vs_warp': error}
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path); p.add_argument('candidate', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.baseline, a.candidate, a.output, a.runtime_check)
