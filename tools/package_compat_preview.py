"""Package supported unverified compatibility or tone candidates without user data."""
import argparse
from pathlib import Path
import zipfile
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package


def package_preview(package, output):
    manifest, receipt = read_package(package)
    candidate = manifest.get('compatibility_candidate', {})
    identifier = candidate.get('id')
    if identifier not in {'r11-compat-c2', 'r11-tone-highlights-h1', 'r11-tone-highlights-h2', 'r11-tone-highlights-h3'} or candidate.get('game_verified') is not False:
        raise ValueError('Expected a supported explicitly unverified candidate')
    highlights = identifier != 'r11-compat-c2'
    highlight_doc = {'r11-tone-highlights-h2':'TONE-COMPARE-H2.md',
                     'r11-tone-highlights-h3':'TONE-HIGHLIGHTS-H3.md'}.get(identifier,'TONE-HIGHLIGHTS-H1.md')
    if highlights and manifest.get('tone_experiment', {}).get('visual_improvement_verified') is not False:
        raise ValueError('Highlight experiment must retain its unverified status')
    if manifest['profiles'][manifest['default_profile']] != []:
        raise ValueError('Compatibility package must default to zero replacements')
    entries = {'package/'+n: (package/n).read_bytes() for n in manifest['files']}
    entries['package/'+RECEIPT] = receipt
    for name in ('manage_preview.py', 'configure_compat_viewports.py', 'validate_d3d11.py'):
        entries['tools/'+name] = (ROOT/'tools'/name).read_bytes()
    for name in ('MANAGEMENT.md', '3DMIGOTO-COMPATIBILITY.md', 'PLAN-3DMIGOTO-RETURN-2026-10-10.md'):
        entries['docs/'+name] = (ROOT/'docs'/name).read_bytes()
    if highlights:
        for name in {'TONE-HIGHLIGHTS-H1.md', 'TONE-COMPARE-H2.md', highlight_doc}:
            entries['docs/'+name] = (ROOT/'docs'/name).read_bytes()
    entries['README.md'] = (ROOT/('docs/'+highlight_doc if highlights else 'README.md')).read_bytes()
    checksums = {n: digest(v) for n, v in entries.items()}
    entries['SHA256SUMS.json'] = encoded(checksums)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 10, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    with zipfile.ZipFile(output) as z:
        for name, sha in checksums.items():
            if digest(z.read(name)) != sha:
                raise ValueError('Archive verification failed: '+name)
    sha = digest(output.read_bytes())
    output.with_suffix(output.suffix+'.sha256').write_text(f'{sha}  {output.name}\n')
    print(f'Verified {len(checksums)} entries. Candidate only, no game acceptance: {sha}')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('package', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    package_preview(a.package, a.output)
