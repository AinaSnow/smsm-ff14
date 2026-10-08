"""Offline mesh ambient replacement with explicit new CBs; original instructions are preserved."""
import ctypes as ct
import re
from manage_preview import ROOT, digest
from patch_material_light import load_original
from patch_shader_asm import assemble, disassemble_exact, instructions, temp_count
from shader_compile import blob_bytes

TARGET = "980154264a89fba1"
ANCHOR = "mul r8.xyz, r8.xyzx, cb6[3].wwww"
VARIANTS = {
    TARGET:dict(ambient='r8',normal='r1',resource=12),
    '1c5c89ac035f9a44':dict(ambient='r6',normal='r9',resource=14),
    'e86f0d4916054deb':dict(ambient='r8',normal='r9',resource=14),
}


def strip_reflection(data):
    # New t12/b8 declarations must not carry stale copied RDEF resource metadata.
    dll = ct.WinDLL("d3dcompiler_47.dll")
    dll.D3DStripShader.argtypes = [ct.c_void_p,ct.c_size_t,ct.c_uint,ct.POINTER(ct.c_void_p)]
    dll.D3DStripShader.restype = ct.c_int32
    result=ct.c_void_p()
    hr=dll.D3DStripShader(data,len(data),1,ct.byref(result))
    if hr<0: raise RuntimeError("D3DStripShader failed")
    stripped=blob_bytes(result)
    if instructions(stripped)!=instructions(data): raise ValueError("Reflection stripping changed instructions")
    return stripped


def build(extraction, output, compiler, decompiler, target=TARGET):
    if target not in VARIANTS:raise ValueError('Unreviewed ambient material target')
    spec=VARIANTS[target];ambient,normal,slot=spec['ambient'],spec['normal'],spec['resource']
    anchor=f'mul {ambient}.xyz, {ambient}.xyzx, cb6[3].wwww'
    output.mkdir(parents=True,exist_ok=False)
    original=load_original(extraction,target)
    original_path=output/'original.bin';original_path.write_bytes(original)
    base=disassemble_exact(decompiler,original_path)
    if instructions(assemble(decompiler,original_path.with_suffix('.asm'),original_path))!=instructions(original):
        raise ValueError('Original instruction roundtrip changed')
    helper,warnings=compiler.compile(ROOT/'tools/patches/native_ambient_surface.hlsl',flags=0)
    if warnings: raise ValueError(warnings)
    helper_path=output/'helper.bin';helper_path.write_bytes(helper)
    text=disassemble_exact(decompiler,helper_path)
    declarations=[line for line in text.splitlines() if line.startswith('dcl_')]
    cbs={int(a):int(b) for a,b in re.findall(r'dcl_constantbuffer cb(\d+)\[(\d+)\]',text)}
    if cbs!={8:1}: raise ValueError('Unexpected helper constant bindings')
    resources=re.findall(r'^dcl_resource.*$',text,re.M)
    if resources!=['dcl_resource_structured t12, 16'] or re.search(r'^dcl_(?:sampler|indexableTemp)',text,re.M):
        raise ValueError('Unreviewed helper resources/indexed temps')
    if re.search(r'\bcb8\[|\bt'+str(slot)+r'\b',base): raise ValueError('Host already uses requested binding slots')
    # Explicitly anchor to the exact normal used by this original SH term.
    expected='\n'.join(f'dp4_sat {ambient}.{c}, {normal}.xyzw, cb6[{i}].xyzw' for i,c in enumerate('xyz'))+'\n'+anchor
    if expected not in base:raise ValueError('Native SH normal/term changed')
    inputs=re.findall(r'^dcl_input_ps linear (v\d+)\.xyz$',text,re.M)
    if inputs!=['v0','v1'] or len(re.findall(r'^dcl_input',text,re.M))!=2: raise ValueError('Unexpected helper inputs')
    lines=text.splitlines();start=max(i for i,line in enumerate(lines) if line.startswith('dcl_'))+1
    body='\n'.join(line for line in lines[start:] if line.strip() and not line.startswith('//'))
    if body.splitlines().count('ret')!=1 or not body.endswith('ret') or re.search(r'\b(?:retc|discard)\w*',body):
        raise ValueError('Unexpected helper exit/control flow')
    old_temps,helper_temps=temp_count(base),temp_count(text)
    result=f'r{old_temps+helper_temps}'
    body=re.sub(r'\br(\d+)\b',lambda m:f'r{old_temps+int(m[1])}',body.removesuffix('ret').rstrip())
    body=re.sub(r'\bo0\b',result,body)
    body=re.sub(r'\bv[01]\b',lambda m:{'v0':normal,'v1':'v6'}[m[0]],body)
    body=re.sub(r'\bt12\b','t'+str(slot),body)
    insertion='\n// NATIVE AMBIENT SURFACE BEGIN\n'+body+f'\nadd {result}.xyz, {result}.xyzx, -{ambient}.xyzx\nmad {ambient}.xyz, {result}.wwww, {result}.xyzx, {ambient}.xyzx\n// NATIVE AMBIENT SURFACE END'
    if base.count(anchor)!=1: raise ValueError('Ambient replacement anchor changed')
    added='\n'.join(line for line in declarations if line.startswith(('dcl_constantbuffer','dcl_resource')))+'\n'
    added=re.sub(r'\bt12\b','t'+str(slot),added)
    modified=base.replace(anchor,anchor+insertion)
    modified=modified.replace('dcl_temps '+str(old_temps),added+'dcl_temps '+str(old_temps+helper_temps+1),1)
    restored=modified.replace(insertion,'').replace(added,'').replace('dcl_temps '+str(old_temps+helper_temps+1),'dcl_temps '+str(old_temps),1)
    if restored!=base: raise ValueError('Original code changed outside bounded insertion')
    source=output/'native-ambient.asm';source.write_text(modified)
    data=strip_reflection(assemble(decompiler,source,original_path))
    path=output/'native-ambient.bin';path.write_bytes(data)
    check=disassemble_exact(decompiler,path)
    if instructions(assemble(decompiler,path.with_suffix('.asm'),path))!=instructions(data): raise ValueError('Patched roundtrip mismatch')
    return path, {'target':target,'original_sha256':digest(original),'candidate_sha256':digest(data),
                  'normal_register':normal,'ambient_register':ambient,'resource_slot':slot,
                  'added_constants':{'b8':1},'added_structured_resources':{'t'+str(slot):16},'native_region_layout_vectors':772,
                  'helper_compile_flags':0,'reflection':'RDEF removed; I/O signatures and instructions retained',
                  'scope':'replace diffuse SH only before native depth attenuation; not exact full background ambient migration',
                  'game_binding_verified':False,'default_enabled':False}
