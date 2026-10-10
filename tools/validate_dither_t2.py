"""Real WARP draws for the T2 dither switch against game originals and r10 binaries; not game captures."""
import argparse
import copy
import json
from pathlib import Path
import numpy as np
from manage_preview import encoded, read_package, digest, RECEIPT
from build_dither_t2 import FIXES, OUTPUT, VIGNETTE, R10, EXTRACTION
from manage_preview import ROOT
from offline_render import render

W, H = 256, 64
D_BOX = (slice(28, 42), slice(40, 50))
D_ROWS = (28, 18, 17, 17, 17, 18, 28)


def params(x=0, y=0, z=0):
    p = np.zeros((8, 4), dtype=np.float32); p[0, 0] = x; p[7, 1] = y; p[7, 2] = z
    return {120: p}


def validate(candidate, output, runtime_check=False, r10=ROOT/R10, extraction=EXTRACTION):
    manifest, _ = read_package(candidate)
    if manifest.get('dither_experiment', {}).get('id') != 'dither-t2':
        raise ValueError('Not a T2 dither package')
    shaders = json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders']
    game = {s['Hash']: extraction/s['File'] for s in shaders if s['Profile'] == 'ps_5_0'}
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'pass', 'source': 'synthetic ramps and constants; not game captures',
              'game_verified': False, 'visual_improvement_verified': False}

    # --- Output copy: smooth ramp across [0, 1.1], plus NaN and exact 0/1 columns.
    image = np.ones((H, W, 4), dtype=np.float32)
    ramp = np.linspace(0, 1.1, W, dtype=np.float32)
    image[:, :, :3] = ramp[None, :, None] * np.array([1, .8, .6], dtype=np.float32)
    image[:, :, 3] = np.linspace(0, 1, H)[:, None]
    image[:, 0, :3] = 0; image[:, 1, :3] = 1
    image[0:4, 2, 0] = np.nan
    def copy_draw(binary, name, **controls):
        return render(binary, output/name, W, H, textures={0: image}, textures1d=params(**controls))[0, 0]
    new = candidate/FIXES/f'{OUTPUT}-ps_replace.bin'
    old = r10/FIXES/f'{OUTPUT}-ps_replace.bin'
    original = copy_draw(game[OUTPUT], 'out-game', x=1, z=1)
    unarmed = copy_draw(new, 'out-unarmed', x=0, z=1)
    off = copy_draw(new, 'out-off', x=1, z=0)
    on = copy_draw(new, 'out-on', x=1, z=1)
    r10_on = copy_draw(old, 'out-r10-on', x=1)
    assert np.array_equal(unarmed, off), 'Unarmed copies must not dither'
    clean = np.where(np.isnan(image), 0, image)
    assert np.array_equal(off, clean), 'Off must be the plain copy with NaN cleanup'
    finite = np.isfinite(original)
    assert np.array_equal(off[finite], original[finite]), 'Off differs from the game copy on finite input'
    assert np.array_equal(on, r10_on), 'On must equal the r10 dither exactly'
    noise = on[..., :3] - clean[..., :3]
    assert np.isfinite(on).all() and np.array_equal(on[..., 3], clean[..., 3]), 'Alpha or NaN cleanup changed'
    assert np.abs(noise).max() <= 1/255 + 1e-6, 'Noise above one 8-bit step'
    assert not noise[:, :2].any(), 'Exact black/white endpoints changed'
    mid = (clean[..., :3] > 2/255) & (clean[..., :3] < 1 - 2/255)
    assert np.count_nonzero(noise[mid]) > .9 * mid.sum(), 'Dither missing in mid tones'
    bias = float(noise[mid].mean())
    assert abs(bias) < .1/255, 'Dither is biased'
    # Quantize like an 8-bit swapchain: the ramp must gain intermediate levels per block of columns.
    cols = (clean[0, :, 0] > 0) & (clean[0, :, 0] < 1)
    q_off = np.round(off[:, cols, 0] * 255); q_on = np.round(on[:, cols, 0] * 255)
    report['output_copy'] = {'off_equals_game_copy': True, 'on_equals_r10_exactly': True,
                             'unarmed_copies_unchanged': True, 'max_abs_noise': float(np.abs(noise).max()),
                             'mid_tone_mean_bias': bias,
                             'column_mean_error_8bit_off': float(np.abs(q_off.mean(0) - clean[0, cols, 0]*255).mean()),
                             'column_mean_error_8bit_on': float(np.abs(q_on.mean(0) - clean[0, cols, 0]*255).mean())}
    assert report['output_copy']['column_mean_error_8bit_on'] < report['output_copy']['column_mean_error_8bit_off'], \
        'Dither must reduce averaged 8-bit banding error'

    # Indicator: only with label and dithering on, only inside its box.
    with_label = copy_draw(new, 'out-label-on', x=1, y=1, z=1)
    label_off = copy_draw(new, 'out-label-dither-off', x=1, y=1, z=0)
    assert np.array_equal(label_off, off), 'Indicator drawn while dithering is off'
    mask = np.zeros((H, W), dtype=bool); mask[D_BOX] = True
    assert np.array_equal(with_label[~mask], on[~mask]), 'Indicator outside its box'
    for y, bits in enumerate(D_ROWS):
        for x in range(5):
            pixel = with_label[28+y*2:30+y*2, 40+x*2:42+x*2, :3]
            if (bits >> (4-x)) & 1:
                assert np.allclose(pixel, .95, atol=1e-6), 'D glyph mismatch'
            else:
                assert np.array_equal(pixel, on[28+y*2:30+y*2, 40+x*2:42+x*2, :3]), 'D background changed'
    report['indicator'] = {'bounds': [40, 28, 50, 42], 'only_when_label_and_dither_on': True}

    # --- Vignette: realistic strength, z7 off must equal the game shader.
    constants = {0: [[1.2, .9, .35, .6], [0, 0, 0, 0]]}
    def vig(binary, name, z):
        return render(binary, output/name, W, H, constants=constants, textures1d=params(z=z))[0, 0]
    vnew = candidate/FIXES/f'{VIGNETTE}-ps_replace.bin'
    vgame = vig(game[VIGNETTE], 'vig-game', 0)
    voff = vig(vnew, 'vig-off', 0); von = vig(vnew, 'vig-on', 1)
    vr10 = vig(r10/FIXES/f'{VIGNETTE}-ps_replace.bin', 'vig-r10', 0)
    vignette_error = float(np.abs(voff - vgame).max())
    assert vignette_error < 1e-6, 'Vignette off differs from the game shader'
    assert np.array_equal(von, vr10), 'Vignette on must equal r10 exactly'
    vnoise = von[..., 3] - voff[..., 3]
    inside = (voff[..., 3] > 2/128) & (voff[..., 3] < 1 - 2/128)
    assert inside.any() and np.abs(vnoise[inside]).max() <= 1/128 + 1e-6 and np.count_nonzero(vnoise[inside])
    report['vignette'] = {'off_vs_game_max_error': vignette_error, 'on_equals_r10_exactly': True,
                          'max_alpha_noise': float(np.abs(vnoise).max()),
                          'note': 'with zero vignette strength the r10 dither still adds up to 1/128 alpha of the vignette colour'}

    if runtime_check:
        # Shipped INI starts with z7=1 and label hidden; 3DMigoto fills t120 itself.
        # x stays 0 here (no tone draw in this harness), so the copy must stay plain.
        shipped = render(new, output/'runtime-out', W, H, textures={0: image}, runtime_package=candidate)[0, 0]
        assert np.array_equal(shipped, off), 'Runtime copy without the tone stage must not dither'
        vrun = render(vnew, output/'runtime-vig', W, H, constants=constants, runtime_package=candidate)[0, 0]
        assert np.allclose(vrun, von, atol=2e-6), 'Runtime vignette must start with dithering on'
        report['official_1_3_16_runtime'] = {
            'copy_without_tone_stage_plain': True, 'vignette_startup_dither_on': True,
            'note': 'separate child processes; stage marker arming needs the real frame and is not exercised here'}
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('candidate', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.candidate, a.output, a.runtime_check)
