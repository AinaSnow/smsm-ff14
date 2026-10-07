"""Ask a D3D11 WARP device to validate every packaged pixel shader offline."""
import argparse
import ctypes as c
import os
from pathlib import Path


def validate_package(package):
    device, context = c.c_void_p(), c.c_void_p()
    # Never load the repository's proxy DLL into the validation process.
    dll = c.WinDLL(str(Path(os.environ["SystemRoot"]) / "System32/d3d11.dll"))
    create = dll.D3D11CreateDevice
    create.argtypes = [c.c_void_p, c.c_uint, c.c_void_p, c.c_uint, c.c_void_p,
                       c.c_uint, c.c_uint, c.POINTER(c.c_void_p), c.c_void_p, c.POINTER(c.c_void_p)]
    create.restype = c.c_int32
    hr = create(None, 5, None, 0, None, 0, 7, c.byref(device), None, c.byref(context))
    if hr < 0:
        raise RuntimeError(f"D3D11CreateDevice(WARP): 0x{hr & 0xffffffff:08x}")
    def method(ptr, index, return_type, *args):
        table = c.cast(ptr, c.POINTER(c.POINTER(c.c_void_p))).contents
        return c.WINFUNCTYPE(return_type, c.c_void_p, *args)(table[index])
    try:
        create_ps = method(device, 15, c.c_int32, c.c_void_p, c.c_size_t, c.c_void_p, c.POINTER(c.c_void_p))
        shaders = sorted((package / "SMSM-ShaderFixes").glob("*-ps*.bin"))
        if not shaders:
            raise ValueError("No packaged pixel shaders")
        for path in shaders:
            data = path.read_bytes()
            shader = c.c_void_p()
            hr = create_ps(device, data, len(data), None, c.byref(shader))
            if hr < 0:
                raise RuntimeError(f"{path.name}: CreatePixelShader 0x{hr & 0xffffffff:08x}")
            method(shader, 2, c.c_ulong)(shader)
        print(f"D3D11 WARP accepted {len(shaders)} pixel shaders")
    finally:
        method(context, 2, c.c_ulong)(context)
        method(device, 2, c.c_ulong)(device)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    validate_package(parser.parse_args().package)
