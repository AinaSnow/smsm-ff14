"""Check the experimental package boundaries and exact baseline restoration."""
import tempfile
from pathlib import Path
import unittest
import manage_preview as m
from build_tone_highlights import BINARY, SOURCE, build


class HighlightPackageTests(unittest.TestCase):
    def test_shader_only_experiment_and_baseline_restore(self):
        baseline = m.ROOT/'artifacts/r11-compat-c2'
        before_manifest, before_receipt = m.read_package(baseline)
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='highlights-test-') as temp:
            root = Path(temp); candidate = root/'candidate'
            build(baseline, candidate)
            manifest, receipt = m.read_package(candidate)
            changed = {n for n in manifest['files'] if manifest['files'][n] != before_manifest['files'][n]}
            self.assertEqual(changed, {SOURCE, BINARY})
            self.assertEqual(manifest['default_profile'], 'vanilla')
            self.assertFalse(manifest['tone_experiment']['game_verified'])
            self.assertFalse(manifest['tone_experiment']['visual_improvement_verified'])
            self.assertEqual(manifest['compatibility_candidate']['required_dalamud_settings'],
                             {'IsDisableViewport': True})
            game = root/'game'; game.mkdir()
            before = m.desired_package(baseline, before_manifest, before_receipt, ['tone'], 'daily')
            m.transition(game, {}, before, root/'backups')
            after = m.desired_package(candidate, manifest, receipt, ['tone'], 'daily')
            saved = m.transition(game, before, after, root/'backups')
            self.assertEqual(m.snapshot(game)[0], after)
            m.transition(game, after, m.read_backup(saved, game), root/'backups')
            self.assertEqual(m.snapshot(game)[0], before)
            with self.assertRaises(FileExistsError):
                build(baseline, candidate)
        self.assertEqual(m.read_package(baseline)[1], before_receipt)


if __name__ == '__main__':
    unittest.main()
