"""Review-bundle isolation and default-off guards; not a native INI parser test."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from manage_preview import ROOT, digest, read_package
from prepare_capture_audit import build, fragment, TARGETS


class CaptureReviewTests(unittest.TestCase):
    def test_default_off_and_bounded_targeted_commands(self):
        for name, target in TARGETS.items():
            lines=[s.strip() for s in fragment(name,target).splitlines() if s.strip() and not s.lstrip().startswith(';')]
            self.assertIn('global $smsm_capture_arm = 0',lines)
            self.assertIn(f'if frame_analysis && $smsm_capture_arm == 1 && $smsm_capture_{name} < 2',lines)
            self.assertIn(f'post $smsm_capture_{name} = 0',lines)
            self.assertFalse(any(s.startswith('analyse_frame') for s in lines))
            self.assertIn('analyse_options = buf dds mono',lines)
            dumps=[s for s in lines if s.startswith('pre dump =')]
            self.assertEqual({s.split()[-1] for s in dumps},set(target['resources']))
            self.assertEqual(len(dumps),len(target['resources']))
            self.assertFalse(any(token in '\n'.join(lines) for token in ('hold','deferred_ctx','clear_rt','ini_params','handling','run =')))

    def test_immutable_output_and_baseline_unchanged(self):
        baseline=ROOT/'artifacts/preview-2026.09.15-r10-managed'
        _,before=read_package(baseline)
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts',prefix='capture-review-test-') as tmp, contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(Path(tmp).resolve().is_relative_to((ROOT/'artifacts').resolve()))
            output=Path(tmp)/'review'
            result=build(output,baseline,ROOT/'artifacts/camera-binding-audit-v2/report.json')
            self.assertFalse(result['installable']);self.assertFalse(result['default_enabled'])
            self.assertFalse(result['native_ini_parser_tested'])
            self.assertEqual({p.name for p in output.iterdir()}, {'review.json','mesh.ini.disabled','fullscreen.ini.disabled'})
            self.assertEqual(json.loads((output/'review.json').read_text())['files'],result['files'])
            for filename,value in result['files'].items():self.assertEqual(digest((output/filename).read_bytes()),value)
            with self.assertRaises(FileExistsError):build(output,baseline,ROOT/'artifacts/camera-binding-audit-v2/report.json')
        _,after=read_package(baseline)
        self.assertEqual(before,after)

    def test_cannot_write_inside_baseline(self):
        baseline=ROOT/'artifacts/preview-2026.09.15-r10-managed'
        with self.assertRaisesRegex(ValueError,'immutable baseline'):
            build(baseline/'capture-forbidden',baseline,ROOT/'artifacts/camera-binding-audit-v2/report.json')


if __name__=='__main__':unittest.main()
