"""Check the final r11 package and ZIP: unchanged files, accepted manifest, install from the extracted ZIP."""
import json
import tempfile
import zipfile
from pathlib import Path
import unittest
import manage_preview as m
from build_final_r11 import build, package_zip

SOURCE = m.ROOT/'artifacts/r11-shadow-n1'


class FinalTests(unittest.TestCase):
    def test_final_package_zip_installs_and_rolls_back(self):
        source, _ = m.read_package(SOURCE)
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='final-test-') as temp:
            root = Path(temp)
            final = build(SOURCE, root/'r11')
            self.assertEqual(final['files'], source['files'])
            self.assertEqual(final['compatibility_candidate']['id'], 'r11')
            self.assertFalse(final['release']['published'])
            self.assertTrue(all(e['execution_verified'] and not e['performance_verified'] for e in final['effects'].values()))
            count, _ = package_zip(root/'r11', root/'smsm-r11.zip')
            with zipfile.ZipFile(root/'smsm-r11.zip') as z:
                z.extractall(root/'unzipped')
                self.assertEqual(len(z.namelist()), count + 1)
            sums = json.loads((root/'unzipped/SHA256SUMS.json').read_text())
            for name, sha in sums.items():
                self.assertEqual(m.digest((root/'unzipped'/name).read_bytes()), sha, name)
            package = root/'unzipped/package'
            manifest, receipt = m.read_package(package)
            self.assertEqual(manifest['default_profile'], 'vanilla')
            game = root/'game'; game.mkdir()
            daily = manifest['profiles']['daily']
            self.assertEqual(daily, ['tone', 'dithering', 'radial', 'dof', 'shadows'])
            installed = m.desired_package(package, manifest, receipt, daily, 'daily')
            m.transition(game, {}, installed, root/'backups')
            self.assertEqual(m.snapshot(game)[0], installed)
            vanilla = m.desired_package(package, manifest, receipt, [], 'vanilla')
            backup = m.transition(game, installed, vanilla, root/'backups')
            self.assertFalse(any(name.endswith('.bin') for name in vanilla))
            m.transition(game, vanilla, m.read_backup(backup, game), root/'backups')
            self.assertEqual(m.snapshot(game)[0], installed)


if __name__ == '__main__':
    unittest.main()
