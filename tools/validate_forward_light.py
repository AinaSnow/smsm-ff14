"""Actual mesh-material PS rasterization with controlled synthetic varyings.

The fixture VS supplies a plane, not game geometry or skinning. Original PS
discard/material logic executes unchanged; runtime stencil coverage is unknown.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from manage_preview import ROOT, encoded, digest
from offline_render import render
from patch_material_light import load_original
from patch_forward_light import TARGET,compile_helper,patch_forward
from shader_compile import Compiler
from validate_single_light import cpu_light


def fixture(compiler,work,width=64,height=40,normal_xy=(.5,.5),alpha=1,albedo=(.8,.8,.8),
            material_type=0,metal=0,wetness=0,exposure=1,depth=1,basis_angle=0):
    work.mkdir(parents=True,exist_ok=True)
    vs=work/'plane.hlsl'
    vs.write_text('''struct O {float4 p:SV_POSITION; float4 color:COLOR0;
float4 uv:TEXCOORD0; float4 n:TEXCOORD1; float4 t:TEXCOORD2;
float4 b:TEXCOORD3; float4 view:TEXCOORD4; float4 hair:TEXCOORD5;};
O main(uint id:SV_VertexID){O o; float2 uv=float2((id<<1)&2,id&2);
o.p=float4(uv*float2(2,-2)+float2(-1,1),.5,1);o.color=1;
o.uv=float4(.25,.25,.75,.25);o.n=float4(0,0,-1,0);o.t=float4(1,0,0,0);o.b=float4(0,1,0,1);
o.view=float4((uv.x*2-1)*3,(1-uv.y*2)*2,5,'''+str(float(wetness))+''');o.hair=float4(0,1,0,0);return o;}''')
    angle=np.deg2rad(basis_angle);sn,cs=float(np.sin(angle)),float(np.cos(angle))
    if abs(cs)<1e-12: cs=0
    vs.write_text(vs.read_text().replace('float4(0,0,-1,0)',f'float4({sn},0,{-cs},0)').replace('float4(1,0,0,0)',f'float4({cs},0,{sn},0)'))
    data,warnings=compiler.compile(vs,'vs_5_0')
    if warnings: raise ValueError(warnings)
    vertex=work/'plane.bin'; vertex.write_bytes(data)
    y,x=np.mgrid[:height,:width].astype(float)
    pos=np.stack((((x+.5)/width*2-1)*3,(1-(y+.5)/height*2)*2,np.full_like(x,5)),-1)
    xy=np.array(normal_xy)-.5; z=np.sqrt(max(.25-float(xy@xy),1e-6))
    normal=np.array([xy[0]*cs+z*sn,xy[1],xy[0]*sn-z*cs]);normal/=np.linalg.norm(normal)
    f=dict(position=pos,normal=np.broadcast_to(normal,pos.shape).copy(),mask=np.ones((height,width),bool),width=width,height=height)
    tex={i:np.broadcast_to(v,(height,width,4)).astype(np.float32).copy() for i,v in {
        0:(.25,.25,.25,0),1:(.1,.1,.1,0),2:(depth,0,0,0),4:(.5,.5,0,0),6:(0,.6,metal,1),8:(1,1,1,1)}.items()}
    tex[5]=np.array([[[*normal_xy,.5,1],[.5,.5,.5,alpha]],[[*normal_xy,.5,1],[.5,.5,.5,alpha]]],np.float32)
    mat=np.zeros((17,4),np.float32); mat[0,:3]=np.sqrt(albedo); mat[11,1]=1
    common=np.zeros((4,4),np.float32); common[0]=[1/width,1/height,0,0];common[3,0]=exposure
    camera=np.zeros((6,4),np.float32);camera[:3,:3]=camera[3:,:3]=np.eye(3)
    instance=np.zeros((3,4),np.float32);instance[0]=1
    customize=np.ones((4,4),np.float32)
    ambient=np.zeros((10,4),np.float32);ambient[3,3]=1;ambient[5]=(1,0,1,0);ambient[9,0]=1
    structured=np.zeros((256,32),np.float32); structured[:,2]=1
    structured.view(np.uint32)[:,0]=material_type
    cube=np.zeros((6,2,2,4),np.float32);cube[...,3]=1
    inputs=dict(textures=tex,constants={0:mat,1:common,2:np.zeros((1,4),np.float32),3:camera,4:instance,5:customize,6:ambient},
                structured={3:(128,structured.tobytes())},cubes={7:cube},vertex=vertex)
    return f,inputs


def run(output,extraction,decompiler):
    output.mkdir(parents=True,exist_ok=False);compiler=Compiler(ROOT/'d3dcompiler_46.dll')
    original=load_original(extraction,TARGET); path=output/'original.bin';path.write_bytes(original)
    checks=[]
    def check(name,a,b,tol=3e-6):
        error=float(np.max(np.abs(a-b)));ok=bool(np.isfinite(a).all() and np.isfinite(b).all() and error<=tol)
        checks.append(dict(name=name,error=error,tolerance=tol,passed=ok))
        if not ok: raise AssertionError(f'{name}: {error} or nonfinite')
    def candidate(name,pos=(0,0,0),color=(1,1,1),intensity=2,radius=8):
        helper=compile_helper(output/(name+'-helper'),compiler,pos,color,intensity,radius)
        _,data=patch_forward(original,helper,output/(name+'-audit'),decompiler,compiler)
        target=output/(name+'.bin');target.write_bytes(data);return target
    lamp=candidate('lamp');zero=candidate('zero',intensity=0)
    if zero.read_bytes()!=original: raise AssertionError('Zero lamp must preserve original bytes')
    checks.append(dict(name='zero byte identity',passed=True))
    def draw(name,shader,f,inputs,fmt='rgba32f',**kw):
        return render(shader,output/name,f['width'],f['height'],**inputs,target_format=fmt,**kw)[0,0]
    cases=[('white',{}),('skin-swatch',{'albedo':(.62,.34,.23)}),('blue',{'albedo':(.25,.35,.65)}),
           ('tilted-normal',{'normal_xy':(.7,.6)}),('alpha-half',{'alpha':.5}),('alpha-zero',{'alpha':0}),
           ('depth-rejected',{'depth':.4}),('metal',{'metal':1}),('wet',{'wetness':.6}),('exposure',{'exposure':1.5}),
           ('type1',{'material_type':1}),('type2',{'material_type':2}),('type3',{'material_type':3})]
    for name,settings in cases:
        f,inputs=fixture(compiler,output/(name+'-geometry'),**settings)
        base=draw(name+'-base',path,f,inputs);actual=draw(name+'-injected',lamp,f,inputs)
        # Native t0 lighting is multiplied by alignment to the shared G-buffer
        # normal. Undo it in the oracle INPUT only; candidate uses final normal
        # after that native correction and must not multiply it twice.
        alignment=-f['normal'][...,2]
        inputs['textures'][0][...,:3]+=(cpu_light(f)/alignment[...,None]).astype(np.float32)
        expected=draw(name+'-oracle',path,f,inputs)
        check(name+' native RGBA oracle',actual,expected)
        check(name+' alpha preserved',actual[...,3],base[...,3],0)
        if name in ('alpha-zero','depth-rejected'):
            check(name+' discarded output',actual,np.zeros_like(actual),0)
        elif name in ('white','skin-swatch','blue','tilted-normal','alpha-half','exposure'):
            analytic=np.sqrt(np.array(settings.get('albedo',(.8,.8,.8)))*(.25*alignment[...,None]+cpu_light(f)))*settings.get('exposure',1)
            check(name+' independent diffuse equation',actual[...,:3],analytic)
            check(name+' expected coverage alpha',actual[...,3],np.full(actual.shape[:2],settings.get('alpha',1)))
        print('PASS',name,flush=True)
    f,inputs=fixture(compiler,output/'controls-geometry')
    base=draw('controls-base',path,f,inputs)
    for name,pos,col,intensity,radius in [('left',(-2,0,1),(1,.8,.6),3,8),('right',(2,0,1),(.6,.8,1),3,8),
            ('behind',(0,0,7),(1,1,1),2,8),('out-of-range',(0,0,0),(1,1,1),2,1)]:
        candidate_path=candidate(name,pos,col,intensity,radius)
        actual=draw(name,candidate_path,f,inputs)
        analytic=np.sqrt(.8*(.25+cpu_light(f,pos,col,intensity,radius)))
        check(name+' lamp controls',actual[...,:3],analytic)
    # A perpendicular G-buffer normal must not suppress the new lamp, which
    # uses the final mesh normal after native alignment correction.
    side,side_inputs=fixture(compiler,output/'perpendicular-geometry',basis_angle=90)
    actual=draw('perpendicular-light',lamp,side,side_inputs)
    baseline=draw('perpendicular-base',path,side,side_inputs)
    check('zero alignment native baseline',baseline[...,:3],np.zeros_like(baseline[...,:3]),0)
    check('zero alignment new lamp survives',actual[...,:3],np.sqrt(.8*cpu_light(side)))
    if not np.any(actual[...,:3]>0): raise AssertionError('Lamp suppressed by old normal correction')
    mixed,mixed_inputs=fixture(compiler,output/'mixed-depth-geometry')
    mixed_inputs['textures'][2][:,:mixed['width']//2,0]=.4
    result=draw('mixed-depth',lamp,mixed,mixed_inputs)
    check('mixed depth rejected half',result[:,:mixed['width']//2],np.zeros_like(result[:,:mixed['width']//2]),0)
    check('mixed depth accepted half',result[:,mixed['width']//2:,:3],np.sqrt(.8*(.25+cpu_light(mixed)))[:,mixed['width']//2:])
    # Entire PS at nine baked positions. Separate jobs/devices demonstrate
    # spatial response, not a live in-game parameter controller.
    centroid=[]
    for i,x in enumerate(np.linspace(-3,3,9)):
        moving=candidate('moving-'+str(i),(float(x),0,1),intensity=12)
        actual=draw('moving-frame-'+str(i),moving,f,inputs)
        energy=cpu_light(f,(x,0,1),intensity=12)
        check('full material movement '+str(i),actual[...,:3],np.sqrt(.8*(.25+energy)))
        observed=(actual[...,:3]**2-base[...,:3]**2).mean(-1)
        centroid.append(float((observed*np.arange(f['width'])).sum()/observed.sum()))
    if not np.all(np.diff(centroid)>0): raise AssertionError('Full material highlight did not move monotonically')
    checks.append(dict(name='full material moving centroid',passed=True,pixels=centroid))
    # Final scene-format and alpha blend are actual hardware API operations,
    # synthetic state choices rather than recovered game blend descriptors.
    f,inputs=fixture(compiler,output/'blend-geometry',alpha=.5)
    source=draw('blend-source',lamp,f,inputs)
    blend=draw('blend-result',lamp,f,inputs,blend='source-alpha')
    check('alpha blend attenuates RGB',blend[...,:3],source[...,:3]*.5)
    fp16=draw('final-fp16',lamp,f,inputs,'rgba16f')
    # WARP conversion need not equal NumPy round-to-nearest. Bound actual
    # stored values by one representable step, including subnormal spacing.
    ulp=np.exp2(np.floor(np.log2(np.maximum(np.abs(source),2**-14)))-10)
    check('FP16 conversion error in ULP',np.abs(fp16-source)/ulp,np.zeros_like(source),1.001)
    report=dict(check_count=len(checks),all_passed=True,checks=checks,target=TARGET,original_sha256=digest(original),
        patched_sha256=digest(lamp.read_bytes()),game_runtime_verified=False,performance_verified=False,
        limits=['Synthetic plane VS; original game skinning/mesh rasterization not replayed',
                'One exact mesh-material PS, not all skin/hair/transparency variants',
                'LightingType numeric IDs do not establish material names',
                'Normal-alignment division belongs only to oracle fixture, never candidate',
                'Native shader discards tested; actual depth/stencil descriptors unknown',
                'Baked camera-relative lamp; no game control binding or occlusion'])
    (output/'report.json').write_bytes(encoded(report));print(json.dumps(dict(checks=len(checks),passed=True)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--extraction',type=Path,default=ROOT/'artifacts/client-2026.09.15')
    p.add_argument('--decompiler',type=Path,default=ROOT/'artifacts/decompiler/1.3.16/cmd_Decompiler.exe')
    a=p.parse_args();run(a.output,a.extraction,a.decompiler.resolve())
