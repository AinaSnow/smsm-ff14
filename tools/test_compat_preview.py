"""Exercise candidate integrity, zero/tone rollback, and scoped configuration changes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import manage_preview as m
import build_compat_preview as b
import configure_compat_viewports as c


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='compat-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = m.ROOT/'artifacts/preview-2026.09.15-r10-managed'
        self.archive = m.ROOT/'artifacts/runtime/3Dmigoto-1.3.16.zip'

    def test_candidate_zero_tone_and_exact_rollback(self):
        package = self.root/'package'
        b.build(self.base, self.archive, package)
        manifest, receipt = m.read_package(package)
        self.assertEqual(manifest['profiles'][manifest['default_profile']], [])
        self.assertEqual(list(manifest['effects']), ['tone'])
        self.assertIn('hunting=0', (package/'d3dx.ini').read_text())
        self.assertEqual((package/'SMSM-ShaderFixes/72a656dfd52149ad-ps_replace.bin').read_bytes(),
                         (self.base/'SMSM-ShaderFixes/72a656dfd52149ad-ps_replace.bin').read_bytes())
        game = self.root/'game'; game.mkdir()
        (game/'ffxivgame.ver').write_text(manifest['client_build'])
        zero = m.desired_package(package, manifest, receipt, [], 'vanilla')
        self.assertEqual(json.loads(zero[m.STATE])['application'], 'pending-restart')
        self.assertFalse(any(n.endswith('.bin') for n in zero))
        m.transition(game, {}, zero, self.root/'backups')
        tone = m.desired_package(package, manifest, receipt, ['tone'], 'daily')
        backup = m.transition(game, zero, tone, self.root/'backups')
        restored = m.read_backup(backup, game)
        m.transition(game, tone, restored, self.root/'backups')
        self.assertEqual(m.snapshot(game)[0], zero)
        with patch.object(m, 'running_game', return_value=True), patch('sys.argv',
                ['manage_preview.py', 'select', '--client-root', str(self.root), '--profile', 'daily', '--live']):
            with self.assertRaisesRegex(ValueError, 'stopped-client selection'):
                m.main()
        self.assertEqual(m.snapshot(game)[0], zero)
        with self.assertRaises(FileExistsError):
            b.build(self.base, self.archive, package)

    def test_untrusted_runtime_rejected_before_output(self):
        archive = self.root/'bad.zip'; archive.write_bytes(b'wrong runtime')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            b.build(self.base, archive, self.root/'package')
        self.assertFalse((self.root/'package').exists())

    def test_config_preserves_stagehand_and_other_plugins(self):
        original = {'IsDisableViewport': False, 'PluginSafeMode': False, 'unrelated': 5,
            'DevPluginLoadLocations': {'$values': [
                {'Path': r'C:\test\Stagehand.dll', 'IsEnabled': True},
                {'Path': r'C:\test\SMSM.StagehandBridge.dll', 'IsEnabled': True}]},
            'DevPluginSettings': {r'C:\test\Stagehand.dll': {'StartOnBoot': True},
                r'C:\test\SMSM.StagehandBridge.dll': {'StartOnBoot': True}}}
        result = c.adjusted(original)
        expected = copy.deepcopy(original)
        expected['IsDisableViewport'] = True
        expected['DevPluginLoadLocations']['$values'][1]['IsEnabled'] = False
        expected['DevPluginSettings'][r'C:\test\SMSM.StagehandBridge.dll']['StartOnBoot'] = False
        self.assertEqual(result, expected)
        self.assertFalse(original['IsDisableViewport'])
        config = self.root/'config.json'; config.write_bytes(m.encoded(original))
        before = config.read_bytes()
        with patch.object(c, 'running_game', return_value=False):
            c.configure(config, self.root/'backup', self.root/'game')
            self.assertEqual(json.loads(config.read_bytes()), expected)
            c.configure(config, self.root/'backup', self.root/'game', restore=True)
        self.assertEqual(config.read_bytes(), before)

    def test_running_game_and_changed_config_block(self):
        config = self.root/'config.json'; config.write_text('{"IsDisableViewport":false}')
        before = config.read_bytes()
        with patch.object(c, 'running_game', return_value=True), self.assertRaises(ValueError):
            c.configure(config, self.root/'backup', self.root/'game')
        self.assertEqual(config.read_bytes(), before)
        with patch.object(c, 'running_game', return_value=False):
            c.configure(config, self.root/'backup', self.root/'game')
            config.write_text('{"IsDisableViewport":true,"new_user_setting":1}')
            with self.assertRaisesRegex(ValueError, 'changed since'):
                c.configure(config, self.root/'backup', self.root/'game', restore=True)
        self.assertEqual(json.loads(config.read_bytes())['new_user_setting'], 1)


if __name__ == '__main__':
    unittest.main()
