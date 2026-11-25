import tempfile
import unittest
from collections import namedtuple
from unittest import mock

from abxr.disk_space import (
    GB,
    SPACE_HEADROOM_BYTES,
    NotEnoughSpaceError,
    check_headset_space,
    computer_space_message,
    format_size,
    headset_space_needed,
    parse_df_available_bytes,
    require_free_space,
    temp_space_plan,
)

Usage = namedtuple("Usage", "total used free")

QUEST_DF = """Filesystem     1K-blocks    Used Available Use% Mounted on
/dev/fuse      110867720 9083372 101784348   9% /storage/emulated
"""

WRAPPED_DF = """Filesystem                              1K-blocks    Used Available Use% Mounted on
/dev/block/by-name/userdata-with-a-long-name
                                        110867720 9083372 101784348   9% /data
"""


class ParseDfTest(unittest.TestCase):
    def test_reads_available_kilobytes(self):
        self.assertEqual(parse_df_available_bytes(QUEST_DF), 101784348 * 1024)

    def test_reads_a_filesystem_name_on_its_own_line(self):
        self.assertEqual(parse_df_available_bytes(WRAPPED_DF), 101784348 * 1024)

    def test_unreadable_output_is_none(self):
        self.assertIsNone(parse_df_available_bytes(""))
        self.assertIsNone(parse_df_available_bytes("Filesystem 1K-blocks Used Available Use% Mounted on\n"))
        self.assertIsNone(parse_df_available_bytes("df: /sdcard: No such file or directory\nsomething else\n"))


class HeadsetSpaceTest(unittest.TestCase):
    def test_needs_content_plus_margin_and_headroom(self):
        self.assertEqual(headset_space_needed(100 * GB), int(105 * GB) + SPACE_HEADROOM_BYTES)

    def test_enough_space_passes(self):
        check_headset_space(free_bytes=110 * GB, content_bytes=100 * GB)

    def test_too_little_space_says_how_much(self):
        with self.assertRaises(NotEnoughSpaceError) as raised:
            check_headset_space(free_bytes=61 * GB, content_bytes=70 * GB)
        self.assertEqual(raised.exception.short, "Headset full")
        self.assertIn("74.5 GB", str(raised.exception))
        self.assertIn("61.0 GB free", str(raised.exception))
        self.assertIn("--skip-space-check", str(raised.exception))


class ComputerSpaceTest(unittest.TestCase):
    def test_enough_for_every_headset_at_once(self):
        self.assertEqual(temp_space_plan(50 * GB, 5 * GB, 8), (True, 8))
        self.assertIsNone(computer_space_message("p.zip", 50 * GB, 5 * GB, 8, "/tmp"))

    def test_too_little_says_how_many_fit(self):
        self.assertEqual(temp_space_plan(21 * GB, 5 * GB, 8), (False, 4))
        lines = computer_space_message("p.zip", 21 * GB, 5 * GB, 8, "/tmp")
        self.assertIn("41.0 GB", lines[0])
        self.assertIn("21.0 GB free", lines[0])
        self.assertIn("Running 4 at a time", lines[1])
        self.assertIn("TMPDIR", lines[-1])

    def test_not_even_one_fits(self):
        self.assertEqual(temp_space_plan(3 * GB, 5 * GB, 8), (False, 0))
        lines = computer_space_message("p.zip", 3 * GB, 5 * GB, 8, "/tmp")
        self.assertIn("can't start", lines[1])

    def test_an_empty_package_needs_only_the_headroom(self):
        self.assertEqual(temp_space_plan(2 * GB, 0, 8), (True, 8))
        self.assertEqual(temp_space_plan(GB // 2, 0, 8), (False, 0))

    def test_require_free_space(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("abxr.disk_space.shutil.disk_usage", return_value=Usage(0, 0, 10 * GB)):
                require_free_space(directory, 8 * GB, "copy a file")
                with self.assertRaises(NotEnoughSpaceError) as raised:
                    require_free_space(directory, 9 * GB + 1, "copy a file")
        self.assertEqual(raised.exception.short, "PC disk full")
        self.assertIn("copy a file", str(raised.exception))

    def test_format_size(self):
        self.assertEqual(format_size(int(72.4 * GB)), "72.4 GB")


if __name__ == "__main__":
    unittest.main()
