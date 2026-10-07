"""Manage immutable preview packages, effect selections and recoverable file transactions.

No DLL hot swapping. --live only changes effect source/binary files and records
that F10 is pending; it never claims that the running game applied the change.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "SMSM-preview.json"
STATE = "SMSM-state.json"
JOURNAL = "SMSM-transaction.json"
FIXES = "SMSM-ShaderFixes"
FIXED = {"d3dx.ini", "d3d11.dll", "nvapi64.dll", "d3dcompiler_46.dll", "LICENSE", "COPYING"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def safe_path(root, relative, metadata=False):
    """Restrict both names and resolved locations; reject junction/symlink traversal."""
    p = PurePosixPath(relative)
    if (not relative or str(p) != relative or "\\" in relative or ":" in relative or p.is_absolute()
            or any(part in (".", "..") for part in relative.split("/"))):
        raise ValueError(f"Unsafe path: {relative}")
    allowed = relative in FIXED or (metadata and relative in {RECEIPT, STATE})
    if len(p.parts) == 2 and p.parts[0] == FIXES:
        allowed = bool(re.fullmatch(r"[0-9a-f]{16}-ps(?:_replace)?\.(txt|bin)|[A-Za-z0-9_-]+\.h", p.name))
    if not allowed:
        raise ValueError(f"Not a managed mod file: {relative}")
    base = root.resolve()
    path = base.joinpath(*p.parts)
    current = path
    while current != base:
        try:
            attributes = getattr(current.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            attributes = 0
        if current.is_symlink() or attributes & 0x400:
            raise ValueError(f"Reparse point is not supported: {current}")
        current = current.parent
    if not path.resolve().is_relative_to(base):
        raise ValueError(f"Path escapes root: {relative}")
    return path


def validate_manifest(manifest):
    files = manifest["files"]
    if not files or len({p.casefold() for p in files}) != len(files):
        raise ValueError("Empty manifest or case-colliding paths")
    for name, sha in files.items():
        safe_path(ROOT / "artifacts", name)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            raise ValueError(f"Invalid hash: {name}")
    if not FIXED.issubset(files):
        raise ValueError("Missing runtime/configuration files")
    if manifest.get("schema_version", 1) == 2:
        groups = manifest["effects"]
        listed = [h for group in groups.values() for h in group["shaders"]]
        actual = [row["hash"] for row in manifest["shaders"]]
        if len(listed) != len(set(listed)) or set(listed) != set(actual):
            raise ValueError("Effects must partition all packaged shader hashes")
        for h in listed:
            if not re.fullmatch(r"[0-9a-f]{16}", h):
                raise ValueError("Invalid shader hash")
            entries = [n for n in files if n.startswith(f"{FIXES}/{h}-ps")]
            if sorted(Path(n).suffix for n in entries) != [".bin", ".txt"]:
                raise ValueError(f"Expected exactly one source/binary pair: {h}")
        for profile in manifest["profiles"].values():
            if len(profile) != len(set(profile)) or set(profile) - groups.keys():
                raise ValueError("Invalid profile")
        if manifest["default_profile"] not in manifest["profiles"]:
            raise ValueError("Missing default profile")
    elif manifest.get("schema_version", 1) != 1:
        raise ValueError("Unsupported package schema")


def selected_files(manifest, effects):
    if len(effects) != len(set(effects)) or set(effects) - manifest["effects"].keys():
        raise ValueError("Unknown or duplicate effect")
    hashes = {h for e in effects for h in manifest["effects"][e]["shaders"]}
    return {name: sha for name, sha in manifest["files"].items()
            if not re.match(rf"^{FIXES}/[0-9a-f]{{16}}-ps", name) or Path(name).name[:16] in hashes}


def read_package(path):
    path = path.resolve()
    receipt = safe_path(path, RECEIPT, True).read_bytes()
    manifest = json.loads(receipt)
    validate_manifest(manifest)
    for name, sha in manifest["files"].items():
        if digest(safe_path(path, name).read_bytes()) != sha:
            raise ValueError(f"Package integrity failure: {name}")
    return manifest, receipt


def snapshot(game):
    receipt_path = safe_path(game, RECEIPT, True)
    if not receipt_path.exists():
        if safe_path(game, STATE, True).exists():
            raise ValueError("Orphaned managed state; review before changing files")
        return {}, None, None
    receipt = receipt_path.read_bytes()
    manifest = json.loads(receipt)
    validate_manifest(manifest)
    state = None
    if manifest.get("schema_version") == 2:
        state = json.loads(safe_path(game, STATE, True).read_bytes())
        if state.get("schema_version") != 1:
            raise ValueError("Unsupported managed-state schema")
        if state["package_sha256"] != digest(receipt):
            raise ValueError("State/receipt mismatch")
        expected = selected_files(manifest, state["effects"])
        if state["files"] != expected:
            raise ValueError("State does not match selected package files")
    else:
        if safe_path(game, STATE, True).exists():
            raise ValueError("Legacy receipt has unexpected managed state")
        expected = manifest["files"]
    data = {RECEIPT: receipt}
    for name, sha in expected.items():
        value = safe_path(game, name).read_bytes()
        if digest(value) != sha:
            raise ValueError(f"Installed file changed; preserve it before continuing: {name}")
        data[name] = value
    if state is not None:
        data[STATE] = safe_path(game, STATE, True).read_bytes()
    return data, manifest, state


def check_unmanaged(game, owned):
    directory = game / FIXES
    # Also rejects a linked directory when it is empty.
    safe_path(game, f"{FIXES}/Configuration.h")
    if directory.exists():
        for p in directory.iterdir():
            name = f"{FIXES}/{p.name}"
            if name not in owned:
                raise ValueError(f"Unmanaged item in shader directory; preserve/review: {name}")


def running_game(game):
    if os.name != "nt":
        raise RuntimeError("Live-client management requires Windows")
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); @((Get-Process -Name ffxiv_dx11 "
               "-ErrorAction SilentlyContinue) | Select-Object Id,Path) | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8", check=True)
    rows = json.loads(result.stdout.strip() or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    for row in rows:
        if not row.get("Path"):
            raise RuntimeError("Cannot inspect FF14 process path; run from an administrator terminal")
    target = os.path.normcase(str((game / "ffxiv_dx11.exe").resolve()))
    return any(os.path.normcase(str(Path(row["Path"]).resolve())) == target for row in rows)


def check_build(game, manifest):
    version = (game / "ffxivgame.ver").read_text().strip()
    if version != manifest["client_build"]:
        raise ValueError(f"Client build mismatch: {version}; compatibility review required")


def desired_package(package, manifest, receipt, effects, label):
    if manifest.get("schema_version") != 2:
        raise ValueError("New installs require a managed schema-2 package; legacy installations can be upgraded")
    files = selected_files(manifest, effects)
    data = {name: safe_path(package, name).read_bytes() for name in files}
    data[RECEIPT] = receipt
    data[STATE] = encoded({"schema_version": 1, "package_path": str(package.resolve()),
                           "package_sha256": digest(receipt), "effects": sorted(effects), "selection": label,
                           "files": files, "application": "pending-restart-or-F10",
                           "runtime_verified": False})
    return data


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".smsm-" + uuid.uuid4().hex)
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def read_backup(path, game):
    if path.is_symlink():
        raise ValueError("Backup path must not be a link")
    meta = json.loads((path / "snapshot.json").read_text(encoding="utf-8"))
    if os.path.normcase(meta["game"]) != os.path.normcase(str(game.resolve())):
        raise ValueError("Backup belongs to a different client")
    data = {}
    for name, sha in meta["files"].items():
        value = safe_path(path / "files", name, True).read_bytes()
        if digest(value) != sha:
            raise ValueError(f"Backup integrity failure: {name}")
        data[name] = value
    return data


def apply_files(game, before, after):
    # Never enumerate and delete a directory. Only explicit, checked owned paths.
    for name in sorted(after, key=lambda n: (n in (RECEIPT, STATE), n)):
        if before.get(name) != after[name]:
            write_atomic(safe_path(game, name, True), after[name])
    for name in sorted(before.keys() - after.keys()):
        path = safe_path(game, name, True)
        if path.exists():
            path.unlink()


def recover(game):
    journal_path = game / JOURNAL
    if journal_path.is_symlink():
        raise ValueError("Journal must not be a link")
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    old = read_backup(Path(journal["backup"]), game)
    if journal["before"] != {n: digest(v) for n, v in old.items()}:
        raise ValueError("Journal/backup mismatch")
    current = {}
    for name in journal["before"].keys() | journal["after"].keys():
        path = safe_path(game, name, True)
        if path.exists():
            value = path.read_bytes()
            if digest(value) not in (journal["before"].get(name), journal["after"].get(name)):
                raise ValueError(f"Changed during transaction; cannot auto-recover: {name}")
            current[name] = value
    apply_files(game, current, old)
    journal_path.unlink()


def preflight(game, before, after):
    check_unmanaged(game, before)
    for name in before.keys() | after.keys():
        path = safe_path(game, name, True)
        if name not in before and path.exists():
            raise ValueError(f"Existing file would be overwritten: {name}")
        if name in before and (not path.exists() or path.read_bytes() != before[name]):
            raise ValueError(f"File changed since preflight: {name}")


def transition(game, before, after, backup_root):
    preflight(game, before, after)
    backup = backup_root.resolve() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex)
    backup.mkdir(parents=True)
    for name, value in before.items():
        write_atomic(safe_path(backup / "files", name, True), value)
    write_atomic(backup / "snapshot.json", encoded({"game": str(game.resolve()),
                  "files": {n: digest(v) for n, v in before.items()}}))
    journal_path = game / JOURNAL
    with journal_path.open("x", encoding="utf-8") as stream:
        json.dump({"backup": str(backup), "before": {n: digest(v) for n, v in before.items()},
                   "after": {n: digest(v) for n, v in after.items()}}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    # Another manager could have finished while this backup was being written.
    # Recheck under the exclusive journal before any game-file mutation. Never
    # roll back somebody else's intervening edit to our earlier snapshot.
    try:
        preflight(game, before, after)
    except BaseException:
        journal_path.unlink()
        raise
    try:
        apply_files(game, before, after)
        for name, value in after.items():
            if safe_path(game, name, True).read_bytes() != value:
                raise RuntimeError(f"Write verification failed: {name}")
    except BaseException:
        # Retain the backup and journal if recovery itself fails. `recover` can retry.
        recover(game)
        raise
    journal_path.unlink()
    return backup


def selection(manifest, profile=None, effects=None, isolate=None):
    if sum(x is not None for x in (profile, effects, isolate)) > 1:
        raise ValueError("Choose one of profile, effects or isolate")
    if isolate is not None:
        result, label = [isolate], "isolate:" + isolate
    elif effects is not None:
        result, label = [e for e in effects.split(",") if e], "custom"
    else:
        label = profile or manifest["default_profile"]
        result = manifest["profiles"][label]
    selected_files(manifest, result)  # Reject unknown effects before touching files.
    return result, label


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("status", "install", "select", "uninstall", "rollback", "recover", "audit"))
    p.add_argument("--client-root", required=True, type=Path)
    p.add_argument("--package", type=Path)
    p.add_argument("--profile")
    p.add_argument("--effects", help="Comma-separated enabled effects; empty string means original")
    p.add_argument("--isolate", help="Only this effect, so F9 compares just that effect")
    p.add_argument("--enable", action="append", default=[], help="Enable one effect while retaining other selections; repeatable")
    p.add_argument("--disable", action="append", default=[], help="Disable one effect while retaining other selections; repeatable")
    p.add_argument("--live", action="store_true", help="Select shader files while game runs; manual F10 required, runtime validation pending")
    p.add_argument("--backup", type=Path)
    p.add_argument("--backup-root", type=Path, default=ROOT / "artifacts/install-backups")
    p.add_argument("--extraction", type=Path)
    args = p.parse_args()
    game = (args.client_root / "game").resolve(strict=True)
    if args.live and args.action != "select":
        p.error("--live is only valid for effect selection, never installation or rollback")
    if (args.enable or args.disable) and (args.action != "select" or any(x is not None for x in (args.profile, args.effects, args.isolate))):
        p.error("--enable/--disable requires select and cannot be combined with a profile/effects/isolate")
    if set(args.enable) & set(args.disable):
        p.error("Cannot enable and disable the same effect")
    if args.action == "recover":
        if running_game(game):
            raise ValueError("Close the game before transaction recovery")
        recover(game)
        print("Recovered pre-transaction files. Backup retained.")
        return
    if (game / JOURNAL).exists():
        raise ValueError("Interrupted transaction: close the game, then run recover")
    before, current, state = snapshot(game)
    if args.action == "status":
        check_unmanaged(game, before)
        compact_state = {k: v for k, v in state.items() if k != "files"} if state else None
        print(json.dumps({"client_build": (game / "ffxivgame.ver").read_text().strip(),
                          "installed": current is not None, "package_build": current.get("client_build") if current else None,
                          "compatible_build": (game / "ffxivgame.ver").read_text().strip() == current["client_build"] if current else None,
                          "integrity": "verified", "state": compact_state,
                          "effect_status": current.get("effects") if current else None}, indent=2))
        return
    if args.action == "audit":
        manifest, _ = read_package(args.package) if args.package else (current, None)
        if not manifest or not args.extraction:
            raise ValueError("audit requires an installed/selected package and --extraction")
        extraction = json.loads((args.extraction / "manifest.json").read_text())
        originals = {s["Hash"]: s for s in extraction["Shaders"]}
        print(json.dumps({"extracted_build": extraction["ClientBuild"], "enables_nothing": True,
                          "shaders": [{"hash": s["hash"], "original_matches":
                          originals.get(s["hash"], {}).get("Sha256") == s["original_sha256"],
                          "execution_proven": False} for s in manifest["shaders"]]}, indent=2))
        return
    running = running_game(game)
    if running and not (args.action == "select" and args.live):
        raise ValueError("Close the game first; select --live is the only shader-only exception")
    if args.action in ("install", "select"):
        if args.action == "select":
            if not state:
                raise ValueError("Install a managed package once before selecting effects")
            package = Path(state["package_path"])
        else:
            if not args.package:
                p.error("install requires --package")
            package = args.package
        manifest, receipt = read_package(package)
        check_build(game, manifest)
        if args.action == "select" and digest(receipt) != state["package_sha256"]:
            raise ValueError("Immutable package was modified; install an explicitly reviewed new package")
        if args.enable or args.disable:
            if (set(args.enable) | set(args.disable)) - manifest["effects"].keys():
                raise ValueError("Unknown effect")
            effects = sorted((set(state["effects"]) | set(args.enable)) - set(args.disable))
            label = "custom"
        else:
            effects, label = selection(manifest, args.profile, args.effects, args.isolate)
        after = desired_package(package, manifest, receipt, effects, label)
        if args.action == "select":
            changed = {n for n in before.keys() | after.keys() if before.get(n) != after.get(n)}
            if any(n != STATE and not re.fullmatch(rf"{FIXES}/[0-9a-f]{{16}}-ps(?:_replace)?\.(txt|bin)", n) for n in changed):
                raise ValueError("Selection tried to change runtime/configuration files")
    elif args.action == "uninstall":
        if not current:
            raise ValueError("No preview installed")
        after = {}
    else:
        if not args.backup:
            p.error("rollback requires --backup")
        after = read_backup(args.backup, game)
        if RECEIPT in after:
            check_build(game, json.loads(after[RECEIPT]))
    backup = transition(game, before, after, args.backup_root)
    print(f"Files updated. Backup: {backup}")
    if args.action == "select" and running:
        print("Game application NOT confirmed. Return to game and press F10 once. If uncertain, restart. F9 is all active effects; isolate selects one.")
    else:
        print("Start/restart the game to apply. Runtime and performance verification remain pending.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
