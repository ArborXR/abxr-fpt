#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

import sys
import os


def get_tool_path(tool_name):
    """Resolve path to a platform tool (adb, aapt2).

    Frozen (PyInstaller) builds: tools bundled under _MEIPASS/tools/.
    Dev / pip-install mode: tools expected on PATH (unchanged behavior).
    """
    if getattr(sys, 'frozen', False):
        base = os.path.join(sys._MEIPASS, 'tools')
        if sys.platform == 'win32' and not tool_name.endswith('.exe'):
            tool_name += '.exe'
        path = os.path.join(base, tool_name)
        if os.path.isfile(path):
            return path
    return tool_name


def resource_path(filename):
    """Resolve path to a bundled data file.

    Frozen builds: files under _MEIPASS/.
    Dev mode: relative to the abxr package directory.
    """
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'abxr', filename)
    return os.path.join(os.path.dirname(__file__), filename)
