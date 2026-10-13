"""Real WARP draws of the patched sun-light shaders: off == game, N0 == game with no sun, N1 == r10 normal shadows.

Synthetic G-buffer from validate_single_light (plane / tilted plane / sphere / normal-map ridges); not game captures.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from manage_preview import ROOT, encoded, read_package
from build_dither_t2 import FIXES, TONE
from build_shadow_n1 import HOSTS, EXTRACTION
from offline_render import render
from validate_single_light import fixture, original_inputs

R10 = ROOT/'artifacts/preview-2026.09.15-r10-managed'
N_ROWS = (17, 25, 21, 19, 17, 17, 17)


def controls(on=0, diag=0, label=0):
    p = np.zeros((8, 4), dtype=np.float32); p[5, :2] = (on, diag); p[7] = (1, label, 1, 1); p[6] = (1, 2, 0, 0)
    return {120: p}


def validate(baseline, candidate, output, runtime_check=False, extraction=EXTRACTION):
    read_package(baseline)
    new, _ = read_package(candidate)
    if new.get('shadow_experiment', {}).get('id') != 'shadow-n1':
        raise ValueError('Not an N1 package')
    output.mkdir(parents=True, exist_ok=False)
    records = {s['Hash']: s for s in json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders']}
    report = {'status': 'pass', 'source': 'synthetic G-buffer (plane, tilted plane, sphere, normal-map ridges); not game captures',
              'game_verified': False, 'visual_improvement_verified': False, 'hosts': {}}
    sun = np.array([.55, .35, -.76]); sun /= np.linalg.norm(sun)
    low_sun = np.array([.85, .2, -.48]); low_sun /= np.linalg.norm(low_sun)
    for target in HOSTS:
        game = extraction/records[target]['File']
        patched = candidate/FIXES/f'{target}-ps.bin'
        r10 = R10/FIXES/f'{target}-ps.bin'
        info = {}
        for geometry in ('plane', 'tilt', 'sphere', 'bumps'):
            f = fixture(width=96, height=64, geometry='plane' if geometry == 'bumps' else geometry)
            if geometry == 'bumps':
                # Normal-map ridges (cloth folds / brick seams): view-space normals tilt +-x in 12 px waves.
                x = np.arange(96)[None, :] + .5
                n = np.stack([np.sin(x * 2 * np.pi / 12) * 3 * np.ones((64, 1)), np.zeros((64, 96)), -np.ones((64, 96))], -1)
                n /= np.linalg.norm(n, axis=-1, keepdims=True)
                f['textures'][3][..., :3] = n * .5 + .5
            textures, constants, structured = original_inputs(f)
            constants[2] = constants[2].copy()
            # Low sun for the ridges so their back slopes face away from it (n.L < 0).
            constants[2][1, :3] = low_sun if geometry == 'bumps' else sun
            def draw(binary, name, t120=None, tex=None):
                return render(binary, output/f'{target}-{geometry}-{name}', f['width'], f['height'], tex or textures,
                              constants, structured, targets=2, textures1d=t120)[0]
            base = draw(game, 'game')
            off = draw(patched, 'off', controls())
            assert np.array_equal(off, base), f'{target} {geometry}: off differs from game'
            dark = dict(textures); dark[8] = np.zeros_like(textures[8])
            no_sun = draw(game, 'game-no-sun', tex=dark)
            diag = draw(patched, 'diag', controls(diag=1))
            assert np.array_equal(diag, no_sun), f'{target} {geometry}: N0 differs from game without sun'
            on = draw(patched, 'on', controls(on=1))
            old = draw(r10, 'r10')
            error = float(np.abs(on - old).max())
            assert error < 1e-5, f'{target} {geometry}: N1 differs from r10 normal shadows ({error})'
            assert np.isfinite(on).all()
            assert (on[0, ..., :3] <= base[0, ..., :3] + 1e-6).all(), f'{target} {geometry}: N1 brightened pixels'
            changed = int((np.abs(on - base).max(-1).max(0) > 1e-4).sum())
            sun_effect = int((np.abs(no_sun - base).max(-1).max(0) > 1e-4).sum())
            info[geometry] = {'off_equals_game': True, 'n0_equals_game_without_sun': True, 'n1_vs_r10_max_error': error,
                              'n1_changed_pixels': changed, 'pixels_lit_by_sun': sun_effect,
                              'n1_mean_darkening': float((base[0, ..., :3] - on[0, ..., :3]).mean())}
        assert info['bumps']['n1_changed_pixels'] > 100, f'{target}: no normal shadow on normal-map ridges'
        assert info['bumps']['pixels_lit_by_sun'] > 0, f'{target}: sun does not reach the fixture'
        report['hosts'][target] = info

    # Tone label N: only with labels on, only inside the extended box; tone unchanged otherwise.
    H, W = 64, 160
    src = np.ones((H, W, 4), dtype=np.float32); src[..., :3] = np.geomspace(.001, 8, W, dtype=np.float32)[None, :, None]
    lut = np.ones((1, 256, 4), dtype=np.float32)
    tconst = {0: [[0, 1, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
    def tone(package, name, **kw):
        return render(package/FIXES/f'{TONE}-ps_replace.bin', output/name, W, H, textures={0: src, 1: lut},
                      constants=tconst, textures1d=controls(**kw))[0, 0]
    area = np.zeros((H, W), dtype=bool); area[24:46, 88:102] = True
    for on in (0, 1):
        assert np.array_equal(tone(baseline, f'tone-base-{on}', on=on), tone(candidate, f'tone-new-{on}', on=on))
        a = tone(baseline, f'tone-base-label-{on}', on=on, label=1); b = tone(candidate, f'tone-new-label-{on}', on=on, label=1)
        assert np.array_equal(a[~area], b[~area]), 'Label changed outside the N area'
        for y, bits in enumerate(N_ROWS):
            for x in range(5):
                if (bits >> (4 - x)) & 1:
                    want = (.55, .85, 1) if on else (.025, .025, .025)
                    assert np.allclose(b[28 + y * 2, 88 + x * 2, :3], want, atol=1e-6), 'N glyph'
    report['tone_indicator'] = {'box': [88, 28, 98, 42], 'background_extended_to': 102}

    if runtime_check:
        f = fixture(width=96, height=64, geometry='plane')
        x = np.arange(96)[None, :] + .5
        n = np.stack([np.sin(x * 2 * np.pi / 12) * 3 * np.ones((64, 1)), np.zeros((64, 96)), -np.ones((64, 96))], -1)
        f['textures'][3][..., :3] = n / np.linalg.norm(n, axis=-1, keepdims=True) * .5 + .5
        textures, constants, structured = original_inputs(f)
        constants[2] = constants[2].copy(); constants[2][1, :3] = low_sun
        results = {}
        for target in HOSTS:
            patched = candidate/FIXES/f'{target}-ps.bin'
            shipped = render(patched, output/f'runtime-{target}', 96, 64, textures, constants, structured, targets=2,
                             runtime_package=candidate)[0]
            on = render(patched, output/f'runtime-ref-{target}', 96, 64, textures, constants, structured, targets=2,
                        textures1d=controls(on=1))[0]
            off = render(patched, output/f'runtime-off-{target}', 96, 64, textures, constants, structured, targets=2,
                         textures1d=controls())[0]
            error, error_off = float(np.abs(shipped - on).max()), float(np.abs(shipped - off).max())
            assert error < 1e-3 and (error_off > 10 * error or error_off == 0), f'{target}: runtime must start with N1 on'
            results[target] = {'max_error_vs_warp_on': error, 'max_error_vs_off': error_off}
        report['official_1_3_16_runtime'] = results
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'output'): p.add_argument(name, type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.baseline, a.candidate, a.output, a.runtime_check)
