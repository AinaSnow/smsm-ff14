import unittest
from audit_light_capture import audit


class CaptureTests(unittest.TestCase):
    def test_counts_draws_not_binds_and_snapshots_state(self):
        report=audit(b"000001 OMSetBlendState(pBlendState:0x1)\n"
                     b"000001 PSSetShader(pPixelShader:0x2) hash=8b384acd7a03c836\n"
                     b"000001 Draw(3,0)\n000002 DrawIndexed(6,0,0)\n"
                     b"000003 OMSetBlendState(pBlendState:0x3)\n"
                     b"000003 Draw(3,0)\n000004 PSSetShader(pPixelShader:0)\n000004 Draw(3,0)\n")
        self.assertEqual(report["draw_counts"]["8b384acd7a03c836"],3)
        self.assertIn("0x1",report["draws"][0]["state"]["blend_binding"]["text"])
        self.assertIn("0x3",report["draws"][2]["state"]["blend_binding"]["text"])
        self.assertFalse(report["per_pixel_injection_count_verified"])

    def test_unknown_context_does_not_reuse_old_shader(self):
        for operation in ("ClearState", "ExecuteCommandList", "SwapDeviceContextState"):
            with self.subTest(operation=operation):
                raw=("000001 PSSetShader(pPixelShader:0x2) hash=e9f57e0834b642f5\n"
                     f"000001 {operation}()\n000002 Draw(3,0)\n").encode()
                self.assertEqual(audit(raw)["draws"],[])


if __name__=="__main__":
    unittest.main()
