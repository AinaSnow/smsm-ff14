"""Historical state audit and isolated two-path package deployment checks."""
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import manage_preview as m
from audit_forward_material import draws
from patch_forward_light import TARGET
from build_preview import verify_interface
from shader_compile import Compiler

BASE=m.ROOT/'artifacts/preview-2026.09.15-r10-managed'
PREVIOUS=m.ROOT/'artifacts/experimental-2026.09.15-material-light-v1'
PACKAGE=m.ROOT/'artifacts/experimental-2026.09.15-material-light-v2'


class ForwardTests(unittest.TestCase):
    def test_historical_binding_persistence_and_invalidations(self):
        raw=('000001 VSSetShader(x) hash=d241dd6ca4f03df3\n'
             f'000001 PSSetShader(x) hash={TARGET}\n'
             '000001 DrawIndexed(x)\n000002 DrawIndexed(x)\n'
             '000003 ClearState()\n000003 DrawIndexed(x)\n'
             f'000004 PSSetShader(x) hash={TARGET}\n000004 DrawIndexed(x)\n'
             '000005 VSSetShader(x) hash=972493e7d05b8002\n000005 DrawIndexed(x)\n'
             '000006 ExecuteCommandList(x)\n000006 DrawIndexed(x)\n').encode()
        rows=draws(raw)
        self.assertEqual([r['draw'] for r in rows],[1,2,4,5])
        self.assertEqual(rows[1]['state']['VSSetShader'],'d241dd6ca4f03df3')
        self.assertNotIn('VSSetShader',rows[2]['state'])
        self.assertEqual(rows[3]['state']['VSSetShader'],'972493e7d05b8002')

    def test_exact_rendered_candidate_and_default_off(self):
        previous,_=m.read_package(PREVIOUS);manifest,_=m.read_package(PACKAGE)
        self.assertEqual(manifest['profiles'][manifest['default_profile']],['tone'])
        self.assertEqual(manifest['effects']['mesh-light']['shaders'],[TARGET])
        self.assertFalse(manifest['material_light']['game_runtime_verified'])
        self.assertFalse(manifest['material_light']['two_path_pixel_overlap_verified'])
        # Flugan writes the assembly-generation wall-clock time into a comment.
        # Require identical bytes for every other file, and identical assembly
        # except that exact comment for the rebuilt full-screen path.
        assembly='SMSM-ShaderFixes/415a922293923fa4-ps.txt'
        self.assertTrue(all(manifest['files'][p]==sha for p,sha in previous['files'].items() if p!=assembly))
        normalize=lambda text:re.sub(r'^//   using 3Dmigoto v1\.3\.16 on .+$','// audit timestamp',text,flags=re.M)
        self.assertEqual(normalize((PACKAGE/assembly).read_text()),normalize((PREVIOUS/assembly).read_text()))
        self.assertEqual(set(manifest['files'])-set(previous['files']),{f'SMSM-ShaderFixes/{TARGET}-ps.{ext}' for ext in ('txt','bin')})
        report=json.loads((m.ROOT/'artifacts/forward-light-validation-v5/report.json').read_text())
        self.assertTrue(report['all_passed'])
        self.assertEqual(report['patched_sha256'],manifest['files'][f'SMSM-ShaderFixes/{TARGET}-ps.bin'])
        first=json.loads((m.ROOT/'artifacts/material-light-validation-v5/report.json').read_text())
        self.assertEqual(first['patched_sha256'],manifest['files']['SMSM-ShaderFixes/415a922293923fa4-ps.bin'])
        compiler=Compiler(m.ROOT/'d3dcompiler_46.dll')
        original=compiler.disassemble((PACKAGE/'build-audit'/TARGET/'original.bin').read_bytes())
        modified=compiler.disassemble((PACKAGE/f'SMSM-ShaderFixes/{TARGET}-ps.bin').read_bytes())
        verify_interface(original,modified)
        self.assertIn('forceEarlyDepthStencil',modified)
        self.assertEqual(original.count('discard_nz'),modified.count('discard_nz'))
        self.assertNotIn('cb13[',modified)

    def test_independent_selection_and_exact_restore(self):
        with tempfile.TemporaryDirectory(dir=m.ROOT/'artifacts',prefix='mesh-manager-') as temp:
            root=Path(temp);game=root/'client/game';game.mkdir(parents=True)
            manifest,receipt=m.read_package(BASE);(game/'ffxivgame.ver').write_text(manifest['client_build'])
            before=m.desired_package(BASE,manifest,receipt,['tone'],'daily');m.transition(game,{},before,root/'backups')
            def cli(*args):
                with patch.object(sys,'argv',['manage_preview.py',*args,'--client-root',str(game.parent),'--backup-root',str(root/'backups')]), \
                     patch.object(m,'running_game',return_value=True),patch('builtins.print'):
                    m.main()
            cli('select','--package',str(PACKAGE),'--profile','mesh-light-only','--live')
            self.assertEqual(m.snapshot(game)[2]['effects'],['mesh-light'])
            self.assertFalse((game/'SMSM-ShaderFixes/415a922293923fa4-ps.bin').exists())
            cli('select','--profile','material-light-both','--live')
            self.assertEqual(m.snapshot(game)[2]['effects'],['material-light','mesh-light'])
            cli('select','--disable','mesh-light','--live')
            self.assertEqual(m.snapshot(game)[2]['effects'],['material-light'])
            self.assertFalse((game/f'SMSM-ShaderFixes/{TARGET}-ps.bin').exists())
            cli('select','--package',str(BASE),'--profile','daily','--live')
            self.assertEqual(m.snapshot(game)[0],before)
            self.assertEqual(len(list((root/'backups').glob('*/snapshot.json'))),5)


if __name__=='__main__':unittest.main()
