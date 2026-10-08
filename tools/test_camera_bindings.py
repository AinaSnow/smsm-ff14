"""State-loss and stale-binding regression tests for the projection audit."""
import unittest
from audit_camera_bindings import audit


class CameraAuditTests(unittest.TestCase):
    def rows(self, text):
        return audit(('000001 PSSetShader(x) hash=415a922293923fa4\n'+text).encode())['draws']

    def test_partial_range_and_null_clear(self):
        rows=self.rows('000001 PSSetConstantBuffers(StartSlot:0, NumBuffers:3)\n'
            '  0: resource=0x10\n  1: resource=0x11\n  2: resource=0x12\n'
            '000001 Draw(x)\n000002 PSSetConstantBuffers(StartSlot:1, NumBuffers:1)\n'
            '000002 Draw(x)\n000003 PSSetConstantBuffers(StartSlot:2, NumBuffers:1)\n'
            '  2: resource=0x22\n000003 Draw(x)\n')
        self.assertEqual(set(rows[0]['buffers']['PS']),{0,1,2})
        self.assertEqual(set(rows[1]['buffers']['PS']),{0,2})
        self.assertEqual(rows[2]['buffers']['PS'][2]['resource'],'0x22')
        self.assertEqual(rows[0]['buffers']['PS'][2]['resource'],'0x12')

    def test_stage_independence_and_ranged_binding_unknown(self):
        rows=self.rows('000001 PSSetConstantBuffers(StartSlot:1, NumBuffers:1)\n  1: resource=0x11\n'
            '000001 VSSetConstantBuffers(StartSlot:1, NumBuffers:1)\n  1: resource=0x22\n'
            '000001 Draw(x)\n000002 PSSetConstantBuffers1(StartSlot:1, NumBuffers:1)\n'
            '  1: resource=0x33\n000002 Draw(x)\n')
        self.assertEqual(rows[0]['buffers']['PS'][1]['resource'],'0x11')
        self.assertEqual(rows[0]['buffers']['VS'][1]['resource'],'0x22')
        self.assertEqual(rows[1]['buffers']['PS'],{})
        self.assertEqual(rows[1]['buffers']['VS'][1]['resource'],'0x22')

    def test_context_state_loss(self):
        for call in ('ClearState','ExecuteCommandList','SwapDeviceContextState'):
            rows=self.rows('000001 PSSetConstantBuffers(StartSlot:1, NumBuffers:1)\n  1: resource=0x11\n'
                '000001 RSSetViewports(NumViewports:1, pViewports:0x12)\n000001 Draw(x)\n'
                f'000002 {call}()\n000002 Draw(x)\n'
                '000003 PSSetShader(x) hash=415a922293923fa4\n000003 Draw(x)\n')
            self.assertEqual([r['draw'] for r in rows],[1,3])
            self.assertEqual(rows[1]['buffers']['PS'],{})
            self.assertIsNone(rows[1]['viewport'])

    def test_write_history_and_unmodeled_dispatch(self):
        rows=self.rows('000001 PSSetConstantBuffers(StartSlot:1, NumBuffers:1)\n  1: resource=0x11\n'
            '000001 Draw(x)\n000002 Map(pResource:0x11)\n000002 Unmap(pResource:0x11)\n'
            '000002 Draw(x)\n000003 CopyResource(pDstResource:0x11, pSrcResource:0x22)\n'
            '000003 Draw(x)\n000004 Dispatch(x)\n000004 Draw(x)\n')
        states=[r['buffers']['PS'][1] for r in rows]
        self.assertIsNone(states[0]['last_possible_write'])
        self.assertEqual(states[1]['last_possible_write']['call'],'Unmap')
        self.assertEqual(states[2]['last_possible_write']['call'],'CopyResource')
        self.assertGreater(states[3]['content_epoch'],states[2]['content_epoch'])

    def test_srv_hazard_and_viewport_not_inferred(self):
        rows=self.rows('000001 PSSetShaderResources(StartSlot:5, NumViews:6)\n'
            '  5: view=0x50 resource=0x55\n  10: view=0x100 resource=0x110\n'
            '000001 RSSetViewports(NumViewports:1, pViewports:0x12)\n000001 Draw(x)\n'
            '000002 OMSetRenderTargets(NumViews:1)\n  0: resource=0x110\n000002 Draw(x)\n'
            '000003 PSSetShaderResources(StartSlot:5, NumViews:1)\n000003 Draw(x)\n')
        self.assertEqual(set(rows[0]['srvs']),{5,10})
        self.assertEqual(set(rows[1]['srvs']),{5})
        self.assertEqual(rows[2]['srvs'],{})
        self.assertFalse(rows[0]['viewport']['numeric_values_verified'])


if __name__=='__main__':unittest.main()
