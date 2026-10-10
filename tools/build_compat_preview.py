"""Derive an immutable, zero-replacement-by-default 1.3.16 candidate from r10."""
import argparse
import copy
from pathlib import Path
import zipfile
from manage_preview import digest, encoded, read_package, selected_files, RECEIPT

R10_RECEIPT = '8fc10d0b0ab4bf8bb3dccccf4f62b4bd684dca57e8425aa010324a7b90a211ae'
RUNTIME_ARCHIVE = '1e097eaed99270f2444e3a70eff68194b751f6be19d0edadc40a780074152558'
SOURCE = 'https://github.com/bo3b/3Dmigoto/releases/download/1.3.16/3Dmigoto-1.3.16.zip'
INI = '''; SMSM R1 compatibility candidate. No hunting, exports or continuous tracing.
[Logging]
calls=0
input=0
debug=0
unbuffered=0
force_cpu_affinity=0
[System]
load_library_redirect=2
check_foreground_window=1
allow_check_interface=1
allow_create_device=1
allow_platform_update=1
[Device]
upscaling=0
full_screen=0
force_stereo=0
[Stereo]
automatic_mode=0
create_profile=0
[Hunting]
hunting=0
reload_config=no_modifiers VK_F10
reload_fixes=no_modifiers VK_F10
show_original=no_modifiers VK_F9
verbose_overlay=0
[Rendering]
shader_hash=3dmigoto
override_directory=SMSM-ShaderFixes
cache_directory=SMSM-ShaderCache
storage_directory=SMSM-ShaderFromGame
cache_shaders=0
rasterizer_disable_scissor=0
stereo_params=-1
ini_params=120
assemble_signature_comments=1
export_fixed=0
export_shaders=0
export_hlsl=0
dump_usage=0
fix_sv_position=0
'''


def build(baseline, archive, output):
    original, receipt = read_package(baseline)
    if digest(receipt) != R10_RECEIPT:
        raise ValueError('Expected the unchanged published r10 manifest')
    if digest(archive.read_bytes()) != RUNTIME_ARCHIVE:
        raise ValueError('Official 1.3.16 archive checksum mismatch')
    files = {name: (baseline/name).read_bytes() for name in selected_files(original, ['tone'])}
    with zipfile.ZipFile(archive) as z:
        for name in ('d3d11.dll', 'nvapi64.dll', 'd3dcompiler_46.dll'):
            files[name] = z.read('x64/'+name)
    files['d3dx.ini'] = INI.encode()
    manifest = copy.deepcopy(original)
    manifest['shaders'] = [s for s in original['shaders'] if s['hash'] in original['effects']['tone']['shaders']]
    manifest['effects'] = {'tone': dict(original['effects']['tone'], status='r10-scene-accepted-runtime-unverified')}
    manifest['profiles'] = {'vanilla': [], 'daily': ['tone']}
    manifest['default_profile'] = 'vanilla'
    manifest['files'] = {n: digest(v) for n, v in files.items()}
    manifest['reload'] = {'method': 'stopped-client-selection-until-live-verified', 'game_verified': False}
    manifest['compatibility_candidate'] = {
        'id': 'r11-compat-c2', 'stage': 'R1', 'runtime_version': '1.3.16',
        'source': SOURCE, 'archive_sha256': RUNTIME_ARCHIVE, 'r10_manifest_sha256': R10_RECEIPT,
        'dalamud_reference': '15.0.3.6', 'game_verified': False,
        'required_dalamud_settings': {'IsDisableViewport': True},
        'limitation': 'External composition viewports crash with both 1.3.11 and 1.3.16',
        'acceptance': 'pending zero-replacement and tone-only UI tests'}
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (output/RECEIPT).write_bytes(encoded(manifest))
    read_package(output)
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('archive', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    result = build(args.baseline, args.archive, args.output)
    print(f"Built {args.output}; default=vanilla; runtime=1.3.16; game acceptance pending")
