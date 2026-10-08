"""Audited single-target diffuse-sample injection, retaining native material logic."""
import json
import re
from pathlib import Path
from build_preview import BUILD, bindings, verify_interface
from build_single_light import validate_settings
from manage_preview import ROOT, digest
from patch_shader_asm import assemble, disassemble_exact, instructions, temp_count

TARGET="415a922293923fa4"
ANCHOR="sample_indexable(texture2d)(float,float,float,float) r9.yzw, r0.xyxx, t3.wxyz, s2"


def load_original(extraction,target=TARGET,profile="ps_5_0"):
    manifest=json.loads((extraction/"manifest.json").read_text())
    if manifest["ClientBuild"]!=BUILD: raise ValueError("Unreviewed client build")
    row=next(r for r in manifest["Shaders"] if r["Hash"]==target and r["Profile"]==profile)
    path=(extraction/row["File"]).resolve(strict=True)
    if not path.is_relative_to(extraction.resolve()): raise ValueError("Extraction path escapes root")
    data=path.read_bytes(); value=0
    for byte in data: value=((value*0x100000001b3)&0xffffffffffffffff)^byte
    if digest(data)!=row["Sha256"] or f"{value:016x}"!=target: raise ValueError("Original integrity mismatch")
    return data


def compile_helper(work,compiler,position=(0,0,0),color=(1,1,1),intensity=2,radius=8):
    validate_settings(position,color,intensity,radius); work.mkdir(parents=True,exist_ok=True)
    fmt=lambda values:", ".join(format(float(v),".9g") for v in values)
    (work/"single_light_parameters.h").write_text(
        "static const float4 lampPositionRange=float4("+fmt([*position,radius])+");\n"+
        "static const float4 lampColorIntensity=float4("+fmt([*color,intensity])+");\n")
    source=work/"material_light.hlsl"
    source.write_text("#define SINGLE_LIGHT_BAKED 1\n"+(ROOT/"tools/patches/material_light.hlsl").read_text())
    data,warnings=compiler.compile(source)
    if warnings: raise ValueError(warnings)
    return data


def patch(original,helper,work,decompiler,compiler,*,target=TARGET,anchor=ANCHOR,
          add_template="add r9.yzw, r9.yyzw, {result}.xxyz",input_remap=None):
    work.mkdir(parents=True,exist_ok=True)
    path=work/"original.bin"; path.write_bytes(original)
    base=disassemble_exact(decompiler,path)
    if instructions(assemble(decompiler,path.with_suffix(".asm"),path))!=instructions(original):
        raise ValueError("Original instruction roundtrip changed")
    helper_path=work/"helper.bin"; helper_path.write_bytes(helper)
    helper_asm=disassemble_exact(decompiler,helper_path); compiled=compiler.disassemble(helper)
    ops=[s.strip() for s in compiled.splitlines() if s.strip() and not s.startswith(("//","dcl_")) and s.strip()!="ps_5_0"]
    source=work/f"{target}-ps.txt"
    if ops==["mov o0.xyzw, l(0,0,0,0)","ret"]:
        source.write_text(base); return source,original
    allowed=bindings(compiler.disassemble(original))
    if "// Resource Bindings:" in compiled:
        helper_bindings=bindings(compiled)
    else:
        if re.search(r"^dcl_(?:resource|constantbuffer|sampler)",compiled,re.M):
            raise ValueError("Missing helper resource reflection")
        helper_bindings={}
    if any(allowed.get(k)!=v for k,v in helper_bindings.items()): raise ValueError("Unbound helper resource")
    sizes=lambda s:{int(a):int(b) for a,b in re.findall(r"dcl_constantbuffer cb(\d+)\[(\d+)\]",s)}
    if any(n>sizes(base).get(k,0) for k,n in sizes(helper_asm).items()): raise ValueError("Constant range exceeds host")
    lines=helper_asm.splitlines(); start=max(i for i,s in enumerate(lines) if s.startswith("dcl_"))+1
    body="\n".join(s for s in lines[start:] if s.strip() and not s.startswith("//"))
    if body.splitlines().count("ret")!=1 or not body.endswith("ret") or re.search(r"\b(?:retc\w*|discard\w*)\b|\bx\d+\[",body):
        raise ValueError("Unreviewed helper control flow or indexed temps")
    count,hcount=temp_count(base),temp_count(helper_asm); result=f"r{count+hcount}"
    body=re.sub(r"\br(\d+)\b",lambda m:f"r{int(m[1])+count}",body.removesuffix("ret").rstrip())
    body=re.sub(r"\bo0\b",result,body)
    if input_remap is not None:
        inputs=re.findall(r"^dcl_input_ps linear (v\d+)\.xyz$",helper_asm,re.M)
        if set(inputs)!=set(input_remap) or len(re.findall(r"^dcl_input",helper_asm,re.M))!=len(inputs):
            raise ValueError("Unreviewed helper inputs")
        # Map only after remapping helper temporaries: host r1 must stay r1.
        body=re.sub(r"\bv\d+\b",lambda m:input_remap[m[0]],body)
    if base.count(anchor)!=1: raise ValueError("Unreviewed material anchor")
    # yzw of t3.wxyz is RGB. Preserve the host swizzle and all native processing.
    addition="\n// MATERIAL LIGHT BEGIN\n"+body+"\n"+add_template.format(result=result)+"\n// MATERIAL LIGHT END"
    modified=base.replace(anchor,anchor+addition)
    modified=re.sub(r"^dcl_temps \d+$",f"dcl_temps {count+hcount+1}",modified,count=1,flags=re.M)
    restored=re.sub(r"^dcl_temps \d+$",f"dcl_temps {count}",modified.replace(addition,""),count=1,flags=re.M)
    if restored!=base: raise ValueError("Changed native instructions outside injection")
    source.write_text(modified); data=assemble(decompiler,source,path)
    verify_interface(compiler.disassemble(original),compiler.disassemble(data))
    return source,data
