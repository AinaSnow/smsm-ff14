"""One exact mesh-material PS, after native light/normal alignment correction."""
from build_single_light import validate_settings
from manage_preview import ROOT
from patch_material_light import patch,diffuse_prefix

TARGET='980154264a89fba1'
ANCHOR='mad r7.xyz, r7.xyzx, r4.wwww, r0.wwww'


def compile_helper(work,compiler,position=(0,0,0),color=(1,1,1),intensity=2,radius=8,*,softness=0,soft_profile='bounded'):
    validate_settings(position,color,intensity,radius); work.mkdir(parents=True,exist_ok=True)
    fmt=lambda xs:', '.join(format(float(x),'.9g') for x in xs)
    (work/'single_light_parameters.h').write_text(
        'static const float4 lampPositionRange=float4('+fmt([*position,radius])+');\n'+
        'static const float4 lampColorIntensity=float4('+fmt([*color,intensity])+');\n')
    path=work/'forward_material_light.hlsl'
    path.write_text(diffuse_prefix(work,softness,soft_profile)+'#define SINGLE_LIGHT_BAKED 1\n'+(ROOT/'tools/patches/forward_material_light.hlsl').read_text())
    data,warnings=compiler.compile(path)
    if warnings: raise ValueError(warnings)
    return data


def patch_forward(original,helper,work,decompiler,compiler):
    return patch(original,helper,work,decompiler,compiler,target=TARGET,anchor=ANCHOR,
                 add_template='add r7.xyz, r7.xyzx, {result}.xyzx',input_remap={'v0':'r1','v1':'v6'})
