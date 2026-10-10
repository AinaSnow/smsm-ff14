"""Real WARP draws for S1 sharpening in tone mapping; synthetic inputs, not game captures."""
import argparse
from pathlib import Path
import numpy as np
from manage_preview import encoded, read_package
from build_dither_t2 import FIXES, TONE
from offline_render import render

W, H = 256, 128
S_ROWS = (15, 16, 16, 14, 1, 1, 30)


def params(mode=1, label=0, z=0, sharp=0.0):
    p = np.zeros((8, 4), dtype=np.float32); p[7, :3] = (mode, label, z); p[6, 0] = sharp
    return {120: p}


def validate(baseline, candidate, output, runtime_check=False):
    read_package(baseline)
    new, _ = read_package(candidate)
    if new.get('sharpen_experiment', {}).get('id') != 'sharpen-s1':
        raise ValueError('Not an S1 sharpen package')
    output.mkdir(parents=True, exist_ok=False)
    lut = np.ones((1, 256, 4), dtype=np.float32)
    constants = {0: [[0, 1, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
    def tone(package, name, image, **controls):
        return render(package/FIXES/f'{TONE}-ps_replace.bin', output/name, W, H, textures={0: image, 1: lut},
                      constants=constants, textures1d=params(**controls))[0, 0]
    report = {'status': 'pass', 'source': 'synthetic inputs; not game captures',
              'game_verified': False, 'visual_improvement_verified': False}

    # Neutral test image: hard edges, a soft edge, fine stripes, texture noise and an HDR highlight.
    rng = np.random.default_rng(3)
    g = np.full((H, W), .18, dtype=np.float32)
    g[:, 64:128] = .5                                     # hard step
    g[:, 128:192] = np.linspace(.05, .9, 64)[None, :]     # soft ramp
    g[:64, 192:] = np.where(np.arange(64)[None, :] % 4 < 2, .6, .2)   # fine stripes
    g[64:, 192:] = .3 + rng.normal(0, .05, (64, 64))      # texture
    g[90:100, 20:30] = 8.0                                # highlight
    g[100:110, 20:30] = 0.0                               # pure black patch
    image = np.ones((H, W, 4), dtype=np.float32); image[..., :3] = np.maximum(g, 0)[..., None]
    image[..., 3] = np.linspace(0, 1, W)[None, :]
    colour = image.copy(); colour[..., :3] *= np.array([1, .75, .55], dtype=np.float32)

    # Off: identical to the deployed T2b tone shader for modes, labels and dither states.
    for mode in (0, 1):
        for label in (0, 1):
            for z in (0, 1):
                a = tone(baseline, f't2b-m{mode}-l{label}-z{z}', colour, mode=mode, label=label, z=z)
                b = tone(candidate, f'off-m{mode}-l{label}-z{z}', colour, mode=mode, label=label, z=z)
                assert np.array_equal(a, b), f'Sharpen off changed mode {mode} label {label} dither {z}'
    report['off_identical_to_t2b'] = True

    flat = np.full((H, W, 4), .3, dtype=np.float32)
    flat_off = tone(candidate, 'flat-off', flat)
    flat_on = tone(candidate, 'flat-strong', flat, sharp=1.0)
    flat_error = float(np.abs(flat_on - flat_off).max())
    assert flat_error < 1e-5, 'Sharpening changed a flat image'

    rows = np.ones(H, dtype=bool); rows[20:50] = False        # keep the label area out
    interior = np.zeros((H, W), dtype=bool); interior[1:-1, 1:-1] = True; interior &= rows[:, None]
    results = {}
    for mode in (0, 1):
        off = tone(candidate, f'm{mode}-off', image, mode=mode)
        def bounds(img):
            stack = np.stack([img, np.roll(img, 1, 0), np.roll(img, -1, 0), np.roll(img, 1, 1), np.roll(img, -1, 1)])
            return stack.min(0), stack.max(0)
        lo, hi = bounds(off[..., :3])
        def gradient(img):
            lum = img[..., :3].mean(-1)
            return float(np.abs(np.diff(lum, axis=1))[interior[:, 1:]].mean())
        level = {'off': gradient(off)}
        for sharp in (.5, 1.0):
            on = tone(candidate, f'm{mode}-s{sharp}', image, mode=mode, sharp=sharp)
            assert np.isfinite(on).all() and np.array_equal(on[..., 3], off[..., 3]), 'Alpha or finiteness changed'
            # No halos: each output stays inside the tone-mapped range of its own input cross.
            overshoot = float(max((on[..., :3] - hi)[interior].max(), (lo - on[..., :3])[interior].max()))
            assert overshoot < 1e-5, f'Mode {mode} sharpness {sharp} overshoots ({overshoot})'
            assert np.array_equal(on[100:110, 20:30], off[100:110, 20:30]) or \
                float(np.abs(on[102:108, 22:28] - off[102:108, 22:28]).max()) < 1e-6, 'Black patch changed'
            level[f'{sharp}'] = gradient(on)
            level[f'max_overshoot_{sharp}'] = overshoot
        assert level['off'] < level['0.5'] < level['1.0'], 'Sharpening must raise edge contrast monotonically'
        results[f'mode{mode}'] = level
    report['edges'] = {'mean_abs_horizontal_gradient': results, 'flat_image_max_change': flat_error,
                       'halo_check': 'output within tone-mapped min/max of the 5-tap input cross'}

    # Indicator S: only with labels on, colour by level, only inside its box.
    box = np.zeros((H, W), dtype=bool); box[28:42, 52:62] = True
    plain = tone(candidate, 'label-off-sharp', colour, label=1)
    for sharp, rgb in ((.5, (.45, .8, 1.0)), (1.0, (1.0, .55, .15))):
        shown = tone(candidate, f'label-s{sharp}', colour, label=1, sharp=sharp)
        hidden = tone(candidate, f'nolabel-s{sharp}', colour, label=0, sharp=sharp)
        labelled_area = np.zeros((H, W), dtype=bool); labelled_area[24:46, 24:72] = True
        assert np.array_equal(shown[~labelled_area], hidden[~labelled_area]), 'Label changed pixels outside its bounds'
        for y, bits in enumerate(S_ROWS):
            for x in range(5):
                if (bits >> (4-x)) & 1:
                    assert np.allclose(shown[28+y*2, 52+x*2, :3], rgb, atol=1e-6), 'S glyph mismatch'
        assert not np.array_equal(shown[box], plain[box]), 'S missing'
    report['indicator'] = {'bounds': [52, 28, 62, 42], 'medium': 'light blue', 'strong': 'orange'}

    if runtime_check:
        shipped = render(candidate/FIXES/f'{TONE}-ps_replace.bin', output/'runtime-tone', W, H,
                         textures={0: colour, 1: lut}, constants=constants, runtime_package=candidate)[0, 0]
        expected = tone(candidate, 'runtime-ref', colour, mode=1, label=0, z=1, sharp=.5)
        error = float(np.abs(shipped - expected).max())
        assert error < 2e-5, 'Shipped startup must be A + dither + medium sharpening'
        report['official_1_3_16_runtime'] = {'startup': 'A, dither on, sharpening 0.5, labels hidden',
                                             'max_error_vs_warp': error}
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path); p.add_argument('candidate', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.baseline, a.candidate, a.output, a.runtime_check)
