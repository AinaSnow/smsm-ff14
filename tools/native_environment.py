"""Stopped-client-only install/uninstall of the isolated diagnostic runtime, with recovery."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid
from manage_preview import ROOT, digest, encoded, running_game, write_atomic

RUNTIME_SHA256 = "0cee63f9c9f13f3ac909c5b4903f4dbb4b719a7ab3b4f13b0deaf83c814b94f7"
RECEIPT = "SMSM-native-install.json"
JOURNAL = "SMSM-native-transaction.json"
NAMES = {"d3d11.dll", "SMSM.NativeLighting.addon64", RECEIPT}
BUILD = "2026.09.15.0000.0000"


def safe(root, name):
    if name not in NAMES | {JOURNAL}:
        raise ValueError(f"Unowned native path: {name}")
    root = root.absolute()
    path = root / name
    for current in (path, *path.parents):
        if current.exists() or current.is_symlink():
            attributes = getattr(current.lstat(), "st_file_attributes", 0)
            if current.is_symlink() or attributes & 0x400:
                raise ValueError(f"Reparse path: {current}")
    return path


def stopped(game):
    for name in NAMES | {JOURNAL}:
        safe(game, name)
    if running_game(game):
        raise ValueError("Exit FF14 before switching any injection DLL")


def current(game):
    receipt = safe(game, RECEIPT)
    if not receipt.exists():
        return {}
    value = receipt.read_bytes()
    meta = json.loads(value)
    if meta.get("schema") != 1 or set(meta["files"]) != NAMES - {RECEIPT}:
        raise ValueError("Invalid native ownership receipt")
    data = {RECEIPT: value}
    for name, sha in meta["files"].items():
        data[name] = safe(game, name).read_bytes()
        if digest(data[name]) != sha:
            raise ValueError(f"Modified installed native file: {name}")
    return data


def preflight(game, before, after):
    for name in before.keys() | after.keys():
        path = safe(game, name)
        if name not in before and path.exists():
            raise ValueError(f"Refusing existing injector/file: {name}")
        if name in before and (not path.exists() or path.read_bytes() != before[name]):
            raise ValueError(f"Concurrent file change: {name}")


def apply(game, before, after):
    for name, value in after.items():
        if before.get(name) != value:
            write_atomic(safe(game, name), value)
    for name in before.keys() - after.keys():
        path = safe(game, name)
        if path.exists():
            path.unlink()


def recover(game):
    stopped(game)
    journal = json.loads(safe(game, JOURNAL).read_bytes())
    if os.path.normcase(journal["game"]) != os.path.normcase(str(game.resolve())):
        raise ValueError("Cross-client journal")
    old = {}
    backup = Path(journal["backup"])
    for name, sha in journal["before"].items():
        value = safe(backup, name).read_bytes()
        if digest(value) != sha:
            raise ValueError("Damaged native backup")
        old[name] = value
    now = {}
    for name in journal["before"].keys() | journal["after"].keys():
        path = safe(game, name)
        if path.exists():
            value = path.read_bytes()
            if digest(value) not in {journal["before"].get(name), journal["after"].get(name)}:
                raise ValueError(f"Manual change prevents recovery: {name}")
            now[name] = value
    apply(game, now, old)
    safe(game, JOURNAL).unlink()


def transition(game, before, after, backups):
    stopped(game)
    preflight(game, before, after)
    backup = backups.resolve() / uuid.uuid4().hex
    backup.mkdir(parents=True)
    for name, value in before.items():
        write_atomic(safe(backup, name), value)
    journal = {"schema": 1, "game": str(game.resolve()), "backup": str(backup),
               "before": {n: digest(v) for n, v in before.items()}, "after": {n: digest(v) for n, v in after.items()}}
    with safe(game, JOURNAL).open("xb") as stream:
        stream.write(encoded(journal)); stream.flush(); os.fsync(stream.fileno())
    try:
        preflight(game, before, after)
        stopped(game)
    except BaseException:
        safe(game, JOURNAL).unlink()
        raise
    # A failed mutation deliberately retains the durable recovery journal.
    apply(game, before, after)
    if current(game) != after or any(safe(game,n).exists() for n in before.keys()-after.keys()):
        raise ValueError("Native write verification failed; run recover")
    safe(game, JOURNAL).unlink()
    return backup


def read_candidate(package, allow_shader_experiment=False):
    meta = json.loads((package / "SMSM-native-package.json").read_bytes())
    if (meta.get("reshade_version") != "6.8.0" or meta.get("api_version") != 20
            or meta.get("default_enabled") is not False or type(meta.get("shader_replacement")) is not bool
            or meta.get("architecture") != "x64"):
        raise ValueError("Unreviewed package configuration")
    if meta['shader_replacement'] and not allow_shader_experiment:
        raise ValueError("Shader experiment requires explicit --allow-shader-experiment")
    addon = (package / "SMSM.NativeLighting.addon64").read_bytes()
    if digest(addon) != meta["files"]["SMSM.NativeLighting.addon64"]:
        raise ValueError("Native package integrity failure")
    return meta, addon


def with_receipt(files, meta):
    data = dict(files)
    data[RECEIPT] = encoded({"schema": 1, "client_build": BUILD, "files": {n: digest(v) for n, v in files.items()},
                            "default_enabled": False, "shader_replacement": meta.get('shader_replacement',False),
                            "package_sha256": digest(encoded(meta))})
    return data


def updated(game, package, allow_shader_experiment=False):
    """Replace only an owned add-on and its receipt; retain runtime and user settings."""
    if (game / "ffxivgame.ver").read_text().strip() != BUILD:
        raise ValueError("Game version requires a new shader identity audit")
    before = current(game)
    if not before or digest(before["d3d11.dll"]) != RUNTIME_SHA256:
        raise ValueError("Update requires the verified fixed diagnostic runtime")
    for name in ("dxgi.dll", "d3d9.dll", "opengl32.dll", "GShade64.dll", "SMSM-preview.json", "SMSM-state.json", "SMSM-transaction.json"):
        if (game / name).exists():
            raise ValueError(f"Conflicting environment: {name}")
    meta, addon = read_candidate(package, allow_shader_experiment)
    return before, with_receipt({"d3d11.dll": before["d3d11.dll"], "SMSM.NativeLighting.addon64": addon}, meta)


def desired(game, package, runtime, allow_shader_experiment=False):
    if (game / "ffxivgame.ver").read_text().strip() != BUILD:
        raise ValueError("Game version requires a new shader identity audit")
    for name in ("dxgi.dll", "d3d9.dll", "opengl32.dll", "GShade64.dll", "ReShade.ini", "SMSM-preview.json", "SMSM-state.json", "SMSM-transaction.json"):
        if (game / name).exists():
            raise ValueError(f"Existing environment must be backed up and switched separately: {name}")
    fixes = game / "SMSM-ShaderFixes"
    if fixes.exists() and (fixes.is_symlink() or getattr(fixes.lstat(), "st_file_attributes", 0) & 0x400 or any(fixes.iterdir())):
        raise ValueError("Existing shader environment is not empty")
    meta, addon = read_candidate(package, allow_shader_experiment)
    runtime_bytes = runtime.read_bytes()
    if digest(runtime_bytes) != RUNTIME_SHA256:
        raise ValueError("Requires exact official full-add-on ReShade 6.8.0 x64 runtime")
    return with_receipt({"d3d11.dll": runtime_bytes, "SMSM.NativeLighting.addon64": addon}, meta)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["install", "update", "status", "uninstall", "recover"])
    p.add_argument("--game", required=True, type=Path)
    p.add_argument("--package", type=Path)
    p.add_argument("--runtime", type=Path)
    p.add_argument("--allow-shader-experiment", action="store_true", help="Explicitly install a default-off material shader experiment")
    p.add_argument("--backup-root", type=Path, default=ROOT / "artifacts/native-install-backups")
    args = p.parse_args()
    game = args.game.absolute()
    if args.action == "status":
        print(json.dumps({"native_files": {n: digest(v) for n,v in current(game).items()},
                          "game_running": running_game(game), "capture_result": "read manifests; disk state does not prove runtime execution"}, indent=2))
        return
    stopped(game)
    if args.action == "recover":
        recover(game); print("Recovered previous native files"); return
    if safe(game, JOURNAL).exists():
        raise ValueError("Incomplete transaction: run recover")
    before = current(game)
    if args.action == "install":
        if before or not args.package or not args.runtime:
            raise ValueError("Install requires a pristine environment, --package and --runtime")
        after = desired(game, args.package, args.runtime, args.allow_shader_experiment)
    elif args.action == "update":
        if not args.package or args.runtime:
            raise ValueError("Update requires --package only; runtime switching is not supported")
        before, after = updated(game, args.package, args.allow_shader_experiment)
    else:
        if not before:
            raise ValueError("No owned native installation")
        after = {}
    print(f"Native files updated. Backup: {transition(game, before, after, args.backup_root)}")
    print("ReShade-created config/logs and capture data are preserved. Keep the prior r10 backup for restoration.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(f"ERROR: {error}")
