import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class VersionTest(unittest.TestCase):
    def test_reads_the_installed_version_without_setuptools(self):
        # setuptools 81 and later don't ship pkg_resources, and setuptools isn't a runtime dependency: reading the
        # version must need neither. A fresh interpreter, so other tests' imports can't hide a regression.
        code = (
            "import sys; sys.modules['pkg_resources'] = None; sys.modules['setuptools'] = None; "
            "from abxr.version import version; print(version)"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)

        version = result.stdout.strip()
        if version == "unknown":
            self.skipTest("abxrfpt isn't installed (pip install -e .), so there's no version to read")
        declared = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        self.assertEqual(declared, version)


if __name__ == "__main__":
    unittest.main()
