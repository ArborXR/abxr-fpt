#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

import subprocess
import re
from abxr.tools import get_tool_path


def get_package_name(apk_path):
    """Extract package name from an APK using aapt2."""
    try:
        aapt2 = get_tool_path('aapt2')
        result = subprocess.run(
            [aapt2, 'dump', 'badging', str(apk_path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
        match = re.search(r"package: name='([^']+)'", result.stdout)
        return match.group(1) if match else None
    except Exception:
        return None
