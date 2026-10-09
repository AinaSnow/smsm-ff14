"""Exercise the complete r10 -> diagnostic -> r10 switch in a simulated client only."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import manage_preview as managed
import native_environment as native
from request_native_capture import request
from request_native_ambient import request as ambient_request


def rejects(fn):
    try:
        fn()
    except (ValueError, RuntimeError):
        return
    raise AssertionError("Unsafe operation was accepted")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--package", required=True, type=Path)
    p.add_argument("--previous-package", type=Path, help="Exercise a real old-to-new add-on update")
    p.add_argument("--runtime", required=True, type=Path)
    p.add_argument("--allow-shader-experiment",action='store_true')
    args = p.parse_args()
    root = args.output.absolute()
    if root.exists():
        raise ValueError("Use a new simulated-client directory")
    game = root / "game"
    game.mkdir(parents=True)
    (game / "ffxivgame.ver").write_text(native.BUILD)
    (game / "ffxiv_dx11.exe").write_bytes(b"simulated executable; never launched")
    package = managed.ROOT / "artifacts/preview-2026.09.15-r10-managed"
    manifest, receipt = managed.read_package(package)
    r10 = managed.desired_package(package, manifest, receipt, ["tone"], "daily")
    managed.transition(game, {}, r10, root / "managed-backups")
    rejects(lambda: native.desired(game, args.package, args.runtime))
    old, _, _ = managed.snapshot(game)
    r10_backup = managed.transition(game, old, {}, root / "managed-backups")
    if args.allow_shader_experiment:
        rejects(lambda:native.desired(game,args.package,args.runtime))
    after = native.desired(game, args.package, args.runtime,args.allow_shader_experiment)
    with patch.object(native, "running_game", return_value=False):
        if args.previous_package:
            initial = native.desired(game, args.previous_package, args.runtime,args.allow_shader_experiment)
            assert initial["SMSM.NativeLighting.addon64"] != after["SMSM.NativeLighting.addon64"]
            native.transition(game, {}, initial, root / "native-backups")
            settings = game / "ReShade.ini"
            settings.write_bytes(b"[GENERAL]\nUserSettings=preserve\n")
            if args.allow_shader_experiment:rejects(lambda:native.updated(game,args.package))
            before_update, next_files = native.updated(game, args.package,args.allow_shader_experiment)
            assert next_files["d3d11.dll"] == before_update["d3d11.dll"]
            assert next_files == after
            original_update_write = native.write_atomic
            def fail_update(path, value):
                if path == game / "SMSM.NativeLighting.addon64":
                    raise OSError("simulated interrupted add-on update")
                original_update_write(path, value)
            try:
                with patch.object(native, "write_atomic", side_effect=fail_update):
                    native.transition(game, before_update, next_files, root / "native-backups")
            except OSError:
                pass
            assert (game / native.JOURNAL).exists()
            native.recover(game)
            assert native.current(game) == initial
            native.transition(game, initial, next_files, root / "native-backups")
            assert native.current(game) == after
            assert settings.read_bytes() == b"[GENERAL]\nUserSettings=preserve\n"
            native.transition(game, after, {}, root / "native-backups")
            settings.unlink()
        native.transition(game, {}, after, root / "native-backups")
        assert native.current(game) == after
        captures = game / "SMSM-native-captures"
        captures.mkdir()
        if json.loads(after[native.RECEIPT]).get('material_input_probe'):
            ambient_request(game,'probe','e86f0d4916054deb',vertex='a'*64,elements=7914)
            command=captures/'ambient-command.txt'
            assert command.read_text()==('probe e86f0d4916054deb 7914 '+'a'*64+'\n');command.unlink()
            old_receipt=json.loads(after[native.RECEIPT]);old_receipt.pop('material_input_probe')
            with patch('request_native_ambient.current',return_value={native.RECEIPT:json.dumps(old_receipt).encode()}):
                rejects(lambda:ambient_request(game,'probe','e86f0d4916054deb',vertex='a'*64,elements=7914))
            rejects(lambda:ambient_request(game,'probe','e86f0d4916054deb',vertex='bad',elements=7914))
            assert not command.exists()
        if json.loads(after[native.RECEIPT]).get('coverage_shader_sha256'):
            ambient_request(game, 'coverage')
            marker_command=captures/'ambient-command.txt'
            assert marker_command.read_bytes()==b'coverage\n'
            try:ambient_request(game,'off')
            except FileExistsError:pass
            else:raise AssertionError('Pending coverage command replaced')
            assert not list(captures.glob('.ambient-command-*.tmp'))
            marker_command.unlink()
            old_receipt=json.loads(after[native.RECEIPT]);old_receipt.pop('coverage_shader_sha256')
            with patch('request_native_ambient.current',return_value={native.RECEIPT:json.dumps(old_receipt).encode()}):
                rejects(lambda:ambient_request(game,'coverage'))
            assert not marker_command.exists()
        if json.loads(after[native.RECEIPT]).get('output_audit'):
            ambient_request(game,'audit')
            marker_command=captures/'ambient-command.txt'
            assert marker_command.read_bytes()==b'audit\n';marker_command.unlink()
            old_receipt=json.loads(after[native.RECEIPT]);old_receipt.pop('output_audit')
            with patch('request_native_ambient.current',return_value={native.RECEIPT:json.dumps(old_receipt).encode()}):
                rejects(lambda:ambient_request(game,'audit'))
            assert not marker_command.exists()
        if json.loads(after[native.RECEIPT]).get('material_roster_sha256'):
            for action in ('census','sample'):
                ambient_request(game,action,**({'shader':'980154264a89fba1','skip':3} if action=='sample' else {}))
                marker_command=captures/'ambient-command.txt'
                assert marker_command.read_bytes()==(b'census\n' if action=='census' else b'sample 980154264a89fba1 3\n')
                marker_command.unlink()
            for hash_,skip in [('bad',0),('980154264a89fba1',-1),('980154264a89fba1',4097),('980154264a89fba1\noff',0)]:
                rejects(lambda:ambient_request(game,'sample',hash_,skip))
            old_receipt=json.loads(after[native.RECEIPT]);old_receipt.pop('material_roster_sha256')
            with patch('request_native_ambient.current',return_value={native.RECEIPT:json.dumps(old_receipt).encode()}):
                rejects(lambda:ambient_request(game,'census'))
            assert not marker_command.exists()
        request(game, "enable")
        command = game / "SMSM-native-command.txt"
        assert command.read_bytes() == b"enable\n"
        try:
            request(game, "capture")
        except FileExistsError:
            pass
        else:
            raise AssertionError("Pending command replaced")
        assert command.read_bytes() == b"enable\n" and not list(captures.glob(".SMSM-native-command-*.tmp"))
        command.unlink()
        rejects(lambda: native.transition(game, {}, after, root / "native-backups"))
        addon = game / "SMSM.NativeLighting.addon64"
        addon.write_bytes(b"edited")
        rejects(lambda: native.current(game))
        addon.write_bytes(after[addon.name])
        native.transition(game, native.current(game), {}, root / "native-backups")
        managed.transition(game, {}, managed.read_backup(r10_backup, game), root / "managed-backups")
        assert managed.snapshot(game)[0] == r10, "prior byte-for-byte r10 not restored"
        managed.transition(game, r10, {}, root / "managed-backups")
        # Inject a write failure after the durable journal: no claimed successful install.
        original_write = native.write_atomic
        def fail_addon(path, value):
            if path.name == "SMSM.NativeLighting.addon64":
                raise OSError("simulated interrupted copy")
            original_write(path, value)
        try:
            with patch.object(native, "write_atomic", side_effect=fail_addon):
                native.transition(game, {}, after, root / "native-backups")
        except OSError:
            pass
        assert (game / native.JOURNAL).exists()
        native.recover(game)
        assert not (game / "d3d11.dll").exists() and not (game / native.JOURNAL).exists()
        (game / "dxgi.dll").write_bytes(b"foreign injector")
        rejects(lambda: native.desired(game, args.package, args.runtime))
        (game / "dxgi.dll").unlink()
    with patch.object(native, "running_game", return_value=True):
        rejects(lambda: native.transition(game, {}, after, root / "native-backups"))
    (root / "report.json").write_text(json.dumps({"simulated_client": True, "real_client_written": False,
        "r10_roundtrip_exact": True, "native_interruption_recovered": True, "collision_modified_and_running_guards": True,
        "old_to_new_addon_update": bool(args.previous_package), "interrupted_update_restores_previous_addon": bool(args.previous_package),
        "runtime_and_user_settings_retained_on_update": bool(args.previous_package),
        "atomic_command_publication_and_duplicate_rejection": True}, indent=2) + "\n")
    print("Simulated r10 roundtrip, interrupted recovery and ownership/process guards passed")


if __name__ == "__main__":
    main()
