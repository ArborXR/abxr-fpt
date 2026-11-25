import unittest


class VersionTest(unittest.TestCase):
    def test_reads_the_version_without_pkg_resources(self):
        from abxr.version import version
        self.assertIsInstance(version, str)
        self.assertTrue(version)


if __name__ == "__main__":
    unittest.main()
