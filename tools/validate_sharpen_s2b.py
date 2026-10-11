"""Real WARP draws: S2b equals S2 below white, equals off above 1.1 x white, and removes lamp rims."""
import argparse
from pathlib import Path
import numpy as np
from manage_preview import encoded, read_package
from build_dither_t2 import FIXES, TONE
from offline_render import render
from validate_sharpen_s2 import gaussian, params

W, H = 256, 128
FADE = (0.9, 1.05)
TAPS = [(0, 0)] + [(dx, dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1),
                                           (2, 0), (-2, 0), (0, 2), (0, -2))]


def curve(x):
    mc, hc = .18 ** 1.6, 64.0 ** 1.6
    b = (-mc + hc * .227) / ((hc - mc) * .227); c = (hc * mc - hc * mc * .227) / ((hc - mc) * .227)
    xc = np.power(np.maximum(x, 0), 1.6)
    return np.clip(xc / (xc * b + c), 0, 1)


def validate(baseline, s2, candidate, output, runtime_check=False):
    read_package(baseline); read_package(s2)
    new, _ = read_package(candidate)
    if new.get('sharpen_experiment', {}).get('id') != 'sharpen-s2b':
        raise ValueError('Not an S2b sharpen package')
    output.mkdir(parents=True, exist_ok=False)
    lut = np.ones((1, 256, 4), dtype=np.float32)
    constants = {0: [[0, 1, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
    white = 1 / 1 + 32 / 256
    def tone(package, name, image, **controls):
        return render(package/FIXES/f'{TONE}-ps_replace.bin', output/name, W, H, textures={0: image, 1: lut},
                      constants=constants, textures1d=params(**controls))[0, 0]

    # Normal-brightness detail (as in S2) plus two lamps with glow (overbright cores, soft falloff).
    rng = np.random.default_rng(1)
    sharp = np.full((H, W), .15)
    sharp[:, 48:96] = .6
    for c in range(110, 150, 6): sharp[:, c] = .9
    sharp[:, 160:] = .3 + rng.normal(0, .06, (H, W - 160))
    sharp[60:72, 10:22] = 8.0
    sharp[60:72, 26:34] = 3.0
    soft = np.maximum(gaussian(sharp, 1.2), 0)
    glow = gaussian(np.where(sharp > 1, sharp, 0), 6) * .25
    linear = (soft + glow).astype(np.float32)
    image = np.ones((H, W, 4), dtype=np.float32); image[..., :3] = linear[..., None] * np.array([1, .85, .6], np.float32)

    # Neighbourhood display brightness exactly as the shader sees it (13 taps, max channel, clamp-to-edge).
    padded = np.pad(image[..., :3].max(-1), 2, mode='edge')
    peak = np.max([padded[2 + dy:2 + dy + H, 2 + dx:2 + dx + W] for dx, dy in TAPS], 0)
    display = curve(peak) / curve(white)
    lo_, hi_ = FADE
    below, above = display <= lo_ - 1e-4, display >= hi_ + 1e-4
    assert below.sum() > 1000 and above.sum() > 50, 'Fixture must cover both sides'

    report = {'status': 'pass', 'source': 'synthetic Gaussian-softened scene with glowing lamps; not game captures',
              'fade': 'smoothstep(0.9, 1.05) of SMSM display brightness of the 13-tap peak',
              'game_verified': False, 'visual_improvement_verified': False, 'modes': {}}
    for t2b_check in ((0, 0), (1, 1)):
        assert np.array_equal(tone(baseline, f't2b-{t2b_check}', image, label=t2b_check[0], z=t2b_check[1]),
                              tone(candidate, f'off-{t2b_check}', image, label=t2b_check[0], z=t2b_check[1])), 'Off changed'
    for mode in (0, 1):
        off = tone(candidate, f'm{mode}-off', image, mode=mode)
        info = {}
        for level, name in ((1, 'medium'), (2, 'strong')):
            ref = tone(s2, f'm{mode}-s2-{name}', image, mode=mode, level=level)
            new_ = tone(candidate, f'm{mode}-s2b-{name}', image, mode=mode, level=level)
            normal_error = float(np.abs(new_ - ref)[below].max())
            assert normal_error < 1e-5, f'Mode {mode} {name}: changed normal-brightness sharpening ({normal_error})'
            bright_error = float(np.abs(new_ - off)[above].max())
            assert bright_error < 1e-5, f'Mode {mode} {name}: still sharpens around overbright light ({bright_error})'
            # Dark rim: how far the ring around the 8.0 lamp drops below the unsharpened image.
            ring = np.zeros((H, W), dtype=bool); ring[54:78, 4:40] = True; ring[60:72, 10:34] = False
            def rim(img): return float(np.max(lum(off)[ring] - lum(img)[ring]))
            info[name] = {'normal_max_diff_vs_s2': normal_error, 'bright_max_diff_vs_off': bright_error,
                          'lamp_rim_darkening_s2': rim(ref), 'lamp_rim_darkening_s2b': rim(new_)}
        report['modes'][f'mode{mode}'] = info
    report['pixels'] = {'normal_brightness': int(below.sum()), 'overbright_neighbourhood': int(above.sum())}

    if runtime_check:
        shipped = render(candidate/FIXES/f'{TONE}-ps_replace.bin', output/'runtime-tone', W, H,
                         textures={0: image, 1: lut}, constants=constants, runtime_package=candidate)[0, 0]
        expected = tone(candidate, 'runtime-ref', image, mode=1, label=0, z=1, level=1)
        error = float(np.abs(shipped - expected).max())
        assert error < 1e-4, f'Shipped startup must be A + dither + medium S2b ({error})'
        report['official_1_3_16_runtime'] = {'startup': 'A, dither on, S2b medium, labels hidden', 'max_error_vs_warp': error}
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


def lum(img): return img[..., :3].mean(-1)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 's2', 'candidate', 'output'): p.add_argument(name, type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.baseline, a.s2, a.candidate, a.output, a.runtime_check)
