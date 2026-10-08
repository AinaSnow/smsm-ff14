"""Read-only, fail-closed position/pixel/depth correspondence audit.

Input metadata is a declaration, NOT proof of capture lineage or game bindings.
Even a numerical pass cannot authorize new game constant-buffer reads.
"""
import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
import struct
import numpy as np

MAX_BYTES = 512 * 1024 * 1024
FORMATS = {'rgba32f': ('<f4', 4), 'rgba16f': ('<f2', 4),
           'r32f': ('<f4', 1), 'r16f': ('<f2', 1)}
# Typed DXGI values only; typeless resources require a separately audited SRV.
DXGI = {2: 'rgba32f', 10: 'rgba16f', 41: 'r32f', 40: 'r32f', 54: 'r16f'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def half_ulp(values):
    # Compute in float64: np.spacing(float16(65504)) overflows to infinity.
    finite = np.nan_to_num(values, nan=0., posinf=65504., neginf=-65504.)
    exponent = np.frexp(np.clip(np.abs(finite), 2**-14, 65504.))[1]
    return np.ldexp(np.ones(values.shape), np.maximum(exponent-11, -24))


def unpack_pixels(raw, width, height, fmt, pitch=None):
    if fmt not in FORMATS or type(width) is not int or type(height) is not int or not (0 < width <= 16384 and 0 < height <= 16384):
        raise ValueError('Unsupported format or dimensions')
    dtype, channels = FORMATS[fmt]
    row = width * channels * np.dtype(dtype).itemsize
    pitch = row if pitch is None else pitch
    if type(pitch) is not int or pitch < row or pitch * height != len(raw):
        raise ValueError('Incorrect row pitch, truncated data, or trailing subresources')
    return np.ndarray((height, width, channels), dtype=dtype, buffer=raw,
                      strides=(pitch, channels * np.dtype(dtype).itemsize, np.dtype(dtype).itemsize)).astype(np.float64)


def read_dds(raw):
    """Restricted uncompressed DX10 2D, one mip/slice. Reject ambiguity.

    Layout: Microsoft DDS_HEADER / DDS_HEADER_DXT10; links in CAPTURE-REPROJECTION.md.
    No image/color-space conversion, no guessed typeless view, no sRGB decoding.
    """
    if len(raw) < 148 or raw[:4] != b'DDS ':
        raise ValueError('Not a DX10 DDS file')
    h = struct.unpack_from('<31I', raw, 4)
    if h[0] != 124 or h[18] != 32 or h[19] != 4 or raw[84:88] != b'DX10':
        raise ValueError('Only an explicit DX10 pixel format is supported')
    if h[5] not in (0, 1) or h[6] not in (0, 1) or h[27] != 0 or h[1] & 0x800000:
        raise ValueError('Mips, cubes, arrays and volumes are unsupported')
    dxgi, dimension, misc, count, misc2 = struct.unpack_from('<5I', raw, 128)
    if dxgi not in DXGI or dimension != 3 or count != 1 or misc != 0 or misc2 & ~7:
        raise ValueError('Unsupported DDS format, dimension or flags (including typeless)')
    fmt = DXGI[dxgi]
    pixels = unpack_pixels(raw[148:], h[3], h[2], fmt, h[4] if h[1] & 8 else None)
    return pixels, dict(format=fmt, dxgi=dxgi, width=h[3], height=h[2])


def input_bytes(root, spec):
    relative = spec['path']
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative or '..' in relative.split('/'):
        raise ValueError('Input paths must be local relative paths')
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Missing, oversized or out-of-root input')
    raw = path.read_bytes()
    if sha(raw) != spec['sha256']:
        raise ValueError('Input hash mismatch: ' + relative)
    return raw


def texture(root, spec):
    raw = input_bytes(root, spec)
    if spec['format'] == 'dds':
        pixels, info = read_dds(raw)
        return pixels, info['format']
    return unpack_pixels(raw, spec['width'], spec['height'], spec['format'], spec.get('row_pitch')), spec['format']


def identity(spec):
    snapshot = spec.get('snapshot', {})
    if not isinstance(snapshot.get('capture'), str) or not snapshot['capture'] or type(snapshot.get('draw')) is not int or snapshot['draw'] < 0 or snapshot.get('phase') != 'pre':
        raise ValueError('Explicit capture/draw/pre-phase identity required')
    return snapshot['capture'], snapshot['draw'], snapshot['phase']


def evaluate(manifest, root):
    if manifest.get('schema') != 1 or manifest.get('source_kind') not in ('synthetic', 'game'):
        raise ValueError('Unsupported audit schema/source kind')
    specs = manifest['inputs']
    if set(specs) not in ({'camera', 'position'}, {'camera', 'position', 'depth'}):
        raise ValueError('Expected camera and independent view-position, optionally depth')
    if len({identity(s) for s in specs.values()}) != 1:
        raise ValueError('Cross-frame/draw/phase resources need a separate lineage audit; cannot combine')
    camera_raw = input_bytes(root, specs['camera'])
    if not camera_raw or len(camera_raw) % 16 or len(camera_raw) > 65536:
        raise ValueError('Camera byte size must be a nonempty float4-aligned D3D11 buffer')
    camera = np.frombuffer(camera_raw, dtype='<f4').reshape(-1, 4).astype(np.float64)
    rows = manifest['projection_rows']
    if not isinstance(rows, list) or len(rows) != 4 or len(set(rows)) != 4 or any(type(r) is not int or r < 0 or r >= len(camera) for r in rows):
        raise ValueError('Projection rows outside captured buffer')
    projection = camera[rows]
    if manifest.get('matrix_convention') != 'row_dot_column_vector' or not np.isfinite(projection).all() or np.linalg.matrix_rank(projection) != 4:
        raise ValueError('Unspecified, nonfinite or singular projection matrix')
    position, position_format = texture(root, specs['position'])
    if position.shape[2] < 3:
        raise ValueError('Position requires at least XYZ')
    height, width = position.shape[:2]
    viewport = np.asarray(manifest['viewport'], dtype=float)
    if viewport.shape != (6,) or not np.isfinite(viewport).all():
        raise ValueError('Viewport must contain finite x/y/width/height/minDepth/maxDepth')
    vx, vy, vw, vh, zmin, zmax = viewport
    if vx < 0 or vy < 0 or vw <= 0 or vh <= 0 or vx+vw > width or vy+vh > height or not 0 <= zmin < zmax <= 1:
        raise ValueError('Viewport outside resource or invalid depth range')
    # This v1 importer intentionally refuses different-size/depth-resolution mappings.
    depth, depth_format = texture(root, specs['depth']) if 'depth' in specs else (None, None)
    if depth is not None and depth.shape[:2] != (height, width):
        raise ValueError('Position/depth grids differ; explicit resampling mapping is not implemented')
    y, x = np.mgrid[:height, :width].astype(float); x += .5; y += .5
    inside = (x >= vx) & (x < vx+vw) & (y >= vy) & (y < vy+vh)
    p = position[..., :3]
    valid = inside & np.isfinite(p).all(-1) & (np.max(np.abs(p), axis=-1) > 1e-8)
    if depth is not None:
        valid &= np.isfinite(depth[..., 0]) & (depth[..., 0] > zmin) & (depth[..., 0] < zmax)
    clean_p = np.where(np.isfinite(p), p, 0.)
    h = np.concatenate((clean_p, np.ones((height, width, 1))), -1) @ projection.T
    # Invalid projected points are failures, not silently discarded from the mask.
    usable = np.isfinite(h).all(-1) & (np.abs(h[..., 3]) > 1e-8)
    ndc = h[..., :3] / np.where(usable, h[..., 3], 1)[..., None]
    projected_x = vx + (ndc[..., 0]+1)*vw/2
    projected_y = vy + (1-ndc[..., 1])*vh/2
    pixel_error = np.maximum(np.abs(projected_x-x), np.abs(projected_y-y))
    depth_error = np.abs(zmin + ndc[..., 2]*(zmax-zmin) - depth[..., 0]) if depth is not None else None
    samples = int(valid.sum()); coverage = samples / max(1, int(inside.sum()))
    # Fixed base bounds; half storage gets an explicit one-ULP interval, not a
    # manually enlarged global threshold. WARP can truncate half outputs.
    pixel_tolerance, depth_tolerance = .35, 5e-5
    depth_uncertainty = np.zeros((height, width))
    if position_format == 'rgba16f':
        ulp = half_ulp(p)
        for signs in product((-1, 1), repeat=3):
            corner = np.concatenate((clean_p+ulp*np.array(signs), np.ones((height,width,1))), -1) @ projection.T
            safe = np.isfinite(corner).all(-1) & (corner[...,3]*h[...,3] > 0) & (np.abs(corner[...,3]) > 1e-8)
            usable &= safe
            corner_z = corner[...,2] / np.where(safe, corner[...,3], 1)
            depth_uncertainty = np.maximum(depth_uncertainty, np.abs(corner_z-ndc[...,2])*(zmax-zmin))
    if depth is not None and depth_format in ('r16f', 'rgba16f'):
        depth_uncertainty += half_ulp(depth[...,0])
    usable &= np.isfinite(depth_uncertainty) & (depth_uncertainty <= .002)
    pixel_ok = usable & (pixel_error <= pixel_tolerance)
    depth_ok = usable & (depth_error <= depth_tolerance+depth_uncertainty) if depth is not None else None
    tiles = set(zip(np.clip(((x[valid]-vx)*4/vw).astype(int), 0, 3),
                    np.clip(((y[valid]-vy)*4/vh).astype(int), 0, 3)))
    depth_span = float(np.ptp(p[valid, 2])) if samples else 0.
    adequate = samples >= 64 and coverage >= .25 and len(tiles) >= 12 and depth_span >= .05
    def metric(error, ok):
        return dict(maximum=float(error[valid].max()) if samples else None,
                    p99=float(np.quantile(error[valid], .99)) if samples else None,
                    passing_fraction=float(ok[valid].mean()) if samples else 0.)
    pixel_metrics = metric(pixel_error, pixel_ok)
    depth_metrics = metric(depth_error, depth_ok) if depth is not None else None
    # Background/disocclusion edges can disagree; require >=99.5% on declared valid data.
    pixel_pass = adequate and pixel_metrics['passing_fraction'] >= .995
    depth_pass = adequate and depth_metrics is not None and depth_metrics['passing_fraction'] >= .995
    independent = manifest.get('position_origin') == 'independent_view_position'
    complete = bool(pixel_pass and depth_pass and independent)
    blockers = []
    if not adequate: blockers.append('Insufficient valid spatial/depth coverage')
    if not pixel_pass: blockers.append('Pixel correspondence not established')
    if not depth_pass: blockers.append('Independent depth correspondence not established')
    if not independent: blockers.append('Position origin unknown or reconstructed from the same depth/matrix: circular evidence')
    blockers.append('Capture lineage and numeric viewport metadata require external review; declared metadata is not proof')
    return dict(schema=1, source_kind=manifest['source_kind'], samples=samples, coverage=coverage,
                occupied_tiles=len(tiles), view_z_span=depth_span, camera_bytes=len(camera_raw),
                projection_rows=rows, viewport=viewport.tolist(),
                tolerances=dict(pixel=pixel_tolerance, depth_base=depth_tolerance,
                    maximum_storage_depth_uncertainty=float(depth_uncertainty[valid].max()) if samples else None),
                pixel=pixel_metrics, depth=depth_metrics, pixel_correspondence_passed=bool(pixel_pass),
                depth_correspondence_passed=bool(depth_pass), numerical_correspondence_passed=complete,
                game_projection_verified=False, eligible_for_game_occlusion=False, blockers=blockers,
                input_sha256={k: v['sha256'] for k, v in specs.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = evaluate(json.loads(args.manifest.read_text(encoding='utf-8')), args.manifest.parent)
    report['manifest_sha256'] = sha(args.manifest.read_bytes())
    report['tool_sha256'] = sha(Path(__file__).read_bytes())
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report['numerical_correspondence_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
