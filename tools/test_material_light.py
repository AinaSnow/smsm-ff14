"""Candidate integrity, default-off selection and reversible managed deployment."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import manage_preview as m
from build_material_light import build
from patch_material_light import TARGET

BASE=m.ROOT/'artifacts/preview-2026.09.15-r10-managed'
PACKAGE=m.ROOT/'artifacts/experimental-2026.09.15-material-light-v1'
VALIDATION=m.ROOT/'artifacts/material-light-validation-v4/report.json'


class MaterialLightTests(unittest.TestCase):
    def test_default_off_and_matches_rendered_binary(self):
        base,_=m.read_package(BASE); manifest,_=m.read_package(PACKAGE)
        self.assertEqual(manifest['profiles'][manifest['default_profile']],['tone'])
        self.assertFalse(manifest['material_light']['game_runtime_verified'])
        self.assertNotIn('single-light',manifest['effects'])
        self.assertEqual(manifest['effects']['material-light']['shaders'],[TARGET])
        self.assertTrue(all(manifest['files'][name]==sha for name,sha in base['files'].items()))
        self.assertEqual(set(manifest['files'])-set(base['files']),{f'SMSM-ShaderFixes/{TARGET}-ps.{ext}' for ext in ('txt','bin')})
        report=json.loads(VALIDATION.read_text())
        self.assertTrue(report['all_passed'])
        self.assertEqual(report['patched_sha256'],manifest['files'][f'SMSM-ShaderFixes/{TARGET}-ps.bin'])

    def test_reject_stacked_lamp_package_and_mutating_existing_package(self):
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts',prefix='material-guard-') as temp:
            path=Path(temp)/'not-created'
            with self.assertRaisesRegex(ValueError,'audited r10'):
                build(m.ROOT/'artifacts/client-2026.09.15',m.ROOT/'artifacts/experimental-2026.09.15-single-light-v1',path,Path('unused'))
            self.assertFalse(path.exists())
        with self.assertRaises(FileExistsError):
            build(m.ROOT/'artifacts/client-2026.09.15',BASE,PACKAGE,Path('unused'))

    def test_managed_live_selection_and_exact_restore(self):
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts',prefix='material-manager-') as temp:
            root=Path(temp); game=root/'client/game'; game.mkdir(parents=True)
            manifest,receipt=m.read_package(BASE); (game/'ffxivgame.ver').write_text(manifest['client_build'])
            before=m.desired_package(BASE,manifest,receipt,['tone'],'daily')
            m.transition(game,{},before,root/'backups')
            def cli(*args):
                with patch.object(sys,'argv',['manage_preview.py',*args,'--client-root',str(game.parent),'--backup-root',str(root/'backups')]), \
                     patch.object(m,'running_game',return_value=True),patch('builtins.print'):
                    m.main()
            cli('select','--package',str(PACKAGE),'--profile','daily','--live')
            self.assertEqual(m.snapshot(game)[2]['effects'],['tone'])
            self.assertFalse((game/f'SMSM-ShaderFixes/{TARGET}-ps.bin').exists())
            cli('select','--profile','material-light-only','--live')
            self.assertEqual(m.snapshot(game)[2]['effects'],['material-light'])
            self.assertTrue((game/f'SMSM-ShaderFixes/{TARGET}-ps.bin').exists())
            cli('select','--disable','material-light','--live')
            self.assertEqual(m.snapshot(game)[2]['effects'],[])
            self.assertFalse((game/f'SMSM-ShaderFixes/{TARGET}-ps.bin').exists())
            cli('select','--package',str(BASE),'--profile','daily','--live')
            self.assertEqual(m.snapshot(game)[0],before)
            self.assertEqual(len(list((root/'backups').glob('*/snapshot.json'))),5)


if __name__=='__main__': unittest.main()
