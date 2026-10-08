"""Submit one frame-boundary diagnostic command to an already installed ReShade add-on."""
import argparse
import os
from pathlib import Path
import uuid


def request(directory, command):
    directory = directory.resolve(strict=True)
    if not (directory / "SMSM.NativeLighting.addon64").is_file():
        raise ValueError("No SMSM native add-on in the selected executable directory")
    path = directory / "SMSM-native-command.txt"
    # Publish a complete command atomically. On Windows rename refuses an existing destination.
    if os.name != "nt":
        raise ValueError("Native diagnostic command transport requires Windows")
    # On protected clients the initialized capture directory grants the game's
    # user Modify. A same-volume rename retains that DACL, including Delete,
    # so the unelevated game can consume a command published by an admin.
    capture_root = directory / "SMSM-native-captures"
    if capture_root.exists():
        attributes = getattr(capture_root.lstat(), "st_file_attributes", 0)
        if capture_root.is_symlink() or attributes & 0x400 or not capture_root.is_dir():
            raise ValueError("Capture command staging directory must be a real owned directory")
        staging = capture_root
    else:
        staging = directory
    temporary = staging / (".SMSM-native-command-" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(command + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(f"Submitted {command}; read ReShade.log and SMSM-native-captures for the result")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path, help="directory containing the game executable and diagnostic add-on")
    p.add_argument("command", choices=["enable", "capture", "stop"])
    args = p.parse_args()
    request(args.directory, args.command)
