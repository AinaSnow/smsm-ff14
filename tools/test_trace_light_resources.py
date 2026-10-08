import unittest
from trace_light_resources import trace


class TraceTests(unittest.TestCase):
    def test_partial_binding_null_and_actual_shader_read(self):
        log=b"""000001 PSSetShader(p:0x1) hash=8b384acd7a03c836
000001 OMSetRenderTargets(NumViews:1)
       0: view=0x1 resource=0x11 hash=aaaaaaaa
000001 Draw(3,0)
000002 OMSetRenderTargets(NumViews:1)
       0: view=0x2 resource=0x22 hash=aaaaaaaa
000002 PSSetShader(p:0x2) hash=1111111111111111
000002 PSSetShaderResources(StartSlot:0, NumViews:2)
       0: view=0x3 resource=0x11 hash=aaaaaaaa
       1: view=0x3 resource=0x11 hash=aaaaaaaa
000002 Draw(3,0)
000003 PSSetShaderResources(StartSlot:1, NumViews:1)
000003 Draw(3,0)
"""
        report=trace(log,lambda h:{"read_slots":[1]})
        self.assertEqual([(e["draw"],e["slot"]) for e in report["direct_consumers"]],[(2,1)])
        self.assertEqual(report["direct_consumers"][0]["outputs"],{0:"0x22"})

    def test_resource_hash_not_identity_and_om_conflict(self):
        log=b"""000001 PSSetShader(p:0x1) hash=8b384acd7a03c836
000001 OMSetRenderTargets(NumViews:1)
       0: view=0x1 resource=0x11 hash=aaaaaaaa
000001 Draw(3,0)
000002 PSSetShaderResources(StartSlot:0, NumViews:2)
       0: view=0x1 resource=0x11 hash=aaaaaaaa
       1: view=0x2 resource=0x22 hash=aaaaaaaa
000002 PSSetShader(p:0x2) hash=1111111111111111
000002 Draw(3,0)
"""
        self.assertEqual(trace(log,lambda h:{"read_slots":[0,1]})["direct_consumers"],[])


if __name__=="__main__": unittest.main()
