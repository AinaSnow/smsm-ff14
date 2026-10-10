"""Run the crash-relevant composition API sequence in isolated child processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from manage_preview import ROOT


def build(output):
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    installation = Path(subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip())
    vc = sorted((installation / 'VC/Tools/MSVC').iterdir())[-1]
    sdk = Path(os.environ['ProgramFiles(x86)']) / 'Windows Kits/10'
    version = sorted((sdk / 'Include').iterdir())[-1].name
    env = dict(os.environ)
    env['INCLUDE'] = ';'.join(map(str, [vc/'include'] + [sdk/'Include'/version/n for n in ('ucrt','shared','um','winrt')]))
    env['LIB'] = ';'.join(map(str, [vc/'lib/x64'] + [sdk/'Lib'/version/n/'x64' for n in ('ucrt','um')]))
    exe = output / 'dcomp_compat.exe'
    subprocess.run([str(vc/'bin/Hostx64/x64/cl.exe'), '/nologo', '/EHsc', '/std:c++17', '/O2',
        str(ROOT/'tools/offline/dcomp_compat.cpp'), '/Fe:'+str(exe), '/Fo:'+str(output/'dcomp_compat.obj'),
        'dxgi.lib', 'dcomp.lib', 'user32.lib'], env=env, check=True, cwd=output)
    return exe


def run(output, packages, main_only=False):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    exe = build(output)
    results = []
    cases = [('system', None)] + [(p.name, p.resolve()) for p in packages]
    for index, (label, package) in enumerate(cases):
        case = output / str(index)
        case.mkdir()
        child = case / exe.name
        shutil.copyfile(exe, child)
        runtime = Path(os.environ['SystemRoot'])/'System32/d3d11.dll'
        if package:
            for name in ('d3d11.dll', 'nvapi64.dll', 'd3dcompiler_46.dll', 'd3dx.ini'):
                shutil.copyfile(package/name, case/name)
            # Never copy shaders: this is strictly a runtime composition test.
            runtime = case/'d3d11.dll'
        try:
            proc = subprocess.run([str(child), str(runtime)] + (['main-only'] if main_only else []),
                                  cwd=case, capture_output=True, timeout=30)
            result = {'exit_code': proc.returncode, 'stdout': proc.stdout.decode(errors='replace'),
                      'stderr': proc.stderr.decode(errors='replace')}
        except subprocess.TimeoutExpired as exc:
            result = {'exit_code': None, 'timeout': True, 'stdout': (exc.stdout or b'').decode(errors='replace')}
        result.update(label=label, runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
                      game_verified=False, path='main-window' if main_only else 'composition-viewport')
        results.append(result)
        print(json.dumps(result, indent=2))
    (output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
    return results


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('packages', type=Path, nargs='+')
    p.add_argument('--main-only', action='store_true')
    a = p.parse_args()
    run(a.output, a.packages, a.main_only)
