"""Assemble the final r11 package and local ZIP from the deployed, user-accepted N1 package.

Files are copied byte for byte; only the manifest changes (final id, accepted defaults, which
effects were proven to execute in game). Performance stays unverified until measured.
"""
import argparse
import copy
import re
import zipfile
from pathlib import Path
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package

N1 = 'ba7afa24537a18c8e2eed76ce6e83490b7d5d73183f89c5169477f6153c3c307'
ACCEPTED = {
    'tone': ('accepted-default-a', 'labels drawn by the tone shader visible in game; user chose A (2026-10-10)', 'TONE-PRESETS-T1.md'),
    'dithering': ('accepted-default-on', 'sky banding removed in a dither on/off pair; dither also lives in the tone shader (2026-10-11)', 'DITHER-T2.md'),
    'radial': ('accepted-default-smsm', 'sun glare changes with Ctrl+F5 in game; user chose SMSM (2026-10-13)', 'RADIAL-T2.md'),
    'dof': ('accepted-default-strong', 'D0 purple diagnostic in /gpose; user chose D1 strong (2026-10-14)', 'DOF-D1.md'),
    'shadows': ('accepted-default-on', 'N0 removed direct sunlight; user chose N1 on, no flicker seen (2026-10-14)', 'SHADOW-N1.md'),
}
DOCS = ['RELEASE-r11.md', 'MANAGEMENT.md', '3DMIGOTO-COMPATIBILITY.md', 'PLAN-3DMIGOTO-RETURN-2026-10-10.md',
        'SHARPEN-S1.md'] + [doc for *_, doc in ACCEPTED.values()]
TOOLS = ['manage_preview.py', 'configure_compat_viewports.py', 'validate_d3d11.py', 'retarget_client_build.py']


def build(source, output):
    manifest, receipt = read_package(source)
    if digest(receipt) != N1:
        raise ValueError('Expected the deployed, accepted N1 package')
    output.mkdir(parents=True, exist_ok=False)
    for name in manifest['files']:
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((source/name).read_bytes())
    final = copy.deepcopy(manifest)
    for effect, (status, evidence, doc) in ACCEPTED.items():
        final['effects'][effect].update(status=status, execution_verified=True, performance_verified=False,
                                        execution_evidence=evidence, record=f'docs/{doc}')
    final['compatibility_candidate'].update(
        id='r11', stage='final-local',
        acceptance='every effect chosen by the user in game, 2026-10-10..14; performance and long-session stability pending',
        source_package_sha256=N1)
    final['sharpen_experiment']['status'] = 'accepted-default-light'
    final['shadow_experiment']['status'] = 'accepted-default-on'
    final['release'] = {'version': 'r11', 'published': False, 'performance_verified': False,
                        'defaults': {'tone': 'A', 'dither': 'on', 'sharpen': 'light', 'light_shafts': 'SMSM',
                                     'gpose_bokeh': 'strong', 'normal_shadows': 'on', 'labels': 'hidden',
                                     'diagnostics': 'off'},
                        'notes': 'docs/RELEASE-r11.md'}
    (output/RECEIPT).write_bytes(encoded(final))
    read_package(output)
    return final


def package_zip(package, archive):
    manifest, receipt = read_package(package)
    if manifest['compatibility_candidate']['id'] != 'r11' or manifest['profiles'][manifest['default_profile']] != []:
        raise ValueError('Expected the final r11 package with a zero-replacement default profile')
    entries = {'package/' + n: (package/n).read_bytes() for n in manifest['files']}
    entries['package/' + RECEIPT] = receipt
    for name in TOOLS:
        entries['tools/' + name] = (ROOT/'tools'/name).read_bytes()
    for name in DOCS:
        entries['docs/' + name] = (ROOT/'docs'/name).read_bytes()
    # README sits at the archive root; its relative links point into docs/.
    entries['README.md'] = re.sub(r'\]\(([A-Za-z0-9-]+\.md)\)', r'](docs/\1)',
                                  (ROOT/'docs/RELEASE-r11.md').read_text(encoding='utf-8')).encode()
    checksums = {n: digest(v) for n, v in entries.items()}
    entries['SHA256SUMS.json'] = encoded(checksums)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 14, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    with zipfile.ZipFile(archive) as z:
        for name, sha in checksums.items():
            if digest(z.read(name)) != sha:
                raise ValueError('Archive verification failed: ' + name)
    sha = digest(archive.read_bytes())
    # LF only, so `sha256sum -c` works on any platform.
    archive.with_suffix(archive.suffix + '.sha256').write_bytes(f'{sha}  {archive.name}\n'.encode())
    return len(checksums), sha


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--zip', type=Path, help='also write the local release ZIP (never published)')
    a = p.parse_args()
    build(a.source, a.output)
    print(f'Prepared {a.output}')
    if a.zip:
        count, sha = package_zip(a.output, a.zip)
        print(f'Verified {count} entries in {a.zip}: {sha}')
