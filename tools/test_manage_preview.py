"""Exercise real package transactions on disposable clients, never the installed game."""
import json
from pathlib import Path
import tempfile
import sys
import os
import subprocess
import shutil
import unittest
from unittest.mock import patch
import manage_preview as m

PACKAGE = m.ROOT / "artifacts/preview-2026.09.15-r10-managed"
LEGACY = m.ROOT / "artifacts/preview-2026.09.15-r9-native-dof"
PROBE = m.ROOT / "artifacts/diagnostic-2026.09.15-reflection-marker"


class ManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.receipt = m.read_package(PACKAGE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=m.ROOT / "artifacts", prefix="manager-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "client/game"
        self.game.mkdir(parents=True)
        (self.game / "ffxivgame.ver").write_text(self.manifest["client_build"])
        (self.game / "keep-me.txt").write_text("unmanaged client file")
        self.backups = self.root / "backups"

    def desired(self, profile="daily", effects=None, isolate=None):
        chosen, label = m.selection(self.manifest, None if effects is not None or isolate else profile, effects, isolate)
        return m.desired_package(PACKAGE, self.manifest, self.receipt, chosen, label)

    def install(self):
        desired = self.desired()
        m.transition(self.game, {}, desired, self.backups)
        return desired

    def test_install_select_isolate_uninstall(self):
        self.install()
        before, _, state = m.snapshot(self.game)
        self.assertEqual(state["effects"], ["tone"])
        for group in self.manifest["effects"]:
            after = self.desired(isolate=group)
            m.transition(self.game, before, after, self.backups)
            before, _, state = m.snapshot(self.game)
            self.assertEqual(state["effects"], [group])
            shader_hashes = {Path(n).name[:16] for n in state["files"] if n.endswith(".bin") and n.startswith(m.FIXES)}
            self.assertEqual(shader_hashes, set(self.manifest["effects"][group]["shaders"]))
        m.transition(self.game, before, self.desired("vanilla"), self.backups)
        before, _, state = m.snapshot(self.game)
        self.assertEqual(state["effects"], [])
        m.transition(self.game, before, {}, self.backups)
        self.assertIsNone(m.snapshot(self.game)[1])
        self.assertEqual((self.game / "keep-me.txt").read_text(), "unmanaged client file")

    def test_upgrade_legacy_and_rollback_exactly(self):
        old, receipt = m.read_package(LEGACY)
        legacy = {n: (LEGACY / n).read_bytes() for n in old["files"]}
        legacy[m.RECEIPT] = receipt
        m.transition(self.game, {}, legacy, self.backups)
        before, _, _ = m.snapshot(self.game)
        backup = m.transition(self.game, before, self.desired(), self.backups)
        self.assertEqual(m.read_backup(backup, self.game), legacy)
        current, _, _ = m.snapshot(self.game)
        m.transition(self.game, current, m.read_backup(backup, self.game), self.backups)
        self.assertEqual(m.snapshot(self.game)[0], legacy)

    def test_modified_files_block_without_changes(self):
        self.install()
        path = self.game / "d3dx.ini"
        path.write_bytes(path.read_bytes() + b"; user edit")
        with self.assertRaisesRegex(ValueError, "Installed file changed"):
            m.snapshot(self.game)
        self.assertTrue(path.read_bytes().endswith(b"; user edit"))

    def test_collision_and_unmanaged_shader_block(self):
        (self.game / "d3d11.dll").write_bytes(b"another injector")
        with self.assertRaisesRegex(ValueError, "Existing file"):
            m.transition(self.game, {}, self.desired(), self.backups)
        self.assertEqual((self.game / "d3d11.dll").read_bytes(), b"another injector")
        (self.game / "d3d11.dll").unlink()
        self.install()
        (self.game / m.FIXES / "custom.txt").write_text("keep")
        with self.assertRaisesRegex(ValueError, "Unmanaged item"):
            m.transition(self.game, m.snapshot(self.game)[0], {}, self.backups)

    def test_bad_paths_and_ownership(self):
        for name in ("../oops", "E:/oops", "SMSM-ShaderFixes/../../oops", "game/ffxiv_dx11.exe",
                     "ffxiv_dx11.exe", "SMSM-ShaderFixes//Common.h", "SMSM-ShaderFixes/../Common.h"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                m.safe_path(self.game, name)

    def test_wrong_client_and_package_integrity(self):
        (self.game / "ffxivgame.ver").write_text("new-build")
        with self.assertRaisesRegex(ValueError, "Client build mismatch"):
            m.check_build(self.game, self.manifest)
        altered = dict(self.manifest, files=dict(self.manifest["files"]))
        altered["files"]["ffxiv_dx11.exe"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Not a managed mod file"):
            m.validate_manifest(altered)
        with self.assertRaises(ValueError):
            m.selection(self.manifest, effects="tone,unknown")
        with self.assertRaises(ValueError):
            m.selection(self.manifest, effects="tone,tone")

    def test_mid_write_failure_rolls_back(self):
        self.install()
        before = m.snapshot(self.game)[0]
        original = m.write_atomic
        failed = False

        def failing(path, value):
            nonlocal failed
            if path.is_relative_to(self.game) and path.name.startswith("8b384") and not failed:
                failed = True
                raise OSError("simulated locked file")
            original(path, value)

        with patch.object(m, "write_atomic", side_effect=failing), self.assertRaisesRegex(OSError, "simulated"):
            m.transition(self.game, before, self.desired("r9-baseline"), self.backups)
        self.assertEqual(m.snapshot(self.game)[0], before)
        self.assertFalse((self.game / m.JOURNAL).exists())

    def test_interrupted_transaction_recovery_and_user_edit_guard(self):
        self.install()
        before = m.snapshot(self.game)[0]
        after = self.desired("r9-baseline")
        original = m.write_atomic

        def failing(path, value):
            if path.is_relative_to(self.game) and path.name.startswith("8b384"):
                raise OSError("simulated interruption")
            original(path, value)

        with patch.object(m, "write_atomic", side_effect=failing), patch.object(m, "recover", side_effect=OSError("recovery unavailable")):
            with self.assertRaisesRegex(OSError, "recovery unavailable"):
                m.transition(self.game, before, after, self.backups)
        self.assertTrue((self.game / m.JOURNAL).exists())
        (self.game / "d3dx.ini").write_bytes(b"manual edit after interruption")
        with self.assertRaisesRegex(ValueError, "Changed during transaction"):
            m.recover(self.game)
        (self.game / "d3dx.ini").write_bytes(before["d3dx.ini"])
        m.recover(self.game)
        self.assertEqual(m.snapshot(self.game)[0], before)

    def test_backup_client_mismatch(self):
        self.install()
        backup = m.transition(self.game, m.snapshot(self.game)[0], {}, self.backups)
        with self.assertRaisesRegex(ValueError, "different client"):
            m.read_backup(backup, self.root / "other-game")

    def test_rollback_rejects_corrupt_backup(self):
        self.install()
        backup = m.transition(self.game, m.snapshot(self.game)[0], {}, self.backups)
        (backup / "files/d3dx.ini").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Backup integrity failure"):
            m.read_backup(backup, self.game)

    def run_cli(self, *arguments, running=False):
        argv = ["manage_preview.py", *arguments, "--client-root", str(self.game.parent),
                "--backup-root", str(self.backups)]
        with patch.object(sys, "argv", argv), patch.object(m, "running_game", return_value=running), patch("builtins.print"):
            m.main()

    def test_live_switch_preserves_runtime_and_other_effects(self):
        self.install()
        originals = {n: (self.game / n).read_bytes() for n in m.FIXED}
        self.run_cli("select", "--enable", "reflection", "--live", running=True)
        self.assertEqual(m.snapshot(self.game)[2]["effects"], ["reflection", "tone"])
        self.run_cli("select", "--disable", "reflection", "--live", running=True)
        self.assertEqual(m.snapshot(self.game)[2]["effects"], ["tone"])
        for n, value in originals.items():
            self.assertEqual((self.game / n).read_bytes(), value)
        self.assertEqual(m.snapshot(self.game)[2]["application"], "pending-restart-or-F10")

    def copy_package(self, name, source=PROBE):
        destination = self.root / name
        manifest, receipt = m.read_package(source)
        for item in manifest["files"]:
            target = destination / item
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / item, target)
        (destination / m.RECEIPT).write_bytes(receipt)
        return destination, manifest

    def test_live_probe_switch_and_exact_daily_restore(self):
        before = self.install()
        unchanged = {n: value for n, value in before.items()
                     if n in m.FIXED or n.endswith(".h")}
        self.run_cli("select", "--package", str(PROBE), "--isolate", "reflection", "--live", running=True)
        probe_files, manifest, state = m.snapshot(self.game)
        self.assertEqual(state["effects"], ["reflection"])
        self.assertEqual(state["package_path"], str(PROBE.resolve()))
        self.assertEqual(manifest["diagnostic"]["kind"], "reflection-execution-marker")
        for n, value in unchanged.items():
            self.assertEqual(probe_files[n], value)
        # Same-package selection and returning to the baseline both remain possible.
        self.run_cli("select", "--profile", "vanilla", "--live", running=True)
        self.assertEqual(m.snapshot(self.game)[2]["effects"], [])
        self.run_cli("select", "--package", str(PACKAGE), "--profile", "daily", "--live", running=True)
        self.assertEqual(m.snapshot(self.game)[0], before)

    def test_probe_rejects_mixed_effects(self):
        before = self.install()
        with self.assertRaisesRegex(ValueError, "must be isolated"):
            self.run_cli("select", "--package", str(PROBE), "--effects", "tone,reflection", "--live", running=True)
        self.assertEqual(m.snapshot(self.game)[0], before)

    def test_package_selection_rejects_changed_runtime_or_headers(self):
        before = self.install()
        for index, name in enumerate(("d3dx.ini", "d3d11.dll", "SMSM-ShaderFixes/Configuration.h")):
            package, manifest = self.copy_package(f"altered-{index}")
            (package / name).write_bytes((package / name).read_bytes() + b"changed")
            manifest["files"][name] = m.digest((package / name).read_bytes())
            (package / m.RECEIPT).write_bytes(m.encoded(manifest))
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "runtime/configuration"):
                self.run_cli("select", "--package", str(package), "--isolate", "reflection", "--live", running=True)
            self.assertEqual(m.snapshot(self.game)[0], before)

    def test_package_selection_rejects_removed_header_and_wrong_build(self):
        before = self.install()
        package, manifest = self.copy_package("removed-header")
        del manifest["files"]["SMSM-ShaderFixes/Configuration.h"]
        (package / m.RECEIPT).write_bytes(m.encoded(manifest))
        with self.assertRaisesRegex(ValueError, "runtime/configuration"):
            self.run_cli("select", "--package", str(package), "--isolate", "reflection", "--live", running=True)
        package, manifest = self.copy_package("wrong-build")
        manifest["client_build"] = "unreviewed-build"
        (package / m.RECEIPT).write_bytes(m.encoded(manifest))
        with self.assertRaisesRegex(ValueError, "build mismatch"):
            self.run_cli("select", "--package", str(package), "--isolate", "reflection", "--live", running=True)
        self.assertEqual(m.snapshot(self.game)[0], before)

    def test_explicit_same_path_cannot_bypass_immutability(self):
        package, manifest = self.copy_package("installed-copy", PACKAGE)
        self.run_cli("install", "--package", str(package))
        before = m.snapshot(self.game)[0]
        manifest["test_edit"] = True
        (package / m.RECEIPT).write_bytes(m.encoded(manifest))
        for extra in ((), ("--package", str(package))):
            with self.assertRaisesRegex(ValueError, "Immutable package"):
                self.run_cli("select", *extra, "--profile", "daily", "--live", running=True)
        self.assertEqual(m.snapshot(self.game)[0], before)

    def test_running_game_blocks_install_uninstall_and_plain_selection(self):
        self.install()
        before = m.snapshot(self.game)[0]
        for args in (("install", "--package", str(PACKAGE)), ("uninstall",), ("select", "--profile", "vanilla")):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "Close the game"):
                self.run_cli(*args, running=True)
        self.assertEqual(m.snapshot(self.game)[0], before)

    def test_linked_shader_directory_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.game / m.FIXES).symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Windows symlink privilege unavailable")
        with self.assertRaisesRegex(ValueError, "Reparse point"):
            m.transition(self.game, {}, self.desired(), self.backups)
        self.assertEqual(list(outside.iterdir()), [])

    def test_edit_during_backup_is_not_rolled_back(self):
        self.install()
        before = m.snapshot(self.game)[0]
        original = m.write_atomic
        edited = False

        def intervening_edit(path, value):
            nonlocal edited
            original(path, value)
            if path.name == "snapshot.json" and not edited:
                edited = True
                (self.game / "d3dx.ini").write_bytes(b"another operation edited this")

        with patch.object(m, "write_atomic", side_effect=intervening_edit), self.assertRaisesRegex(ValueError, "changed since preflight"):
            m.transition(self.game, before, self.desired("vanilla"), self.backups)
        self.assertEqual((self.game / "d3dx.ini").read_bytes(), b"another operation edited this")
        self.assertFalse((self.game / m.JOURNAL).exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_windows_junction_rejected(self):
        outside = self.root / "junction-target"
        outside.mkdir()
        link = self.game / m.FIXES
        env = dict(os.environ, SMSM_TEST_LINK=str(link), SMSM_TEST_TARGET=str(outside))
        subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:SMSM_TEST_LINK -Target $env:SMSM_TEST_TARGET | Out-Null"],
                       env=env, check=True, capture_output=True)
        try:
            with self.assertRaisesRegex(ValueError, "Reparse point"):
                m.transition(self.game, {}, self.desired(), self.backups)
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            # Remove only the junction entry we created, never recurse into it.
            self.assertEqual(link.parent, self.game)
            link.rmdir()


if __name__ == "__main__":
    unittest.main()
