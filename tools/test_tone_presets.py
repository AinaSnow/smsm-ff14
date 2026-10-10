"""Check the T1 package boundaries and exact H3 rollback."""
import tempfile
from pathlib import Path
import unittest
import manage_preview as m
from build_tone_presets import BINARY, SOURCE, MODES, build


class TonePresetPackageTests(unittest.TestCase):
    def test_t1_changes_only_tone_and_ini_and_rolls_back_to_h3(self):
        baseline = m.ROOT/'artifacts/r11-compat-c2'
        h3 = m.ROOT/'artifacts/r11-tone-highlights-h3'
        base, base_receipt = m.read_package(baseline)
        old, old_receipt = m.read_package(h3)
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='presets-test-') as temp:
            root = Path(temp); candidate = root/'candidate'
            build(baseline, candidate)
            manifest, receipt = m.read_package(candidate)
            self.assertEqual({n for n in manifest['files'] if manifest['files'][n] != base['files'][n]},
                             {SOURCE, BINARY, 'd3dx.ini'})
            self.assertEqual({n for n in manifest['files'] if manifest['files'][n] != old['files'][n]},
                             {SOURCE, BINARY, 'd3dx.ini'})
            self.assertEqual(manifest['default_profile'], 'vanilla')
            experiment = manifest['tone_experiment']
            self.assertEqual(experiment['comparison']['states'], MODES)
            self.assertEqual(experiment['comparison']['startup'], 'r10-baseline')
            self.assertEqual(experiment['output_ceiling'], 'none (same as R10)')
            self.assertFalse(experiment['game_verified'])
            self.assertFalse(experiment['visual_improvement_verified'])
            self.assertEqual(manifest['compatibility_candidate']['required_dalamud_settings'],
                             {'IsDisableViewport': True})
            ini = (candidate/'d3dx.ini').read_text()
            self.assertIn('hunting=0', ini)
            self.assertIn('x7 = 0, 1, 2, 3', ini)
            self.assertEqual(ini.count('[Constants]'), 1)
            self.assertNotIn('t1Max', (candidate/SOURCE).read_text())
            game = root/'game'; game.mkdir()
            before = m.desired_package(h3, old, old_receipt, ['tone'], 'daily')
            after = m.desired_package(candidate, manifest, receipt, ['tone'], 'daily')
            m.transition(game, {}, before, root/'backups')
            backup = m.transition(game, before, after, root/'backups')
            self.assertEqual(m.snapshot(game)[0], after)
            m.transition(game, after, m.read_backup(backup, game), root/'backups')
            self.assertEqual(m.snapshot(game)[0], before)
            with self.assertRaises(FileExistsError):
                build(baseline, candidate)
        self.assertEqual(m.read_package(baseline)[1], base_receipt)
        self.assertEqual(m.read_package(h3)[1], old_receipt)


if __name__ == '__main__':
    unittest.main()
