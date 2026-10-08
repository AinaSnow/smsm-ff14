"""Create an immutable REVIEW bundle, never an installable or live capture package."""
import argparse
import json
from pathlib import Path
from manage_preview import ROOT, digest, encoded, read_package

TARGETS = {
    'fullscreen': dict(shader='415a922293923fa4', resources={
        'ps-cb0':'common', 'ps-cb1':'camera', 'ps-t10':'view-position', 'ps-t5':'encoded-normal'}),
    'mesh': dict(shader='980154264a89fba1', resources={
        'ps-cb1':'common', 'ps-cb3':'camera', 'vs-cb0':'possible-camera-A',
        'vs-cb2':'possible-camera-B', 'ps-t2':'depth', 'ps-t4':'encoded-normal'})}


def fragment(name, target):
    counter = '$smsm_capture_' + name
    lines = ['; REVIEW ONLY: do not copy over d3dx.ini or install as an include.',
             '; Merge requires a new immutable package and configuration validation.',
             '; CPU command-list variables only; no IniParams or new GPU bindings.',
             '[Constants]', 'global $smsm_capture_arm = 0', f'global {counter} = 0',
             '', '[Present]', f'post {counter} = 0', '', '[Hunting]',
             '; analyse_frame = no_modifiers VK_F8',
             'analyse_options = buf dds mono', '',
             '[ShaderOverrideSMSMCapture'+name.title()+']', 'hash = '+target['shader'],
             f'if frame_analysis && $smsm_capture_arm == 1 && {counter} < 2']
    for resource in target['resources']:
        options = 'dump_cb buf desc mono' if '-cb' in resource else 'dump_tex dds desc mono'
        lines.append(f'  pre dump = {options} {resource}')
    lines.extend([f'  {counter} = {counter} + 1', 'endif', ''])
    return '\n'.join(lines)


def build(output, baseline, audit_path):
    baseline = baseline.resolve()
    manifest, receipt = read_package(baseline)  # Verify every immutable baseline file.
    raw_audit = audit_path.read_bytes(); audit = json.loads(raw_audit)
    if audit.get('game_projection_verified') is not False or not audit.get('targets'):
        raise ValueError('Expected unresolved camera-binding audit')
    output = output.resolve()
    if output.is_relative_to(baseline):
        raise ValueError('Review output cannot be placed inside immutable baseline')
    output.mkdir(parents=True, exist_ok=False)
    files = {}
    for name, target in TARGETS.items():
        content = fragment(name, target).encode()
        filename = name+'.ini.disabled'
        (output/filename).write_bytes(content); files[filename] = digest(content)
    result = dict(schema=1, type='capture-review-only', client_build=manifest['client_build'],
        default_enabled=False, installable=False, native_ini_parser_tested=False,
        baseline=str(baseline), baseline_manifest_sha256=digest(receipt),
        camera_audit_sha256=digest(raw_audit), historical_capture_sha256=audit['source_sha256'],
        targets=TARGETS, files=files, maximum_selected_draws_per_target_per_frame=2,
        notes=['Choose ONE fragment per diagnostic package; do not merge duplicate Constants/Present/Hunting sections verbatim',
            'F8 commented, CPU arm defaults zero, no hold or deferred-context capture; no shader, DLL or resource binding changes',
            'Count limits are draft command-list logic, not yet verified in the shipped DLL; no hard byte/memory/time limit claimed',
            'Full-screen t10 provides position but no independently confirmed depth at this draw',
            'Mesh t2 provides depth but v6 interpolated position is not a texture that this dump command can export',
            'Upstream 1.3.16 RSSetViewports logging records a pointer, not numeric viewport; this bundle does not fill that gap',
            'Do not combine across draws based on pointer/hash alone; require producer/write lineage and numeric viewport evidence',
            'DDS import initially supports only typed single-mip single-slice DX10 float formats; retain unsupported originals',
            'Before arming: parser/runtime and count-limit smoke validation, stopped-game immutable install/backup, and resource-size review'],
        sources=['repo d3dx.ini frame-analysis documentation',
            'https://raw.githubusercontent.com/bo3b/3Dmigoto/1.3.16/DirectX11/CommandList.cpp',
            'https://raw.githubusercontent.com/bo3b/3Dmigoto/1.3.16/DirectX11/FrameAnalysis.cpp'])
    (output/'review.json').write_bytes(encoded(result))
    print(json.dumps(dict(output=str(output), installable=False, files=files), indent=2))
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output', type=Path)
    p.add_argument('--baseline',type=Path,default=ROOT/'artifacts/preview-2026.09.15-r10-managed')
    p.add_argument('--audit',type=Path,default=ROOT/'artifacts/camera-binding-audit-v2/report.json')
    a=p.parse_args();build(a.output,a.baseline,a.audit)
