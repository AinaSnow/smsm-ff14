"""Package/default-off/control guards; actual pixels are tested by validate_single_light.py."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import manage_preview as m
from build_single_light import TARGETS, validate_settings
from build_preview import verify_interface, bindings
from shader_compile import Compiler

BASE=m.ROOT/"artifacts/preview-2026.09.15-r10-managed"
PACKAGE=m.ROOT/"artifacts/experimental-2026.09.15-single-light-v1"


class LightTests(unittest.TestCase):
    def test_default_off_and_no_conflicting_shadow_group(self):
        manifest,_=m.read_package(PACKAGE)
        self.assertEqual(manifest["profiles"][manifest["default_profile"]],["tone"])
        self.assertNotIn("shadows",manifest["effects"])
        self.assertEqual(set(manifest["effects"]["single-light"]["shaders"]),set(TARGETS))
        self.assertFalse(manifest["single_light"]["game_runtime_verified"])

    def test_only_light_pairs_change_and_no_unbound_resource(self):
        base,_=m.read_package(BASE); manifest,_=m.read_package(PACKAGE)
        self.assertEqual(base["files"].keys(),manifest["files"].keys())
        changed={n for n in base["files"] if base["files"][n]!=manifest["files"][n]}
        self.assertEqual(changed,{f"SMSM-ShaderFixes/{h}-ps.{ext}" for h in TARGETS for ext in ("txt","bin")})
        compiler=Compiler(m.ROOT/"d3dcompiler_46.dll")
        for target in TARGETS:
            original=compiler.disassemble((PACKAGE/"build-audit"/target/"original.bin").read_bytes())
            modified=compiler.disassemble((PACKAGE/"SMSM-ShaderFixes"/f"{target}-ps.bin").read_bytes())
            verify_interface(original,modified)
            self.assertNotIn(("cbuffer",13),bindings(modified))
            self.assertNotIn(("texture",120),bindings(modified))

    def test_parameter_validation(self):
        for position,color,intensity,radius in (([float("nan"),0,0],[1,1,1],1,8),([0,0,0],[-1,1,1],1,8),
                                               ([0,0,0],[1,1,1],float("inf"),8),([0,0,0],[1,1,1],1,0)):
            with self.assertRaises(ValueError): validate_settings(position,color,intensity,radius)
        validate_settings([0,0,0],[1,1,1],0,8)

    def test_managed_selection_backup_and_exact_restore(self):
        with tempfile.TemporaryDirectory(dir=m.ROOT/"artifacts",prefix="light-manager-test-") as temp:
            root=Path(temp); game=root/"client/game"; game.mkdir(parents=True)
            manifest,receipt=m.read_package(BASE); (game/"ffxivgame.ver").write_text(manifest["client_build"])
            before=m.desired_package(BASE,manifest,receipt,["tone"],"daily")
            m.transition(game,{},before,root/"backups")
            def cli(*args):
                with patch.object(sys,"argv",["manage_preview.py",*args,"--client-root",str(game.parent),"--backup-root",str(root/"backups")]), patch.object(m,"running_game",return_value=True), patch("builtins.print"):
                    m.main()
            cli("select","--package",str(PACKAGE),"--profile","daily","--live")
            self.assertEqual(m.snapshot(game)[2]["effects"],["tone"])
            cli("select","--enable","single-light","--live")
            self.assertEqual(m.snapshot(game)[2]["effects"],["single-light","tone"])
            cli("select","--disable","single-light","--live")
            self.assertEqual(m.snapshot(game)[2]["effects"],["tone"])
            cli("select","--package",str(BASE),"--profile","daily","--live")
            self.assertEqual(m.snapshot(game)[0],before)
            snapshots=list((root/"backups").glob("*/snapshot.json"))
            self.assertEqual(len(snapshots),5)
            self.assertTrue(all(json.loads(p.read_text())["game"]==str(game.resolve()) for p in snapshots))


if __name__=="__main__": unittest.main()
