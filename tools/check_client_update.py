"""Maintainer, after a game update: extract shaders, compare, and if every replaced shader is unchanged,
retarget the final package and build the release ZIP. Stops (and names the affected effects) otherwise.

    python tools/check_client_update.py --client-root <game root> --package artifacts/r11-final-2026.11.03 --previous artifacts/client-2026.11.03
"""
import argparse
import json
import subprocess
from pathlib import Path
from manage_preview import ROOT, read_package
from retarget_client_build import retarget, review
from build_final_r11 import package_zip


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--client-root', required=True, type=Path)
    p.add_argument('--package', required=True, type=Path, help='current final package')
    p.add_argument('--previous', required=True, type=Path, help='ShaderAudit extraction matching --package')
    a = p.parse_args(argv)
    build = (a.client_root/'game/ffxivgame.ver').read_text().strip()
    manifest, _ = read_package(a.package)
    if build == manifest['client_build']:
        print(f'Client {build} already matches {a.package}; nothing to do.')
        return
    extraction = ROOT/'artifacts'/f'client-{build[:10]}'
    if not extraction.exists():
        subprocess.run(['dotnet', 'run', '--project', str(ROOT/'tools/ShaderAudit'), '--', str(a.client_root), str(extraction)],
                       check=True)
    _, new, record = review(a.previous, extraction)
    current = {s['Hash']: s['Sha256'] for s in new['Shaders'] if s['Profile'] == 'ps_5_0'}
    changed = [s['hash'] for s in manifest['shaders'] if current.get(s['hash']) != s['original_sha256']]
    print(json.dumps(record, indent=1))
    if changed:
        effects = sorted({e for e, v in manifest['effects'].items() if set(v['shaders']) & set(changed)})
        raise SystemExit(f'Replaced shaders changed in {build}: {changed}\nAffected effects: {effects}. '
                         'These need re-porting; do not retarget.')
    output = ROOT/'artifacts'/f'r11-final-{build[:10]}'
    retarget(a.package, a.previous, extraction, output)
    archive = ROOT/'artifacts/releases'/f'smsm-r11-{build[:10]}.zip'
    count, sha = package_zip(output, archive)
    print(f'All replaced shaders unchanged. Package {output}\nZIP {archive} ({count} entries) {sha}')


if __name__ == '__main__':
    main()
