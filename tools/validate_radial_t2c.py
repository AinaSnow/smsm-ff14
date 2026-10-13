"""Real WARP draws for the T2c/T2d radial blur switch and tone indicator; synthetic inputs, not game captures."""
import argparse
import json
from pathlib import Path
import numpy as np
from manage_preview import ROOT, encoded, read_package
from build_dither_t2 import FIXES, TONE, R10, EXTRACTION
from build_radial_t2c import RADIAL
from offline_render import render

W, H = 320, 180
R_ROWS = (30, 17, 17, 30, 20, 18, 17)


def params(mode=1, label=0, z=1, w=0, sharp=0):
    p = np.zeros((8, 4), dtype=np.float32); p[7] = (mode, label, z, w); p[6, 0] = sharp
    return {120: p}


def validate(baseline, candidate, output, runtime_check=False, r10=ROOT/R10, extraction=EXTRACTION):
    read_package(baseline)
    new, _ = read_package(candidate)
    if new.get('radial_experiment', {}).get('id') != 'radial-t2c':
        raise ValueError('Not a T2c/T2d radial package')
    rx0, ry0, rx1, ry1 = new['radial_experiment'].get('indicator_box', [52, 28, 62, 42])
    lx0, ly0, lx1, ly1 = new['radial_experiment'].get('label_box', [24, 24, 72, 46])
    sharp_levels = (0, 1) if 'sharpen_experiment' in new else (0,)
    # Pixels the radial build may change while labels are shown (extended label background).
    extra = np.zeros((H, W), dtype=bool); extra[ly0:ly1, 72:lx1] = True
    game = {s['Hash']: extraction/s['File'] for s in
            json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders'] if s['Profile'] == 'ps_5_0'}
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'pass', 'source': 'synthetic inputs; not game captures',
              'game_verified': False, 'visual_improvement_verified': False}

    # --- Tone: w7 only adds the R indicator while labels are shown.
    source = np.ones((H, W, 4), dtype=np.float32)
    source[:, :, :3] = np.geomspace(.001, 8, W, dtype=np.float32)[None, :, None] * np.array([1, .7, .5], dtype=np.float32)
    lut = np.ones((1, 256, 4), dtype=np.float32)
    tconst = {0: [[0, 1, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
    def tone(package, name, **controls):
        return render(package/FIXES/f'{TONE}-ps_replace.bin', output/name, W, H, textures={0: source, 1: lut},
                      constants=tconst, textures1d=params(**controls))[0, 0]
    for mode in (0, 1):
        for label in (0, 1):
            for z in (0, 1):
                for sharp in sharp_levels:
                    tag = f'm{mode}-l{label}-z{z}-s{sharp}'
                    old = tone(baseline, f'base-{tag}', mode=mode, label=label, z=z, sharp=sharp)
                    new_w0 = tone(candidate, f'w0-{tag}', mode=mode, label=label, z=z, w=0, sharp=sharp)
                    keep = ~extra if label else np.ones((H, W), dtype=bool)
                    assert np.array_equal(old[keep], new_w0[keep]), 'w7=0 changed tone output'
                    if label and extra.any():
                        assert np.allclose(new_w0[extra][:, :3], .025, atol=1e-6), 'Label background extension wrong'
                    if not label:
                        assert np.array_equal(old, tone(candidate, f'w1-{tag}', mode=mode, z=z, w=1, sharp=sharp)), \
                            'w7=1 changed tone output without labels'
    with_r = tone(candidate, 'label-r', label=1, w=1)
    without_r = tone(candidate, 'label-no-r', label=1, w=0)
    box = np.zeros((H, W), dtype=bool); box[ry0:ry1, rx0:rx1] = True
    assert np.array_equal(with_r[~box], without_r[~box]), 'R indicator outside its box'
    for y, bits in enumerate(R_ROWS):
        for x in range(5):
            if (bits >> (4-x)) & 1:
                assert np.allclose(with_r[ry0+y*2, rx0+x*2, :3], (1, .85, .3), atol=1e-6), 'R glyph mismatch'
    report['tone'] = {'w7_off_identical_to_base': True, 'w7_on_identical_without_label': True,
                      'sharpen_levels_checked': list(sharp_levels), 'r_indicator_bounds': [rx0, ry0, rx1, ry1]}

    # --- Radial: textured scene with a small bright light, full and dynamic-resolution viewports.
    rng = np.random.default_rng(7)
    scene = np.zeros((H, W, 4), dtype=np.float32)
    scene[..., :3] = rng.random((H, W, 3), dtype=np.float32) * .2
    scene[80:90, 150:160, :3] = 6.0     # light
    scene[..., 3] = 1
    rad_new = candidate/FIXES/f'{RADIAL}-ps_replace.bin'
    cases = []
    for label, viewport in (('full', [1, 1, 1, 1]), ('dynamic-75', [.75, .75, .749, .749])):
        rconst = {0: [viewport, [0, 0, 0, 0]], 1: [[.48, .47, .6, .5]]}
        def radial(binary, name, w):
            return render(binary, output/f'{label}-{name}', W, H, textures={0: scene}, constants=rconst,
                          textures1d=params(w=w))[0, 0]
        g = radial(game[RADIAL], 'game', 0)
        off = radial(rad_new, 'off', 0)
        on = radial(rad_new, 'on', 1)
        old = radial(r10/FIXES/f'{RADIAL}-ps_replace.bin', 'r10', 0)
        off_error = float(np.abs(off - g).max())
        assert off_error <= 1e-6 * max(1, float(np.abs(g).max())), f'{label}: game path differs ({off_error})'
        assert np.array_equal(on, old), f'{label}: SMSM path must equal r10 exactly'
        assert np.isfinite(on).all()
        # Ghost copies of the light along its streak: local maxima of luminance on the ray to the centre.
        def peaks(img):
            lum = img[..., :3].mean(-1)
            cx, cy = .48 * W, .47 * H
            t = np.linspace(0, 1, 400)
            xs = (155 + (155 - cx) * t * 1.5).astype(int).clip(0, W-1)
            ys = (85 + (85 - cy) * t * 1.5).astype(int).clip(0, H-1)
            line = lum[ys, xs]
            return int(np.sum((line[1:-1] > line[:-2] + .02) & (line[1:-1] >= line[2:])))
        energy = float(on[..., :3].sum() / g[..., :3].sum())
        cases.append({'viewport': label, 'game_path_max_error': off_error, 'smsm_equals_r10_exactly': True,
                      'energy_ratio_smsm_over_game': energy, 'streak_peaks_game': peaks(g), 'streak_peaks_smsm': peaks(on),
                      'mean_abs_difference': float(np.abs(on - g)[..., :3].mean())})
        assert .9 < energy < 1.1, f'{label}: SMSM changes overall energy'
    report['radial'] = cases

    if runtime_check:
        rconst = {0: [[1, 1, 1, 1], [0, 0, 0, 0]], 1: [[.48, .47, .6, .5]]}
        shipped = render(rad_new, output/'runtime-radial', W, H, textures={0: scene}, constants=rconst,
                         runtime_package=candidate)[0, 0]
        expected = render(rad_new, output/'runtime-radial-ref', W, H, textures={0: scene}, constants=rconst,
                          textures1d=params(w=1))[0, 0]
        game_path = render(rad_new, output/'runtime-radial-game-ref', W, H, textures={0: scene}, constants=rconst,
                           textures1d=params(w=0))[0, 0]
        # The isolated runtime draws on GPU hardware: bilinear taps between texels use lower-precision
        # filter weights than WARP, so compare against the peak instead of requiring WARP equality.
        error_on = float(np.abs(shipped - expected).max()); error_game = float(np.abs(shipped - game_path).max())
        assert error_on < .01 * float(scene[..., :3].max()) and error_on < error_game / 10, 'Radial must start in SMSM mode'
        tone_run = render(candidate/FIXES/f'{TONE}-ps_replace.bin', output/'runtime-tone', W, H,
                          textures={0: source, 1: lut}, constants=tconst, runtime_package=candidate)[0, 0]
        startup_sharp = 1 if 'sharpen_experiment' in new else 0
        assert np.allclose(tone_run, tone(candidate, 'runtime-tone-ref', mode=1, label=0, z=1, w=1, sharp=startup_sharp),
                           atol=1e-4, rtol=3e-6)
        report['official_1_3_16_runtime'] = {'startup': 'tone A, dither on, SMSM radial, labels hidden',
                                             'radial_max_error_vs_warp_smsm': error_on,
                                             'radial_max_error_vs_warp_game_path': error_game,
                                             'note': 'hardware bilinear filtering differs from WARP by <1% of peak'}
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path); p.add_argument('candidate', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.baseline, a.candidate, a.output, a.runtime_check)
