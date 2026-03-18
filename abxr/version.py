#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

def _get_version():
    try:
        from importlib.metadata import version
        return version("abxrfpt")
    except Exception:
        return "unknown"

version = _get_version()
