"""Check the T2d radial package (on S2c): boundaries, effect selection and exact rollback."""
import tempfile
from pathlib import Path
import unittest
import manage_preview as m
from build_dither_t2 import FIXES, TONE
from build_radial_t2c import RADIAL, build


class RadialPackageTests(unittest.TestCase):
    def test_t2d_adds_radial_on_s2c_and_rolls_back(self):
        baseline = m.ROOT/'artifacts/r11-sharpen-s2c'
        old, old_receipt = m.read_package(baseline)
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='radial-test-') as temp:
            root = Path(temp); candidate = root/'candidate'
            build(baseline, candidate)
            manifest, receipt = m.read_package(candidate)
            self.assertEqual(set(manifest['files']) - set(old['files']),
                             {f'{FIXES}/{RADIAL}-ps_replace.{e}' for e in ('txt', 'bin')})
            self.assertEqual({n for n in old['files'] if manifest['files'][n] != old['files'][n]},
                             {'d3dx.ini'} | {f'{FIXES}/{TONE}-ps_replace.{e}' for e in ('txt', 'bin')})
            self.assertEqual(manifest['profiles']['daily'], ['tone', 'dithering', 'radial'])
            self.assertEqual(manifest['compatibility_candidate']['id'], 'r11-radial-t2d')
            self.assertEqual(manifest['sharpen_experiment']['status'], 'accepted-default-light')
            ini = (candidate/'d3dx.ini').read_text()
            self.assertIn('[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\nw7 = 1\nx6 = 1\n', ini)
            self.assertEqual(ini.count('[KeySMSMRadial]'), 1)
            self.assertEqual(ini.count('[KeySMSMSharpen]'), 1)
            self.assertNotIn(f'{FIXES}/{RADIAL}-ps_replace.bin', m.selected_files(manifest, ['tone', 'dithering']))
            game = root/'game'; game.mkdir()
            before = m.desired_package(baseline, old, old_receipt, ['tone', 'dithering'], 'daily')
            after = m.desired_package(candidate, manifest, receipt, ['tone', 'dithering', 'radial'], 'daily')
            m.transition(game, {}, before, root/'backups')
            backup = m.transition(game, before, after, root/'backups')
            self.assertEqual(m.snapshot(game)[0], after)
            m.transition(game, after, m.read_backup(backup, game), root/'backups')
            self.assertEqual(m.snapshot(game)[0], before)


if __name__ == '__main__':
    unittest.main()
