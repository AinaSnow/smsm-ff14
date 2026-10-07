from pathlib import Path
import tempfile
import unittest
from record_validation import ROOT, summarize_frames


class FrameTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "artifacts", prefix="timing-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "frames.csv"

    def test_percentiles_process_filter_and_stutter_preserved(self):
        self.path.write_text("Application,MsBetweenPresents\nffxiv_dx11.exe,10\nffxiv_dx11.exe,20\nother.exe,1\nffxiv_dx11.exe,30\nffxiv_dx11.exe,1000\n")
        result = summarize_frames(self.path, "MsBetweenPresents", "ffxiv_dx11.exe")
        self.assertEqual(result["samples"], 4)
        self.assertEqual(result["filtered_other_process_rows"], 1)
        self.assertEqual(result["mean_ms"], 265)
        self.assertEqual(result["median_ms"], 25)
        self.assertAlmostEqual(result["p95_ms"], 854.5)
        self.assertAlmostEqual(result["p99_ms"], 970.9)
        self.assertEqual(result["max_ms"], 1000)

    def test_bad_values_not_silently_discarded(self):
        for value in ("0", "-1", "NaN", "inf", "bad", ""):
            self.path.write_text("frame_time_ms,other\n" + value + ",x\n")
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize_frames(self.path, "frame_time_ms")

    def test_wrong_column_and_empty_input(self):
        self.path.write_text("frame_time_ms\n")
        with self.assertRaisesRegex(ValueError, "No matching"):
            summarize_frames(self.path, "frame_time_ms")
        with self.assertRaisesRegex(ValueError, "Missing"):
            summarize_frames(self.path, "FPS")


if __name__ == "__main__":
    unittest.main()
