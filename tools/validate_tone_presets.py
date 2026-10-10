"""Real WARP draws of T1 modes against an independent numpy reference; not game captures."""
import argparse
import copy
from pathlib import Path
import numpy as np
from manage_preview import encoded, read_package, digest, RECEIPT
from build_tone_presets import BASELINE, BINARY, MODES
from offline_render import render

LUMA = np.array([.2126, .7152, .0722])
LABEL = (slice(24, 46), slice(24, 72))
# Glyph rows for A, B, C (same table as the shader).
GLYPHS = {1: (14,17,17,31,17,17,17), 2: (30,17,17,30,17,17,30), 3: (14,17,16,16,16,17,14)}
ACCENTS = {0: (.2,.65,1), 1: (.3,.9,.35), 2: (1,.45,.12), 3: (.75,.4,1)}


def curve(x):
    """genericTonemap(x, 1.6, 1, 0.18, 0.227, 64) in float64."""
    mc, hc = .18**1.6, 64.0**1.6
    b = (-mc + hc*.227) / ((hc-mc)*.227)
    c = (hc*mc - hc*mc*.227) / ((hc-mc)*.227)
    xc = np.power(np.maximum(x, 0), 1.6)
    return np.clip(xc / (xc*b + c), 0, 1)


def reference(src, exposure, gain):
    """R10 and A/B/C outputs for constant-gain LUT fixtures."""
    hdr = np.maximum(src, 0)
    white = curve(1/exposure + .125)
    game = np.sqrt(gain) * hdr * exposure
    smsm = curve(hdr) / white
    peak = hdr.max(-1, keepdims=True)
    mapped = curve(peak) / white
    safe = np.where(peak > 1e-6, peak, 1)
    hue = np.where(peak > 1e-6, hdr * mapped / safe, 0)
    ratio = np.clip((smsm @ LUMA) / np.maximum(game @ LUMA, 1e-4), 0, 4)[..., None]
    roll = np.clip((mapped - .7) / .3, 0, 1)
    chalk = hue + (mapped - hue) * .5 * roll * roll
    return {0: .5*game + .5*smsm, 1: hue, 2: game*ratio, 3: chalk}, mapped[..., 0]


def validate(baseline, candidate, output, runtime_check=False):
    old, receipt = read_package(baseline)
    new, _ = read_package(candidate)
    if digest(receipt) != BASELINE or new.get('tone_experiment', {}).get('baseline_manifest_sha256') != BASELINE:
        raise ValueError('Unexpected comparison packages')
    output.mkdir(parents=True, exist_ok=False)
    # Neutral, warm skin-like, saturated red, green, blue and cyan HDR ramps.
    colors = np.array([[1,1,1],[1,.65,.45],[1,.08,.02],[.08,1,.05],[.03,.08,1],[.05,1,1]], dtype=np.float32)
    levels = np.concatenate(([0], np.geomspace(.0001, 16, 511))).astype(np.float32)
    source = np.ones((64, len(levels), 4), dtype=np.float32)
    source[:, :, :3] = colors[np.arange(64) % len(colors), None, :] * levels[None, :, None]
    source[:, :, 3] = np.linspace(0, 1, len(levels))
    rows = np.ones(64, dtype=bool); rows[LABEL[0]] = False   # label rows checked separately
    cases = []

    def draw(package, name, constants, lut, controls=None):
        resources = {}
        if controls is not None:
            params = np.zeros((8, 4), dtype=np.float32); params[7, :2] = controls
            resources = {120: params}
        return render(package/BINARY, output/name, len(levels), 64, textures={0: source, 1: lut},
                      constants=constants, textures1d=resources)[0, 0]

    for index, (exposure, gain) in enumerate(((.25, 1), (1, 1), (4, 1), (1, .25))):
        lut = np.ones((1, 256, 4), dtype=np.float32); lut[:, :, :3] = gain
        constants = {0: [[0, exposure, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
        expected, mapped = reference(source[..., :3].astype(np.float64), exposure, gain)
        base = draw(baseline, f'{index}-c2', constants, lut)
        # Self-check: the numpy model must reproduce the accepted R10 output first.
        model_error = float(np.max(np.abs(base[..., :3] - expected[0])))
        assert model_error < 1e-4, f'Reference model disagrees with R10 ({model_error})'
        case = {'exposure': exposure, 'synthetic_lut_gain': gain, 'reference_vs_r10_max_error': model_error}
        for mode in range(4):
            out = draw(candidate, f'{index}-mode{mode}', constants, lut, (mode, 0))
            assert np.isfinite(out).all(), 'Non-finite output'
            assert np.array_equal(out[..., 3], source[..., 3]), 'Alpha changed'
            if mode == 0:
                assert np.array_equal(out, base), 'Mode 0 must reproduce R10 exactly'
                continue
            rgb = out[rows, :, :3]
            ref = expected[mode][rows]
            error = float(np.max(np.abs(rgb - ref) / np.maximum(1, np.abs(ref))))
            assert error < 1e-4, f'Mode {mode} differs from reference ({error})'
            assert rgb.min() >= 0, 'Negative output'
            info = {'max_relative_error_vs_reference': error, 'peak': float(rgb.max())}
            src = source[rows, :, :3]
            valid = src.max(-1) > 1e-3
            if mode in (1, 2):
                # A keeps the source hue; B keeps the game tone-map hue (here equal to the source).
                ratio = lambda a: a[valid] / a[valid].max(-1, keepdims=True)
                hue_error = float(np.max(np.abs(ratio(rgb) - ratio(src))))
                assert hue_error < 2e-4, f'Mode {mode} shifted hue'
                info['hue_ratio_max_error'] = hue_error
            if mode == 3:
                hue = draw(candidate, f'{index}-mode3-hue', constants, lut, (1, 0))[rows, :, :3]
                below = mapped[rows] <= .7
                assert below.any() and (~below).any(), 'Fixture must cover both sides of the roll start'
                assert np.array_equal(rgb[below], hue[below]), 'C changed tones below its roll start'
                info['pixels_equal_to_A_below_roll'] = int(below.sum())
            if mode in (1, 3):
                steps = np.diff(out[0, :, :3], axis=0)
                assert steps.min() > -2e-6, 'Neutral curve reverses'
            case[MODES[mode]] = info
        cases.append(case)

    # Output above 1 must survive: no ceiling in any mode (W < 1 makes peaks exceed 1).
    assert any(case[MODES[1]]['peak'] > 1 for case in cases), 'Fixture never exceeds 1; ceiling untested'

    # Labels: stay inside bounds, keep alpha, draw the expected letter.
    lut = np.ones((1, 256, 4), dtype=np.float32)
    constants = {0: [[0, 1, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
    mask = np.zeros((64, len(levels)), dtype=bool); mask[LABEL] = True
    labelled = {}
    for mode in range(4):
        plain = draw(candidate, f'label-off-{mode}', constants, lut, (mode, 0))
        shown = labelled[mode] = draw(candidate, f'label-on-{mode}', constants, lut, (mode, 1))
        assert np.array_equal(shown[~mask], plain[~mask]), 'Label changed pixels outside its bounds'
        assert np.array_equal(shown[..., 3], plain[..., 3]), 'Label changed alpha'
        if mode:
            for y, bits in enumerate(GLYPHS[mode]):
                for x in range(5):
                    want = ACCENTS[mode] if (bits >> (4-x)) & 1 else (.025, .025, .025)
                    assert np.allclose(shown[28+y*2, 28+x*2, :3], want, atol=1e-6), f'Glyph mismatch in mode {mode}'
            # Single letter: the second and third cells stay background.
            assert np.allclose(shown[28:42, 40:64, :3], .025, atol=1e-6), 'Extra glyphs drawn'
    assert len({labelled[m][mask].tobytes() for m in range(4)}) == 4, 'Mode labels must differ'

    report = {'status': 'pass', 'source': 'synthetic HDR ramps and constant-gain LUTs; not game captures',
              'baseline_shader_sha256': old['files'][BINARY], 'candidate_shader_sha256': new['files'][BINARY],
              'modes': MODES, 'mode0_equals_r10_exactly': True, 'output_ceiling': 'none',
              'label_bounds': [24, 24, 72, 46], 'label_alpha_unchanged': True,
              'game_verified': False, 'visual_improvement_verified': False, 'cases': cases}
    if runtime_check:
        original = new
        results = []
        for mode in range(4):
            # Isolated startup fixture: only the initial x7 differs; 3DMigoto fills t120 itself.
            package = output/f'runtime-fixture-{mode}'; package.mkdir()
            manifest = copy.deepcopy(original)
            for name in manifest['files']:
                data = (candidate/name).read_bytes()
                if name == 'd3dx.ini': data = data.replace(b'x7 = 0\ny7 = 1', f'x7 = {mode}\ny7 = 1'.encode())
                path = package/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
                manifest['files'][name] = digest(data)
            manifest['isolated_test_fixture'] = True
            (package/RECEIPT).write_bytes(encoded(manifest))
            actual = render(candidate/BINARY, output/f'runtime-draw-{mode}', len(levels), 64,
                            textures={0: source, 1: lut}, constants=constants, runtime_package=package)[0, 0]
            assert np.isfinite(actual).all()
            assert np.allclose(actual, labelled[mode], atol=2e-5, rtol=3e-6), 'Runtime IniParams output mismatch'
            results.append({'initial_x7': mode, 'max_error_vs_warp': float(np.max(np.abs(actual-labelled[mode])))})
        report['official_1_3_16_runtime_startup_checks'] = results
        report['runtime_note'] = 'Separate child processes verify real IniParams initialization; no key presses synthesized'
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path); p.add_argument('candidate', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.baseline, a.candidate, a.output, a.runtime_check)
