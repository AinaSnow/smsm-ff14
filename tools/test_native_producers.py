import unittest
from audit_native_producers import audit


class ProducerHistoryTests(unittest.TestCase):
    def capture(self, middle="", resource="0x1"):
        return audit(("000001 PSSetShader() hash=1111111111111111\n"
                      "000001 OMSetRenderTargets(NumViews:1)\n 0: resource=0x1\n"
                      "000001 Draw(VertexCount:3)\n" + middle +
                      "000005 OMSetRenderTargets(NumViews:0)\n"
                      "000005 PSSetShader() hash=415a922293923fa4\n"
                      "000005 PSSetShaderResources(StartSlot:10, NumViews:1)\n 10: resource=" + resource + "\n"
                      "000005 Draw(VertexCount:3)\n").encode())["targets"][0]["inputs"][10]

    def test_copy_freezes_source_before_later_write(self):
        result = self.capture("000002 CopyResource(pDstResource:0x2, pSrcResource:0x1)\n"
                              "000003 PSSetShader() hash=2222222222222222\n000003 Draw(VertexCount:3)\n", "0x2")
        self.assertEqual(result["last_observed_write"]["source_writer_at_copy"]["ps"], "1111111111111111")

    def test_compute_only_invalidates_its_bound_destination(self):
        middle = "000002 CSSetShader() hash=3333333333333333\n000002 CSSetUnorderedAccessViews(StartSlot:0, NumUAVs:1)\n 0: resource=0x2\n000002 Dispatch()\n000003 CSSetUnorderedAccessViews(StartSlot:0, NumUAVs:1)\n"
        self.assertEqual(self.capture(middle)["last_observed_write"]["ps"], "1111111111111111")
        self.assertEqual(self.capture(middle, "0x2")["last_observed_write"]["cs"], "3333333333333333")

    def test_context_execution_drops_stale_writer(self):
        self.assertIsNone(self.capture("000002 ExecuteCommandList()\n")["last_observed_write"])

    def test_null_binding_does_not_keep_previous_resource(self):
        text = "000001 PSSetShader() hash=415a922293923fa4\n000001 PSSetShaderResources(StartSlot:10, NumViews:1)\n 10: resource=0x1\n000002 PSSetShaderResources(StartSlot:10, NumViews:1)\n000003 Draw()\n"
        self.assertIsNone(audit(text.encode())["targets"][0]["inputs"][10]["resource"])


if __name__ == "__main__":
    unittest.main()
