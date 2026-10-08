"""Keep the rendered offline program behind the existing game-interface guard."""
import json
from pathlib import Path
import tempfile
import unittest
from build_preview import verify_interface
from manage_preview import ROOT, digest
from patch_material_light import patch
from shader_compile import Compiler

RESULT = ROOT/'artifacts/material-visibility-fused-v3'


class FusedVisibilityTests(unittest.TestCase):
    def test_exact_rendered_program_rejected_by_game_interface(self):
        report=json.loads((RESULT/'report.json').read_text())
        self.assertTrue(report['all_passed'])
        self.assertTrue(report['single_draw_fused'])
        self.assertFalse(report['game_package_created'])
        compiler=Compiler(ROOT/'d3dcompiler_46.dll')
        original=(RESULT/'original-material.bin').read_bytes()
        for mode in (0,1):
            data=(RESULT/f'fused-{mode}/offline-fused.bin').read_bytes()
            self.assertEqual(digest(data),report['fused_sha256'][str(mode)])
            with self.assertRaisesRegex(ValueError,'reads beyond original range'):
                verify_interface(compiler.disassemble(original),compiler.disassemble(data))

    def test_game_patcher_rejects_synthetic_helper_bindings(self):
        compiler=Compiler(ROOT/'d3dcompiler_46.dll')
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts',prefix='offline-boundary-') as temp:
            with self.assertRaisesRegex(ValueError,'Unbound helper resource'):
                patch((RESULT/'original-material.bin').read_bytes(),
                      (RESULT/'fused-1/helper.bin').read_bytes(),Path(temp),
                      ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe',compiler)


if __name__=='__main__':unittest.main()
