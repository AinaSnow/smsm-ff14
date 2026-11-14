"""One-step installer in an isolated fake environment: auto-detect, Dalamud setting, install, uninstall, rollback."""
import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock
import manage_preview as m
import easy_install as e

PACKAGE = m.ROOT/'artifacts/r11-final-2026.11.03'


class EasyInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts', prefix='easy-test-')
        root = Path(self.temp.name)
        manifest, _ = m.read_package(PACKAGE)
        self.client = root/'FINAL FANTASY XIV Online'
        (self.client/'game').mkdir(parents=True)
        (self.client/'game/ffxivgame.ver').write_text(manifest['client_build'])
        self.appdata, self.local = root/'Roaming', root/'Local'
        (self.appdata/'XIVLauncher').mkdir(parents=True)
        (self.appdata/'XIVLauncher/launcherConfigV3.json').write_text(json.dumps({'GamePath': str(self.client)}))
        self.dalamud = self.appdata/'XIVLauncher/dalamudConfig.json'
        self.dalamud.write_text(json.dumps({'IsDisableViewport': False, 'Other': 1}))
        self.env = mock.patch.dict(os.environ, {'APPDATA': str(self.appdata), 'LOCALAPPDATA': str(self.local)})
        self.env.start()
        self.steam = mock.patch.object(e, 'steam_libraries', return_value=[])
        self.steam.start()

    def tearDown(self):
        self.steam.stop(); self.env.stop(); self.temp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            e.main([*args, '--package', str(PACKAGE)])
        return out.getvalue()

    def test_full_cycle(self):
        game = self.client/'game'
        self.assertEqual(e.find_client(), self.client.resolve())
        out = self.run_main('install')
        self.assertIn('安装完成', out)
        config = json.loads(self.dalamud.read_text(encoding='utf-8-sig'))
        self.assertIs(config['IsDisableViewport'], True)
        self.assertEqual(config['Other'], 1)
        self.assertEqual(len(list((self.local/'SMSM/dalamud-backups').iterdir())), 1)
        stored = list((self.local/'SMSM/packages').iterdir())
        self.assertEqual(len(stored), 1)
        installed, current, state = m.snapshot(game)
        self.assertEqual(state['effects'], ['dithering', 'dof', 'radial', 'shadows', 'tone'])
        self.assertEqual(Path(state['package_path']).resolve(), stored[0].resolve())
        self.assertIn('版本匹配', self.run_main('status'))
        # Installing again reuses the stored copy and leaves Dalamud alone.
        self.assertIn('无需修改', self.run_main('install'))
        self.assertEqual(len(list((self.local/'SMSM/packages').iterdir())), 1)
        self.assertIn('已卸载', self.run_main('uninstall'))
        self.assertIsNone(m.snapshot(game)[1])
        self.assertIn('已恢复', self.run_main('rollback'))
        self.assertEqual(m.snapshot(game)[0], installed)

    def test_version_mismatch_changes_nothing(self):
        (self.client/'game/ffxivgame.ver').write_text('2099.01.01.0000.0000')
        before = self.dalamud.read_bytes()
        with self.assertRaises(SystemExit) as stop:
            self.run_main('install')
        self.assertIn('版本', str(stop.exception))
        self.assertEqual(self.dalamud.read_bytes(), before)
        self.assertIsNone(m.snapshot(self.client/'game')[1])
        self.assertFalse((self.local/'SMSM/packages').exists())

    def test_no_game_found(self):
        (self.appdata/'XIVLauncher/launcherConfigV3.json').write_text(json.dumps({'GamePath': str(self.client/'missing')}))
        with mock.patch.object(e, 'DEFAULT_SE', self.client/'also-missing'), self.assertRaises(SystemExit):
            e.find_client()


if __name__ == '__main__':
    unittest.main()
