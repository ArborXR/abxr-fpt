import importlib
import sys
import unittest
from importlib.metadata import PackageNotFoundError, version as installed_version


class VersionTest(unittest.TestCase):
    def test_reads_the_version_without_pkg_resources(self):
        # setuptools 81 and later don't ship pkg_resources: importing it must not be needed.
        saved = sys.modules.get("pkg_resources")
        sys.modules["pkg_resources"] = None
        try:
            import abxr.version
            module = importlib.reload(abxr.version)
        finally:
            if saved is None:
                sys.modules.pop("pkg_resources", None)
            else:
                sys.modules["pkg_resources"] = saved

        try:
            expected = installed_version("abxrfpt")
        except PackageNotFoundError:
            expected = "unknown"
        self.assertEqual(expected, module.version)


if __name__ == "__main__":
    unittest.main()
