"""Check the T2 dither package boundaries, effect selection and exact rollback to tone A."""
import tempfile
from pathlib import Path
import unittest
import manage_preview as m
from build_dither_t2 import FIXES, OUTPUT, VIGNETTE, build


class DitherPackageTests(unittest.TestCase):
    def test_adds_only_dither_shaders_and_ini_and_rolls_back(self):
        baseline = m.ROOT/'artifacts/r11-tone-a-default'
        old, old_receipt = m.read_package(baseline)
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='dither-test-') as temp:
            root = Path(temp); candidate = root/'candidate'
            build(baseline, candidate)
            manifest, receipt = m.read_package(candidate)
            added = set(manifest['files']) - set(old['files'])
            self.assertEqual(added, {f'{FIXES}/{h}-ps_replace.{e}' for h in (OUTPUT, VIGNETTE) for e in ('txt', 'bin')})
            self.assertEqual({n for n in old['files'] if manifest['files'][n] != old['files'][n]}, {'d3dx.ini'})
            self.assertEqual(manifest['profiles'], {'vanilla': [], 'daily': ['tone', 'dithering']})
            self.assertEqual(manifest['default_profile'], 'vanilla')
            self.assertFalse(manifest['dither_experiment']['visual_improvement_verified'])
            ini = (candidate/'d3dx.ini').read_text()
            self.assertIn('[Constants]\nx7 = 1\ny7 = 0\nz7 = 1\nx = 0\n', ini)
            for section in ('[Present]', '[KeySMSMDither]', '[ShaderOverrideSMSMOutputArm]',
                            '[ShaderOverrideSMSMOutputConsume]', '[Constants]'):
                self.assertEqual(ini.count(section), 1, section)
            self.assertIn('hunting=0', ini)
            # Tone only selection must leave the dither shaders out.
            self.assertNotIn(f'{FIXES}/{OUTPUT}-ps_replace.bin', m.selected_files(manifest, ['tone']))
            game = root/'game'; game.mkdir()
            before = m.desired_package(baseline, old, old_receipt, ['tone'], 'daily')
            after = m.desired_package(candidate, manifest, receipt, ['tone', 'dithering'], 'daily')
            m.transition(game, {}, before, root/'backups')
            backup = m.transition(game, before, after, root/'backups')
            self.assertEqual(m.snapshot(game)[0], after)
            m.transition(game, after, m.read_backup(backup, game), root/'backups')
            self.assertEqual(m.snapshot(game)[0], before)
            with self.assertRaises(FileExistsError):
                build(baseline, candidate)
        self.assertEqual(m.read_package(baseline)[1], old_receipt)


if __name__ == '__main__':
    unittest.main()
