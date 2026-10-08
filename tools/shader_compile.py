"""Windows D3DCompiler helpers; outputs go to a separate build directory."""
import argparse
import ctypes as c
from pathlib import Path


def blob_bytes(ptr):
    if not ptr:
        return b""
    table = c.cast(ptr, c.POINTER(c.POINTER(c.c_void_p))).contents
    get_ptr = c.WINFUNCTYPE(c.c_void_p, c.c_void_p)(table[3])
    get_size = c.WINFUNCTYPE(c.c_size_t, c.c_void_p)(table[4])
    release = c.WINFUNCTYPE(c.c_ulong, c.c_void_p)(table[2])
    try:
        return c.string_at(get_ptr(ptr), get_size(ptr))
    finally:
        release(ptr)


class Compiler:
    def __init__(self, dll=None):
        self.dll = c.WinDLL(str(dll) if dll else "d3dcompiler_47.dll")
        self.dll.D3DDisassemble.argtypes = [c.c_void_p, c.c_size_t, c.c_uint, c.c_char_p, c.POINTER(c.c_void_p)]
        self.dll.D3DDisassemble.restype = c.c_int32
        self.dll.D3DCompileFromFile.argtypes = [c.c_wchar_p, c.c_void_p, c.c_void_p, c.c_char_p, c.c_char_p,
                                               c.c_uint, c.c_uint, c.POINTER(c.c_void_p), c.POINTER(c.c_void_p)]
        self.dll.D3DCompileFromFile.restype = c.c_int32

    def disassemble(self, data):
        code = c.c_void_p()
        hr = self.dll.D3DDisassemble(data, len(data), 0, None, c.byref(code))
        text = blob_bytes(code).rstrip(b"\0").decode("utf-8", errors="replace")
        if hr < 0:
            raise RuntimeError(f"D3DDisassemble failed: {hr & 0xffffffff:08x}")
        return text

    def compile(self, path, profile="ps_5_0", *, flags=1 << 15):
        code, error = c.c_void_p(), c.c_void_p()
        # D3D_COMPILE_STANDARD_FILE_INCLUDE = 1. Resolve headers relative to source.
        hr = self.dll.D3DCompileFromFile(str(path.resolve()), None, 1, b"main", profile.encode(),
                                       flags, 0, c.byref(code), c.byref(error))
        diagnostics = blob_bytes(error).rstrip(b"\0").decode("utf-8", errors="replace")
        data = blob_bytes(code)
        if hr < 0:
            raise RuntimeError(f"{path.name}: {diagnostics}")
        return data, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["compile", "disassemble"])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dll", type=Path)
    args = parser.parse_args()
    compiler = Compiler(args.dll)
    args.output.mkdir(parents=True, exist_ok=True)
    files = sorted(args.source.glob("*_replace.txt" if args.operation == "compile" else "*.bin")) if args.source.is_dir() else [args.source]
    failures = []
    for source in files:
        try:
            if args.operation == "compile":
                data, diagnostics = compiler.compile(source)
                target = args.output / (source.stem + ".bin")
                target.write_bytes(data)
                (args.output / (source.stem + ".asm")).write_text(compiler.disassemble(data), encoding="utf-8")
                (args.output / (source.stem + ".log")).write_text(diagnostics, encoding="utf-8")
            else:
                (args.output / (source.stem + ".asm")).write_text(compiler.disassemble(source.read_bytes()), encoding="utf-8")
        except RuntimeError as ex:
            failures.append(str(ex))
    print(f"{len(files) - len(failures)}/{len(files)} succeeded")
    for error in failures:
        print(error)
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
