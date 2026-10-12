"""Check the S1/S2 sharpen package boundaries and exact rollback to T2b."""
import tempfile
from pathlib import Path
import unittest
import manage_preview as m
from build_dither_t2 import FIXES, TONE
from build_sharpen_s1 import build


class SharpenPackageTests(unittest.TestCase):
    def test_changes_only_tone_and_ini_and_rolls_back(self):
        baseline = m.ROOT/'artifacts/r11-dither-t2b'
        old, old_receipt = m.read_package(baseline)
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='sharpen-test-') as temp:
            root = Path(temp); candidate = root/'candidate'
            build(baseline, candidate)
            manifest, receipt = m.read_package(candidate)
            self.assertEqual(set(manifest['files']), set(old['files']))
            self.assertEqual({n for n in old['files'] if manifest['files'][n] != old['files'][n]},
                             {'d3dx.ini'} | {f'{FIXES}/{TONE}-ps_replace.{e}' for e in ('txt', 'bin')})
            self.assertEqual(manifest['profiles'], old['profiles'])
            self.assertEqual(manifest['sharpen_experiment']['comparison']['startup'], 'medium-0.5')
            self.assertFalse(manifest['sharpen_experiment']['visual_improvement_verified'])
            ini = (candidate/'d3dx.ini').read_text()
            self.assertIn('[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\nx6 = 0.5\n', ini)
            self.assertIn('x6 = 0, 0.5, 1\n', ini)
            self.assertEqual(ini.count('[KeySMSMSharpen]'), 1)
            self.assertIn('hunting=0', ini)
            game = root/'game'; game.mkdir()
            before = m.desired_package(baseline, old, old_receipt, ['tone', 'dithering'], 'daily')
            after = m.desired_package(candidate, manifest, receipt, ['tone', 'dithering'], 'daily')
            m.transition(game, {}, before, root/'backups')
            backup = m.transition(game, before, after, root/'backups')
            self.assertEqual(m.snapshot(game)[0], after)
            m.transition(game, after, m.read_backup(backup, game), root/'backups')
            self.assertEqual(m.snapshot(game)[0], before)
            with self.assertRaises(FileExistsError):
                build(baseline, candidate)

    def test_s2_levels_and_ini(self):
        baseline = m.ROOT/'artifacts/r11-dither-t2b'
        old, _ = m.read_package(baseline)
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='sharpen-s2-test-') as temp:
            candidate = Path(temp)/'candidate'
            build(baseline, candidate, variant='s2')
            manifest, _ = m.read_package(candidate)
            self.assertEqual({n for n in old['files'] if manifest['files'][n] != old['files'][n]},
                             {'d3dx.ini'} | {f'{FIXES}/{TONE}-ps_replace.{e}' for e in ('txt', 'bin')})
            self.assertEqual(manifest['sharpen_experiment']['id'], 'sharpen-s2')
            self.assertEqual(manifest['compatibility_candidate']['id'], 'r11-sharpen-s2')
            ini = (candidate/'d3dx.ini').read_text()
            self.assertIn('[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\nx6 = 1\n', ini)
            self.assertIn('x6 = 0, 1, 2\n', ini)
            source = (candidate/f'{FIXES}/{TONE}-ps_replace.txt').read_text()
            self.assertIn('S2 unsharp mask', source)
            self.assertIn('s1Level > 1.5', source)

    def test_s2b_adds_only_highlight_fade(self):
        baseline = m.ROOT/'artifacts/r11-dither-t2b'
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='sharpen-s2b-test-') as temp:
            candidate = Path(temp)/'candidate'
            build(baseline, candidate, variant='s2b')
            manifest, _ = m.read_package(candidate)
            self.assertEqual(manifest['sharpen_experiment']['id'], 'sharpen-s2b')
            self.assertEqual(manifest['sharpen_experiment']['comparison']['startup'], 'medium-2x-k0.2')
            source = (candidate/f'{FIXES}/{TONE}-ps_replace.txt').read_text()
            self.assertIn('s2Amount *= 1 - smoothstep(0.9, 1.05, s2Display);', source)
            s2 = (m.ROOT/'tools/patches/tone_sharpen_s2.hlsl').read_text()
            for line in s2.splitlines():
                if line.strip() and not line.strip().startswith('//'):
                    self.assertIn(line, source)

    def test_s2c_four_levels_default_light(self):
        baseline = m.ROOT/'artifacts/r11-dither-t2b'
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='sharpen-s2c-test-') as temp:
            candidate = Path(temp)/'candidate'
            build(baseline, candidate, variant='s2c')
            manifest, _ = m.read_package(candidate)
            self.assertEqual(manifest['sharpen_experiment']['comparison']['states'],
                             ['off', 'light-1.2x-k0.1', 'medium-2x-k0.2', 'strong-4x-k0.4'])
            self.assertEqual(manifest['sharpen_experiment']['comparison']['startup'], 'light-1.2x-k0.1')
            ini = (candidate/'d3dx.ini').read_text()
            self.assertIn('[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\nx6 = 1\n', ini)
            self.assertIn('x6 = 0, 1, 2, 3\n', ini)
            source = (candidate/f'{FIXES}/{TONE}-ps_replace.txt').read_text()
            self.assertIn('s2Level > 2.5 ? 4.0 : s2Level > 1.5 ? 2.0 : 1.2', source)
            self.assertIn('smoothstep(0.9, 1.05, s2Display)', source)
            s2 = (m.ROOT/'tools/patches/tone_sharpen_s2b.hlsl').read_text()
            s2 = '\n'.join(l for l in s2.splitlines() if 's2Amount = ' not in l and 's2Overshoot = ' not in l)
            for line in s2.splitlines():
                if line.strip() and not line.strip().startswith('//'):
                    self.assertIn(line, source)


if __name__ == '__main__':
    unittest.main()
