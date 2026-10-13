"""Check the N0/N1 package: boundaries, INI controls and exact rollback to D1 strong."""
import tempfile
from pathlib import Path
import unittest
import manage_preview as m
from build_dither_t2 import FIXES, TONE
from build_shadow_n1 import HOSTS, build


class ShadowPackageTests(unittest.TestCase):
    def test_n1_adds_two_sun_light_shaders_and_rolls_back(self):
        baseline = m.ROOT/'artifacts/r11-dof-d1-strong'
        old, old_receipt = m.read_package(baseline)
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='shadow-test-') as temp:
            root = Path(temp); candidate = root/'candidate'
            build(baseline, candidate)
            manifest, receipt = m.read_package(candidate)
            self.assertEqual(set(manifest['files']) - set(old['files']),
                             {f'{FIXES}/{h}-ps.{e}' for h in HOSTS for e in ('txt', 'bin')})
            self.assertEqual({n for n in old['files'] if manifest['files'][n] != old['files'][n]},
                             {'d3dx.ini'} | {f'{FIXES}/{TONE}-ps_replace.{e}' for e in ('txt', 'bin')})
            self.assertEqual(manifest['profiles']['daily'], ['tone', 'dithering', 'radial', 'dof', 'shadows'])
            ini = (candidate/'d3dx.ini').read_text()
            self.assertIn('y6 = 2\nz6 = 0\nx5 = 1\ny5 = 0\n', ini)
            for section in ('[KeySMSMNormalShadow]', '[KeySMSMNormalShadowDiagnostic]', '[Constants]'):
                self.assertEqual(ini.count(section), 1, section)
            for host in HOSTS:
                asm = (candidate/f'{FIXES}/{host}-ps.txt').read_text()
                self.assertEqual(asm.count('// SMSM N1 normal shadow begin'), 1)
                self.assertEqual(asm.count('dcl_resource_texture1d (float,float,float,float) t120'), 1)
            game = root/'game'; game.mkdir()
            effects_old = ['tone', 'dithering', 'radial', 'dof']
            before = m.desired_package(baseline, old, old_receipt, effects_old, 'daily')
            after = m.desired_package(candidate, manifest, receipt, effects_old + ['shadows'], 'daily')
            m.transition(game, {}, before, root/'backups')
            backup = m.transition(game, before, after, root/'backups')
            self.assertEqual(m.snapshot(game)[0], after)
            m.transition(game, after, m.read_backup(backup, game), root/'backups')
            self.assertEqual(m.snapshot(game)[0], before)


if __name__ == '__main__':
    unittest.main()
