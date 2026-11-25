#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

# importlib.metadata, not pkg_resources: setuptools 81 and later no longer ship pkg_resources, so a fresh install
# couldn't start.
from importlib.metadata import PackageNotFoundError, version as _installed_version

try:
    version = _installed_version("abxrfpt")
except PackageNotFoundError:
    version = "unknown"
