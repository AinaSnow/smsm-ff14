"""Real WARP draws for T2b dithering inside tone mapping and the vignette; not game captures."""
import argparse
import json
from pathlib import Path
import numpy as np
from manage_preview import ROOT, encoded, read_package
from build_dither_t2 import FIXES, TONE, VIGNETTE, R10, EXTRACTION
from offline_render import render

W, H = 512, 64
D_BOX = (slice(28, 42), slice(40, 50))
D_ROWS = (28, 18, 17, 17, 17, 18, 28)
R10_COPY = '23d27700572e0c4d'


def params(x=0, mode=1, label=0, z=0):
    p = np.zeros((8, 4), dtype=np.float32); p[0, 0] = x; p[7, :3] = (mode, label, z)
    return {120: p}


def validate(baseline, candidate, output, runtime_check=False, r10=ROOT/R10, extraction=EXTRACTION):
    old, _ = read_package(baseline)
    new, _ = read_package(candidate)
    if new.get('dither_experiment', {}).get('id') != 'dither-t2b':
        raise ValueError('Not a T2b dither package')
    game = {s['Hash']: extraction/s['File'] for s in
            json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders'] if s['Profile'] == 'ps_5_0'}
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'pass', 'source': 'synthetic HDR ramps and constants; not game captures',
              'game_verified': False, 'visual_improvement_verified': False}

    # Tone input: neutral and warm HDR ramps spanning dark to clipped highlights.
    source = np.ones((H, W, 4), dtype=np.float32)
    levels = np.geomspace(.0005, 8, W).astype(np.float32)
    colours = np.array([[1, 1, 1], [1, .65, .45]], dtype=np.float32)
    source[:, :, :3] = colours[np.arange(H) % 2][:, None, :] * levels[None, :, None]
    source[:, :, 3] = np.linspace(0, 1, W)
    lut = np.ones((1, 256, 4), dtype=np.float32)
    constants = {0: [[0, 1, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
    tone_old = baseline/FIXES/f'{TONE}-ps_replace.bin'
    tone_new = candidate/FIXES/f'{TONE}-ps_replace.bin'
    def tone(binary, name, **controls):
        return render(binary, output/name, W, H, textures={0: source, 1: lut}, constants=constants,
                      textures1d=params(**controls))[0, 0]

    # Off: every tone mode and label state is byte-identical to the deployed A default.
    for mode in range(4):
        for label in (0, 1):
            a = tone(tone_old, f'old-m{mode}-l{label}', mode=mode, label=label)
            b = tone(tone_new, f'off-m{mode}-l{label}', mode=mode, label=label, z=0)
            assert np.array_equal(a, b), f'Dither off changed mode {mode} label {label}'
    report['off_identical_to_a_default'] = {'modes': 4, 'label_states': 2}

    # On: the noise must be exactly r10's output dither applied to the dither-off image.
    rows = np.ones(H, dtype=bool); rows[D_BOX[0]] = False
    for mode in (1, 0):
        off = tone(tone_new, f'off-m{mode}', mode=mode, z=0)
        on = tone(tone_new, f'on-m{mode}', mode=mode, z=1)
        reference = render(r10/FIXES/f'{R10_COPY}-ps_replace.bin', output/f'r10-copy-m{mode}', W, H,
                           textures={0: off}, textures1d=params(x=1))[0, 0]
        assert np.array_equal(on, reference), f'Mode {mode} noise differs from r10 output dither'
        noise = on[..., :3] - off[..., :3]
        assert np.array_equal(on[..., 3], off[..., 3]), 'Alpha changed'
        assert np.abs(noise).max() <= 1/255 + 1e-6, 'Noise above one 8-bit step'
        assert not noise[(off[..., :3] <= 0) | (off[..., :3] >= 1)].any(), 'Black/white/HDR values changed'
        mid = (off[..., :3] > 2/255) & (off[..., :3] < 1 - 2/255)
        assert np.count_nonzero(noise[mid]) > .9 * mid.sum(), 'Dither missing in mid tones'
        bias = float(noise[mid].mean())
        assert abs(bias) < .1/255, 'Dither is biased'
        if mode == 1:
            # Banding proxy: neutral rows share one value per column, so the column mean after
            # 8-bit quantization shows how closely the displayed average follows the exact value.
            neutral = rows & (np.arange(H) % 2 == 0)
            cols = (off[0, :, 0] > .02) & (off[0, :, 0] < .98)
            def column_error(img):
                q = np.round(img[neutral][:, cols, 0] * 255)
                return float(np.abs(q.mean(0) - off[0, cols, 0] * 255).mean())
            report['tone_a'] = {'equals_r10_output_dither_exactly': True, 'max_abs_noise': float(np.abs(noise).max()),
                                'mid_tone_mean_bias': bias,
                                'column_mean_error_8bit_off': column_error(off),
                                'column_mean_error_8bit_on': column_error(on)}
            assert report['tone_a']['column_mean_error_8bit_on'] < report['tone_a']['column_mean_error_8bit_off'] / 2, \
                'Dither must reduce averaged 8-bit error'

    # Indicator: D only with label and dither on; only inside its box.
    on_label = tone(tone_new, 'on-label', mode=1, label=1, z=1)
    off_label = tone(tone_new, 'off-label', mode=1, label=1, z=0)
    on_plain = tone(tone_new, 'on-plain', mode=1, label=0, z=1)
    mask = np.zeros((H, W), dtype=bool); mask[24:46, 24:72] = True
    assert np.array_equal(on_label[~mask], on_plain[~mask]), 'Label changed pixels outside its bounds'
    for y, bits in enumerate(D_ROWS):
        for x in range(5):
            pixel = on_label[28+y*2:30+y*2, 40+x*2:42+x*2, :3]
            if (bits >> (4-x)) & 1:
                assert np.allclose(pixel, .95, atol=1e-6), 'D glyph mismatch'
                assert not np.allclose(off_label[28+y*2, 40+x*2, :3], .95), 'D drawn while dither off'
    report['indicator'] = {'bounds': [40, 28, 50, 42], 'only_when_label_and_dither_on': True}

    # Vignette: off equals the game shader, on equals r10.
    vconst = {0: [[1.2, .9, .35, .6], [0, 0, 0, 0]]}
    def vig(binary, name, z):
        return render(binary, output/name, W, H, constants=vconst, textures1d=params(z=z))[0, 0]
    vnew = candidate/FIXES/f'{VIGNETTE}-ps_replace.bin'
    voff, von = vig(vnew, 'vig-off', 0), vig(vnew, 'vig-on', 1)
    vgame = vig(game[VIGNETTE], 'vig-game', 0)
    vr10 = vig(r10/FIXES/f'{VIGNETTE}-ps_replace.bin', 'vig-r10', 0)
    assert np.abs(voff - vgame).max() < 1e-6, 'Vignette off differs from the game shader'
    assert np.array_equal(von, vr10), 'Vignette on must equal r10 exactly'
    report['vignette'] = {'off_equals_game': True, 'on_equals_r10_exactly': True,
                          'max_alpha_noise': float(np.abs(von[..., 3] - voff[..., 3]).max())}

    if runtime_check:
        # Shipped INI: x7=1 (A), y7=0, z7=1; 3DMigoto fills t120 itself.
        shipped = render(tone_new, output/'runtime-tone', W, H, textures={0: source, 1: lut},
                         constants=constants, runtime_package=candidate)[0, 0]
        expected = tone(tone_new, 'runtime-reference', mode=1, label=0, z=1)
        assert np.allclose(shipped, expected, atol=2e-5, rtol=3e-6), 'Shipped startup state mismatch'
        vrun = render(vnew, output/'runtime-vig', W, H, constants=vconst, runtime_package=candidate)[0, 0]
        assert np.allclose(vrun, von, atol=2e-6), 'Runtime vignette must start with dithering on'
        report['official_1_3_16_runtime'] = {'startup': 'A, label hidden, dither on',
                                             'tone_max_error_vs_warp': float(np.abs(shipped - expected).max())}
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path); p.add_argument('candidate', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.baseline, a.candidate, a.output, a.runtime_check)
