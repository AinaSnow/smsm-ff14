"""Check tone-curve endpoint equivalence and the public Bloom switch on compiled DXBC."""
from pathlib import Path
import re
import shutil
import uuid
from shader_compile import Compiler
from patch_shader_asm import instructions
from build_preview import bindings, insert_section

ROOT = Path(__file__).resolve().parents[1]


def main():
    template = (ROOT / "d3dx.ini").read_text()
    configured = insert_section(template, "Constants", "y = 1")
    configured = insert_section(configured, "Present", "post x = 0")
    section = None
    inserted = []
    for line in configured.splitlines():
        if line.startswith("["):
            section = line.strip()
        if line.strip() in ("y = 1", "post x = 0"):
            inserted.append((section, line.strip()))
    assert inserted == [("[Constants]", "y = 1"), ("[Present]", "post x = 0")], "INI commands must not be inserted into comments/other sections"
    output = ROOT / "artifacts" / ("calibration-test-" + uuid.uuid4().hex)
    compiler = Compiler(ROOT / "d3dcompiler_46.dll")

    def compile_case(name, shader, settings, use_original_entry=False):
        directory = output / name
        directory.mkdir(parents=True)
        for header in (ROOT / "ShaderFixes").glob("*.h"):
            shutil.copy2(header, directory / header.name)
        config_path = directory / "Configuration.h"
        config = config_path.read_text()
        for key, value in settings.items():
            config, count = re.subn(r"(#define\s+" + key + r"\s+)\d+", lambda m: m[1] + str(value), config)
            if count != 1:
                raise AssertionError(f"Missing configuration: {key}")
        config_path.write_text(config)
        source = (ROOT / "ShaderFixes" / f"{shader}-ps_replace.txt").read_text()
        if use_original_entry:
            source = re.sub(r"void main\(", "void unused_main(", source, count=1)
            source = re.sub(r"void orig\(", "void main(", source, count=1)
        path = directory / "shader.txt"
        path.write_text(source)
        data, diagnostics = compiler.compile(path)
        (directory / "shader.bin").write_bytes(data)
        (directory / "compiler.log").write_text(diagnostics)
        return instructions(data)

    tone = "72a656dfd52149ad"
    zero = compile_case("zero", tone, {"TONEMAP_SMSM_PERCENT": 0})
    vanilla = compile_case("vanilla", tone, {"TONEMAP_VANILLA": 1})
    full = compile_case("full", tone, {"TONEMAP_SMSM_PERCENT": 100})
    quarter = compile_case("quarter", tone, {"TONEMAP_SMSM_PERCENT": 25})
    assert zero == vanilla, "0% must preserve the vanilla shader's instruction bytes"
    assert full == instructions((ROOT / f"ShaderFixes/{tone}-ps_replace.bin").read_bytes()), "100% must retain the shipped SMSM curve"
    assert quarter not in (zero, full), "25% must not collapse to either endpoint"
    quarter_bindings = bindings(compiler.disassemble((output / "quarter/shader.bin").read_bytes()))
    assert ("texture", 120) not in quarter_bindings, "Static blend must not depend on runtime IniParams"
    assert quarter_bindings[("texture", 1)] == ("float4", "2d", 1), "Static blend must retain the game tone LUT"
    assert ("sampler", 1) in quarter_bindings, "Game tone LUT sampler must remain bound"
    bloom = "a617dec7fe8f1603"
    enabled = compile_case("bloom-on", bloom, {"UseOriginalWhitening": 1})
    disabled = compile_case("bloom-off", bloom, {"UseOriginalWhitening": 0})
    original = compile_case("bloom-original", bloom, {}, use_original_entry=True)
    assert enabled == original, "Public Bloom switch must select original merge instructions"
    assert enabled != disabled, "Public Bloom switch must change compiled shader behavior"
    print("PASS: 0% equals vanilla, 100% equals SMSM, 25% blends, Bloom switch selects original merge")
    print(output)


if __name__ == "__main__":
    main()
