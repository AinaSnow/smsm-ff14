"""Check the D0/D1 package: boundaries, INI controls and exact rollback to T2d."""
import tempfile
from pathlib import Path
import unittest
import manage_preview as m
from build_dither_t2 import FIXES, TONE
from build_dof_d1 import BLUR, build


class DofPackageTests(unittest.TestCase):
    def test_d1_adds_blur_pass_and_rolls_back(self):
        baseline = m.ROOT/'artifacts/r11-radial-t2d-2026.10.06'
        old, old_receipt = m.read_package(baseline)
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='dof-test-') as temp:
            root = Path(temp); candidate = root/'candidate'
            build(baseline, candidate)
            manifest, receipt = m.read_package(candidate)
            self.assertEqual(manifest['client_build'], '2026.10.06.0000.0000')
            self.assertEqual(set(manifest['files']) - set(old['files']),
                             {f'{FIXES}/{BLUR}-ps_replace.{e}' for e in ('txt', 'bin')})
            self.assertEqual({n for n in old['files'] if manifest['files'][n] != old['files'][n]},
                             {'d3dx.ini'} | {f'{FIXES}/{TONE}-ps_replace.{e}' for e in ('txt', 'bin')})
            self.assertEqual(manifest['profiles']['daily'], ['tone', 'dithering', 'radial', 'dof'])
            ini = (candidate/'d3dx.ini').read_text()
            self.assertIn('x6 = 1\ny6 = 1\nz6 = 0\n', ini)
            self.assertIn('y6 = 0, 1, 2\n', ini)
            self.assertIn('z6 = 1, 0\n', ini)
            for section in ('[KeySMSMBokeh]', '[KeySMSMBokehDiagnostic]', '[Constants]'):
                self.assertEqual(ini.count(section), 1, section)
            game = root/'game'; game.mkdir()
            before = m.desired_package(baseline, old, old_receipt, ['tone', 'dithering', 'radial'], 'daily')
            after = m.desired_package(candidate, manifest, receipt, ['tone', 'dithering', 'radial', 'dof'], 'daily')
            m.transition(game, {}, before, root/'backups')
            backup = m.transition(game, before, after, root/'backups')
            self.assertEqual(m.snapshot(game)[0], after)
            m.transition(game, after, m.read_backup(backup, game), root/'backups')
            self.assertEqual(m.snapshot(game)[0], before)


if __name__ == '__main__':
    unittest.main()
