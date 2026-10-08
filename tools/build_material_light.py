"""Build an immutable, default-off, single-path material-stage lamp candidate."""
import argparse
from pathlib import Path
import shutil
from build_preview import BUILD
from build_single_light import validate_settings
from manage_preview import ROOT, RECEIPT, digest, encoded, read_package
from patch_material_light import TARGET, load_original, compile_helper, patch
from patch_forward_light import TARGET as MESH_TARGET, compile_helper as compile_mesh_helper, patch_forward
from shader_compile import Compiler
from validate_d3d11 import validate_package

BASE_SHA='8fc10d0b0ab4bf8bb3dccccf4f62b4bd684dca57e8425aa010324a7b90a211ae'


def build(extraction,base_package,output,decompiler,position=(0,0,0),color=(1,1,1),intensity=2,radius=8,include_mesh=False):
    validate_settings(position,color,intensity,radius)
    manifest,receipt=read_package(base_package)
    if digest(receipt)!=BASE_SHA or manifest['client_build']!=BUILD:
        raise ValueError('Only the audited r10 baseline is accepted; do not stack two lamp injections')
    original=load_original(extraction)
    if output.exists(): raise FileExistsError('Use a fresh immutable output directory')
    compiler=Compiler(ROOT/'d3dcompiler_46.dll')
    helper=compile_helper(output/'build-audit/helper',compiler,position,color,intensity,radius)
    source,data=patch(original,helper,output/'build-audit'/TARGET,decompiler,compiler)
    for name in manifest['files']:
        path=output/name; path.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(base_package/name,path)
    for suffix,content in (('txt',source.read_bytes()),('bin',data)):
        name=f'SMSM-ShaderFixes/{TARGET}-ps.{suffix}'
        (output/name).write_bytes(content); manifest['files'][name]=digest(content)
    manifest['shaders'].append(dict(hash=TARGET,effect='experimental material-stage diffuse lamp',
        original_sha256=digest(original),compiled_sha256=digest(data),
        compiler_diagnostics='Exact original roundtrip; bounded insertion; original interface and material instructions preserved'))
    manifest['effects']['material-light']=dict(shaders=[TARGET],status='experimental-offline-prototype',
        execution_verified=False,performance_verified=False)
    manifest['profiles']={'daily':['tone'],'vanilla':[],'material-light-only':['material-light']}
    manifest['default_profile']='daily'
    manifest['material_light']=dict(position_view=list(position),color_linear=list(color),intensity=intensity,range=radius,
        base_package_sha256=digest(receipt),control='baked immutable parameters; dynamic b13 exists only in offline helper',
        injection='after native diffuse t3 sample, before native AO/material/output encoding',
        audited_target=TARGET,other_material_paths_supported=False,world_locked=False,occlusion=False,
        game_runtime_verified=False,performance_verified=False,
        limits=['No new specular lobe','Screen-visible G-buffer only; no transparent material coverage guarantee',
                'Unoccluded lamp can illuminate through walls','Native scene output is still FP16; tiny increments may quantize away'])
    if include_mesh:
        mesh_original=load_original(extraction,MESH_TARGET)
        mesh_helper=compile_mesh_helper(output/'build-audit/mesh-helper',compiler,position,color,intensity,radius)
        mesh_source,mesh_data=patch_forward(mesh_original,mesh_helper,output/'build-audit'/MESH_TARGET,decompiler,compiler)
        for suffix,content in (('txt',mesh_source.read_bytes()),('bin',mesh_data)):
            name=f'SMSM-ShaderFixes/{MESH_TARGET}-ps.{suffix}'
            (output/name).write_bytes(content);manifest['files'][name]=digest(content)
        manifest['shaders'].append(dict(hash=MESH_TARGET,effect='experimental mesh-material diffuse lamp',
            original_sha256=digest(mesh_original),compiled_sha256=digest(mesh_data),
            compiler_diagnostics='Final host normal/view position reused; native discards preserved; no new bindings'))
        manifest['effects']['mesh-light']=dict(shaders=[MESH_TARGET],status='experimental-offline-prototype',
            execution_verified=False,performance_verified=False)
        manifest['profiles']['mesh-light-only']=['mesh-light']
        manifest['profiles']['material-light-both']=['material-light','mesh-light']
        manifest['material_light'].update(audited_targets=[TARGET,MESH_TARGET],two_path_pixel_overlap_verified=False,
            mesh_injection='after native normal-alignment/camera-light correction, before material/output encoding')
    (output/RECEIPT).write_bytes(encoded(manifest)); read_package(output); validate_package(output)
    print('Built default-off material-light candidate:',output)
    return output


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path)
    p.add_argument('--extraction',type=Path,default=ROOT/'artifacts/client-2026.09.15')
    p.add_argument('--base-package',type=Path,default=ROOT/'artifacts/preview-2026.09.15-r10-managed')
    p.add_argument('--decompiler',type=Path,default=ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe')
    p.add_argument('--position',type=float,nargs=3,default=[0,0,0]); p.add_argument('--color',type=float,nargs=3,default=[1,1,1])
    p.add_argument('--intensity',type=float,default=2); p.add_argument('--range',dest='radius',type=float,default=8)
    p.add_argument('--include-mesh',action='store_true',help='Add independent, default-off audited mesh-material path')
    a=p.parse_args(); build(a.extraction,a.base_package,a.output,a.decompiler.resolve(),a.position,a.color,a.intensity,a.radius,a.include_mesh)
