"""Real WARP draws for D0/D1 on the /gpose blur pass 00f2b6068017c6c6; synthetic inputs, not game captures."""
import argparse
import json
from pathlib import Path
import numpy as np
from manage_preview import encoded, read_package
from shader_compile import Compiler
from build_dither_t2 import FIXES, TONE
from build_dof_d1 import BLUR, EXTRACTION
from offline_render import render

W, H = 256, 160
B_ROWS = (30, 17, 17, 30, 17, 17, 30)
# 16 taps on four rings (pixels), passed as 8 float4 TEXCOORDs like the game's vertex shader.
VERTEX = '''
struct O { float4 p : SV_POSITION; float4 t[8] : TEXCOORD0; };
O main(uint id : SV_VertexID)
{
    O o; float2 uv = float2((id << 1) & 2, id & 2);
    o.p = float4(uv * float2(2, -2) + float2(-1, 1), 0, 1);
    float2 px = float2(1.0 / %d, 1.0 / %d);
    [unroll] for (int i = 0; i < 8; ++i) {
        float radius = 3 + 3 * (i >> 1);
        float a0 = i * 0.785398 + 0.3, a1 = a0 + 3.141593;
        o.t[i] = float4(uv + float2(cos(a0), sin(a0)) * radius * px, uv + float2(cos(a1), sin(a1)) * radius * px);
    }
    return o;
}
''' % (W, H)


def params(bokeh=0, diag=0, mode=1, label=0, z=1, w=1, sharp=1):
    p = np.zeros((8, 4), dtype=np.float32); p[7] = (mode, label, z, w); p[6, :3] = (sharp, bokeh, diag)
    return {120: p}


def validate(baseline, candidate, output, runtime_check=False, extraction=EXTRACTION):
    read_package(baseline)
    new, _ = read_package(candidate)
    if new.get('dof_experiment', {}).get('id') != 'dof-d1':
        raise ValueError('Not a D1 package')
    output.mkdir(parents=True, exist_ok=False)
    records = {s['Hash']: s for s in json.loads((extraction/'manifest.json').read_text(encoding='utf-8'))['Shaders']}
    game_blur = extraction/records[BLUR]['File']
    compiler = Compiler((candidate/'d3dcompiler_46.dll').resolve())
    (output/'vs.hlsl').write_text(VERTEX)
    vs, _ = compiler.compile(output/'vs.hlsl', 'vs_5_0')
    (output/'vs.bin').write_bytes(vs)
    report = {'status': 'pass', 'source': 'synthetic HDR scenes with CoC alpha and a 16-tap ring pattern; not game captures',
              'game_verified': False, 'visual_improvement_verified': False}

    # Scene: dim textured background (fully blurred CoC), a mid-bright patch, two point lights, near layer strip.
    rng = np.random.default_rng(5)
    scene = np.zeros((H, W, 4), dtype=np.float32)
    scene[..., :3] = .08 + rng.random((H, W, 3), dtype=np.float32) * .12
    scene[..., 3] = .85                      # far, fully blurred
    scene[:, 200:, 3] = .3                   # in-focus-ish strip: weak weights
    scene[60:64, 60:64, :3] = 6.0            # point light
    scene[100:103, 140:143, :3] = (3.0, 2.2, 1.2)
    scene[20:40, 150:190, :3] = .6           # bright but ordinary surface (u < 0.45)
    blur_new = candidate/FIXES/f'{BLUR}-ps_replace.bin'
    cases = {}
    for label, viewport in (('full', [1, 1, 1, 1]), ('dynamic-75', [.75, .75, .749, .749])):
        constants = {0: [viewport, [0, 0, 0, 0]]}
        def draw(binary, name, **controls):
            return render(binary, output/f'{label}-{name}', W, H, textures={0: scene}, constants=constants,
                          vertex=output/'vs.bin', textures1d=params(**controls))[0, 0]
        game = draw(game_blur, 'game')
        off = draw(blur_new, 'off')
        off_error = float(np.abs(off - game).max())
        assert off_error <= 1e-6 * max(1.0, float(np.abs(game).max())), f'{label}: off differs from game ({off_error})'
        diag = draw(blur_new, 'diag', diag=1)
        assert np.allclose(diag[..., :3], off[..., :3] * np.array([1, .25, 1]) + np.array([.08, 0, .08]), atol=1e-5)
        assert np.array_equal(diag[..., 3], off[..., 3]), 'Diagnostic changed alpha'
        info = {'off_vs_game_max_error': off_error}
        # Pixels whose 16 taps contain no highlight: weights identical, so D1 must equal off.
        # Taps are read at uv * viewport scale, so map each output pixel to texture space first.
        bright = (scene[..., :3].max(-1) / (1 + scene[..., :3].max(-1))) > .45
        near_tex = np.zeros_like(bright)
        ys, xs = np.nonzero(bright)
        for y, x in zip(ys, xs):
            near_tex[max(0, y - 14):y + 15, max(0, x - 14):x + 15] = True
        oy, ox = np.indices((H, W))
        ty = np.clip(((oy + .5) * viewport[1]).astype(int), 0, H - 1)
        tx = np.clip(((ox + .5) * viewport[0]).astype(int), 0, W - 1)
        near_bright = near_tex[ty, tx]
        for level, name in ((1, 'normal'), (2, 'strong')):
            d1 = draw(blur_new, name, bokeh=level)
            assert np.isfinite(d1).all()
            alpha_error = float(np.abs(d1[..., 3] - off[..., 3]).max())
            assert alpha_error < 1e-5, f'{label} {name}: alpha (CoC) changed ({alpha_error})'
            plain_error = float(np.abs(d1 - off)[~near_bright].max())
            assert plain_error < 1e-5, f'{label} {name}: changed pixels without highlights ({plain_error})'
            # Around the 6.0 light: blurred disc brightness and how flat it stays across the kernel.
            disc = (np.abs(ty - 62) < 13) & (np.abs(tx - 62) < 13)
            around = d1[..., :3].max(-1)[disc]; around_off = off[..., :3].max(-1)[disc]
            stats = {'alpha_max_error': alpha_error, 'non_highlight_max_error': plain_error,
                     'light_disc_mean': float(around.mean()), 'light_disc_mean_off': float(around_off.mean()),
                     'light_disc_area_above_half_peak_px': int((around > around.max() / 2).sum()),
                     'light_disc_area_above_half_peak_px_off': int((around_off > around_off.max() / 2).sum())}
            assert stats['light_disc_mean'] > stats['light_disc_mean_off'] * 1.2, f'{label} {name}: highlight not brighter'
            info[name] = stats
        assert info['strong']['light_disc_mean'] > info['normal']['light_disc_mean'], 'Strong must exceed normal'
        cases[label] = info
    report['blur'] = cases

    # Tone label: B only with labels on; tone output otherwise unchanged from the base for every y6.
    source = np.ones((H, W, 4), dtype=np.float32)
    source[..., :3] = np.geomspace(.001, 8, W, dtype=np.float32)[None, :, None]
    lut = np.ones((1, 256, 4), dtype=np.float32)
    tconst = {0: [[0, 1, 1, 0]], 1: [[0, 0, 1, 0], [0, 1, 0, 0]]}
    def tone(package, name, **controls):
        return render(package/FIXES/f'{TONE}-ps_replace.bin', output/name, W, H, textures={0: source, 1: lut},
                      constants=tconst, textures1d=params(**controls))[0, 0]
    extra = np.zeros((H, W), dtype=bool); extra[24:46, 78:90] = True
    for bokeh in (0, 1, 2):
        base_plain = tone(baseline, f'tone-base-{bokeh}', bokeh=bokeh)
        assert np.array_equal(base_plain, tone(candidate, f'tone-new-{bokeh}', bokeh=bokeh)), 'Tone changed without labels'
        base_label = tone(baseline, f'tone-base-label-{bokeh}', bokeh=bokeh, label=1)
        new_label = tone(candidate, f'tone-new-label-{bokeh}', bokeh=bokeh, label=1)
        box = np.zeros((H, W), dtype=bool); box[28:42, 76:86] = True
        assert np.array_equal(base_label[~(extra | box)], new_label[~(extra | box)]), 'Label changed outside B area'
        for y, bits in enumerate(B_ROWS):
            for x in range(5):
                if (bits >> (4 - x)) & 1:
                    want = (.025, .025, .025) if bokeh == 0 else ((1, .95, .6) if bokeh == 1 else (1, .5, .3))
                    assert np.allclose(new_label[28 + y * 2, 76 + x * 2, :3], want, atol=1e-6), 'B glyph'
    report['tone_indicator'] = {'box': [76, 28, 86, 42], 'background_extended_to': 90}

    if runtime_check:
        startup = new['dof_experiment']['comparison']['startup']
        startup_level = new['dof_experiment']['comparison']['states'].index(startup)
        constants = {0: [[1, 1, 1, 1], [0, 0, 0, 0]]}
        shipped = render(blur_new, output/'runtime-blur', W, H, textures={0: scene}, constants=constants,
                         vertex=output/'vs.bin', runtime_package=candidate)[0, 0]
        expected = render(blur_new, output/'runtime-blur-ref', W, H, textures={0: scene}, constants=constants,
                          vertex=output/'vs.bin', textures1d=params(bokeh=startup_level))[0, 0]
        off = render(blur_new, output/'runtime-blur-off', W, H, textures={0: scene}, constants=constants,
                     vertex=output/'vs.bin', textures1d=params())[0, 0]
        error = float(np.abs(shipped - expected).max()); error_off = float(np.abs(shipped - off).max())
        assert error < 1e-4 * max(1, float(expected.max())) and error < error_off / 10, f'Runtime must start with {startup}'
        report['official_1_3_16_runtime'] = {'startup': f'D1 {startup}, diagnostic off', 'max_error_vs_warp': error,
                                             'max_error_vs_off': error_off}
    (output/'report.json').write_bytes(encoded(report))
    print(encoded(report).decode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'output'): p.add_argument(name, type=Path)
    p.add_argument('--runtime-check', action='store_true')
    a = p.parse_args(); validate(a.baseline, a.candidate, a.output, a.runtime_check)
