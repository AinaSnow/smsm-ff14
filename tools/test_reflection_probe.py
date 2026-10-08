"""Verify the real compiled probe and reject unsupported original shader exits."""
import unittest

from build_reflection_probe import TARGET, SAMPLE, CONTRIBUTION_MARKER, append_marker, check_instruction_delta
from manage_preview import ROOT, read_package
from shader_compile import Compiler

BASE = ROOT / "artifacts/preview-2026.09.15-r10-managed"
PROBE = ROOT / "artifacts/diagnostic-2026.09.15-reflection-marker"
CONTRIBUTION = ROOT / "artifacts/diagnostic-2026.09.15-reflection-contribution"


class ProbeTests(unittest.TestCase):
    def test_probe_changes_only_target_pair(self):
        base, _ = read_package(BASE)
        probe, _ = read_package(PROBE)
        self.assertEqual(base["files"].keys(), probe["files"].keys())
        changed = {n for n in base["files"] if base["files"][n] != probe["files"][n]}
        self.assertEqual(changed, {f"SMSM-ShaderFixes/{TARGET}-ps.{extension}" for extension in ("txt", "bin")})
        self.assertEqual(probe["default_profile"], "daily")
        self.assertEqual(probe["profiles"]["daily"], ["tone"])
        self.assertFalse(probe["diagnostic"]["quality_test"])

    def test_compiled_marker_and_original_instruction_preservation(self):
        original = (PROBE / "build-audit" / TARGET / "original.bin").read_bytes()
        binary = (PROBE / "SMSM-ShaderFixes" / f"{TARGET}-ps.bin").read_bytes()
        check_instruction_delta(original, binary)
        asm = Compiler(ROOT / "d3dcompiler_46.dll").disassemble(binary)
        lines = [line.strip() for line in asm.splitlines() if line.strip() and not line.startswith("//")]
        self.assertEqual(lines[-2:], ["mov o0.xyzw, l(1.000000,0,1.000000,1.000000)", "ret"])
        # An extra earlier instruction must be rejected, even if final output agrees.
        with self.assertRaises(ValueError):
            check_instruction_delta(binary, binary)

    def test_unsupported_exits_rejected(self):
        sample = "ps_5_0\nmov o0.w, r0.w\nret\n"
        for changed in (sample + "ret\n", sample.replace("ret", "retc_nz r0.x"),
                        sample.replace("mov o0.w", "discard_nz r0.x\nmov o0.w"),
                        sample.replace("r0.w", "r1.w")):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                append_marker(changed)

    def test_contribution_preserves_weighting_alpha_and_all_original_instructions(self):
        original = (CONTRIBUTION / "build-audit" / TARGET / "original.bin").read_bytes()
        binary = (CONTRIBUTION / "SMSM-ShaderFixes" / f"{TARGET}-ps.bin").read_bytes()
        check_instruction_delta(original, binary, "contribution")
        source = (CONTRIBUTION / "SMSM-ShaderFixes" / f"{TARGET}-ps.txt").read_text()
        self.assertIn(CONTRIBUTION_MARKER + "\nmul r0.xyz, r0.xyzx, r1.xyzx", source)
        self.assertIn("mov o0.w, r0.w\nret", source)
        asm = Compiler(ROOT / "d3dcompiler_46.dll").disassemble(binary)
        self.assertIn("mov r0.xyz, l(1.000000,0,1.000000,0)\nmul r0.xyz, r0.xyzx, r1.xyzx", asm)
        base, _ = read_package(BASE)
        probe, _ = read_package(CONTRIBUTION)
        changed = {n for n in base["files"] if base["files"][n] != probe["files"][n]}
        self.assertEqual(changed, {f"SMSM-ShaderFixes/{TARGET}-ps.{extension}" for extension in ("txt", "bin")})
        self.assertFalse(probe["diagnostic"]["forces_alpha_and_bypasses_hit_fades"])
        self.assertTrue(probe["diagnostic"]["preserves_original_weights_and_alpha"])

    def test_contribution_requires_exact_sample_anchor(self):
        sample = "ps_5_0\n" + SAMPLE + "\nmul r0.xyz, r0.xyzx, r1.xyzx\nmov o0.w, r0.w\nret\n"
        duplicate = sample.replace(SAMPLE, SAMPLE + "\nmul r0.xyz, r0.xyzx, r1.xyzx\n" + SAMPLE)
        for bad in (sample.replace("r1.xyzx", "r2.xyzx"), duplicate):
            with self.assertRaisesRegex(ValueError, "contribution anchor"):
                append_marker(bad, "contribution")


if __name__ == "__main__":
    unittest.main()
