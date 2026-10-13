"""Copy a managed package to a new client build after a shader compatibility review.

The manager refuses packages whose client_build differs from the game. When a game
update leaves the replaced shaders untouched, this copies the package unchanged except
for client_build and a review record. It requires both extractions (from
tools/ShaderAudit) and checks that every replaced shader exists in the new client with
the same original SHA-256. It never edits the old package.
"""
import argparse
import copy
import json
from pathlib import Path
from manage_preview import RECEIPT, digest, encoded, read_package


def review(old_extraction, new_extraction):
    old = json.loads((old_extraction/'manifest.json').read_text(encoding='utf-8'))
    new = json.loads((new_extraction/'manifest.json').read_text(encoding='utf-8'))
    key = lambda s: (s['Hash'], s['Profile'], s['Sha256'])
    old_set, new_set = {key(s) for s in old['Shaders']}, {key(s) for s in new['Shaders']}
    return old, new, {'from_build': old['ClientBuild'], 'to_build': new['ClientBuild'],
                      'old_unique_shaders': len(old_set), 'new_unique_shaders': len(new_set),
                      'removed': len(old_set - new_set), 'added': len(new_set - old_set),
                      'old_extraction_manifest_sha256': digest((old_extraction/'manifest.json').read_bytes()),
                      'new_extraction_manifest_sha256': digest((new_extraction/'manifest.json').read_bytes())}


def retarget(package, old_extraction, new_extraction, output):
    manifest, _ = read_package(package)
    old, new, record = review(old_extraction, new_extraction)
    if manifest['client_build'] != old['ClientBuild']:
        raise ValueError(f"Package is for {manifest['client_build']}, old extraction is {old['ClientBuild']}")
    current = {s['Hash']: s['Sha256'] for s in new['Shaders'] if s['Profile'] == 'ps_5_0'}
    checked = {}
    for shader in manifest['shaders']:
        if current.get(shader['hash']) != shader['original_sha256']:
            raise ValueError(f"{shader['hash']} changed or missing in {new['ClientBuild']}; rebuild required")
        checked[shader['hash']] = shader['original_sha256']
    output.mkdir(parents=True, exist_ok=False)
    for name in manifest['files']:
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((package/name).read_bytes())
    result = copy.deepcopy(manifest)
    result['client_build'] = new['ClientBuild']
    result.setdefault('client_build_reviews', []).append(dict(record, replaced_shaders_unchanged=checked,
                                                              source_package_build=manifest['client_build']))
    if 'compatibility_candidate' in result:
        result['compatibility_candidate']['id'] += '-' + new['ClientBuild'][:10]
    (output/RECEIPT).write_bytes(encoded(result))
    read_package(output)
    return record


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'old_extraction', 'new_extraction', 'output'):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(retarget(a.package, a.old_extraction, a.new_extraction, a.output), indent=1))
