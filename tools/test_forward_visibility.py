"""Offline mesh visibility must not relax game patching or use the wrong layout."""
from pathlib import Path
import tempfile
import unittest
from manage_preview import ROOT
from shader_compile import Compiler
from patch_forward_light import patch_forward
from offline.fuse_material_visibility import fuse

RESULT=ROOT/'artifacts/forward-visibility-validation-v8'


class ForwardVisibilityTests(unittest.TestCase):
    def test_game_patcher_rejects_synthetic_projection(self):
        compiler=Compiler(ROOT/'d3dcompiler_46.dll')
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts',prefix='mesh-visibility-guard-') as temp:
            with self.assertRaisesRegex(ValueError,'Unbound helper resource'):
                patch_forward((RESULT/'native.bin').read_bytes(),(RESULT/'helper-0.5.bin').read_bytes(),Path(temp),
                    ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe',compiler)

    def test_fullscreen_envelope_rejects_mesh_helper(self):
        compiler=Compiler(ROOT/'d3dcompiler_46.dll')
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts',prefix='mesh-visibility-layout-') as temp:
            with self.assertRaisesRegex(ValueError,'Unreviewed synthetic constants'):
                fuse((RESULT/'native.bin').read_bytes(),(RESULT/'helper-0.5.bin').read_bytes(),Path(temp)/'wrong-layout',
                    ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe',compiler)


if __name__=='__main__':unittest.main()
