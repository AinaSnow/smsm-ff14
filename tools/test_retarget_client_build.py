"""Check client-build retargeting: unchanged files, review record, refusal when a replaced shader changed."""
import json
import tempfile
from pathlib import Path
import unittest
import manage_preview as m
from retarget_client_build import retarget

PACKAGE = m.ROOT/'artifacts/r11-sharpen-s2c'
OLD = m.ROOT.parent/'smsm-ff14/artifacts/client-2026.09.15'


def fake_extraction(root, build, change=None):
    data = json.loads((OLD/'manifest.json').read_text(encoding='utf-8'))
    data['ClientBuild'] = build
    if change:
        for shader in data['Shaders']:
            if shader['Hash'] == change:
                shader['Sha256'] = '0' * 64
    root.mkdir()
    (root/'manifest.json').write_text(json.dumps(data), encoding='utf-8')
    return root


class RetargetTests(unittest.TestCase):
    def test_unchanged_shaders_only_relabel_the_build(self):
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='retarget-test-') as temp:
            root = Path(temp)
            new = fake_extraction(root/'new', '2099.01.01.0000.0000')
            record = retarget(PACKAGE, OLD, new, root/'out')
            self.assertEqual((record['removed'], record['added']), (0, 0))
            old_manifest, _ = m.read_package(PACKAGE)
            manifest, _ = m.read_package(root/'out')
            self.assertEqual(manifest['files'], old_manifest['files'])
            self.assertEqual(manifest['client_build'], '2099.01.01.0000.0000')
            self.assertEqual(set(manifest['client_build_reviews'][0]['replaced_shaders_unchanged']),
                             {s['hash'] for s in old_manifest['shaders']})

    def test_changed_replaced_shader_is_refused(self):
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='retarget-test-') as temp:
            root = Path(temp)
            new = fake_extraction(root/'new', '2099.01.01.0000.0000', change='72a656dfd52149ad')
            with self.assertRaises(ValueError):
                retarget(PACKAGE, OLD, new, root/'out')
            self.assertFalse((root/'out').exists())


if __name__ == '__main__':
    unittest.main()
