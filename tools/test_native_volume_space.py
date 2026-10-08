import struct
import unittest
import numpy as np
from audit_native_volume_space import decode_regions, compare


class VolumeSpaceTests(unittest.TestCase):
    def test_known_world_region_stays_fixed_when_camera_rotates_and_translates(self):
        world_region = np.array([[.2, 0, 0, -3], [0, .5, 0, 4], [0, 0, .1, -2.]])
        first = np.eye(4)
        second = np.array([[0, 0, 1, 17], [0, 1, 0, -3], [-1, 0, 0, 8], [0, 0, 0, 1.]])
        def region(camera):
            return {"type": 3, "signature": np.zeros(8), "view_to_region": world_region @ camera,
                    "sh": np.zeros((3, 4)), "color": np.zeros(3)}
        row = compare(([region(first)], first), ([region(second)], second))["entries"][0]
        self.assertGreater(row["view_matrix_max_delta"], 1)
        self.assertLess(row["world_reference_max_delta"], 1e-12)

    def test_camera_following_region_is_not_reported_as_world_fixed(self):
        region = {"type": 2, "signature": np.zeros(8), "view_to_region": np.eye(4)[:3], "sh": np.zeros((3, 4)), "color": np.zeros(3)}
        camera = np.eye(4); camera[0, 3] = 10
        row = compare(([region], np.eye(4)), ([region], camera))["entries"][0]
        self.assertEqual(row["world_reference_max_delta"], 10)

    def test_global_unused_matrix_and_buffer_bounds(self):
        raw = bytearray(64 + 192)
        struct.pack_into("<I", raw, 0, 1)
        struct.pack_into("<12f", raw, 160, *([float('nan')] * 12))
        regions = decode_regions(raw, 0, 16)
        self.assertEqual(compare((regions, np.eye(4)), (regions, np.eye(4)))["entries"][0]["status"], "global_region_matrix_unused_by_shader")
        with self.assertRaises(ValueError): decode_regions(raw, 0, 15)
        struct.pack_into("<I", raw, 0, 65)
        with self.assertRaises(ValueError): decode_regions(raw, 0, 16)


if __name__ == "__main__": unittest.main()
