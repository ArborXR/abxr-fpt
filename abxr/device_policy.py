#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#
"""Parsing for the device-ownership and HMS checks, kept free of adb so it can be tested."""

import re

CLIENT_PACKAGE_NAME = "app.xrdm.client"
CLIENT_ADMIN_RECEIVER = "app.xrdm.client/.AdminReceiver"

# Same pattern as the Device Setup App (device repo, SetupApp.Core/Adb.fs, OwnerAppRegex).
_DEVICE_OWNER = re.compile(r"Device Owner:\s*admin=ComponentInfo\{(?P<component>[^}]*)\}")


def parse_device_owner(dumpsys_device_policy):
    """The device owner's component ("package/class") from `dumpsys device_policy`, or None if there isn't one."""
    if "enabled device admins" not in dumpsys_device_policy.lower():
        return None

    match = _DEVICE_OWNER.search(dumpsys_device_policy)
    return match.group("component") if match else None


def is_client_admin(component):
    """Whether a device-owner component is our client's admin receiver, in either short or full form."""
    if not component or "/" not in component:
        return False

    package_name, class_name = component.split("/", 1)
    if class_name.startswith("."):
        class_name = package_name + class_name

    return package_name == CLIENT_PACKAGE_NAME and class_name == f"{CLIENT_PACKAGE_NAME}.AdminReceiver"


def parse_is_hms(oemconfig_query_output, oemconfig_query_error=""):
    """Whether Meta's OEMConfig provider reports the headset as managed by Horizon managed services (HMS):
    True, False, or None when the provider gave no answer.

    Based on the Device Setup App (SetupApp.Core/Adb.fs, GetIsHms): any stderr means no answer, and a managed
    headset's row doesn't contain -1 or "not found". An empty result is also no answer here.
    """
    if oemconfig_query_error.strip() or "Row:" not in oemconfig_query_output:
        return None
    return not ("-1" in oemconfig_query_output or "not found" in oemconfig_query_output)


_RELEASE_VERSION = re.compile(r"^\d{4}\.\d+\.\d+$")


def compare_versions(installed_version, target_version):
    """-1, 0 or 1 as the installed client is older than, equal to or newer than the target. None unless both are
    plain release versions (YYYY.W.N, as in the client's release tags), e.g. "2026.47.0-dev" can't be compared."""
    if not (installed_version and target_version):
        return None
    if not (_RELEASE_VERSION.match(installed_version) and _RELEASE_VERSION.match(target_version)):
        return None

    installed = tuple(int(part) for part in installed_version.split("."))
    target = tuple(int(part) for part in target_version.split("."))
    return (installed > target) - (installed < target)


INSTALL = "install"
KEEP_INSTALLED = "keep-installed"
ALREADY_CURRENT = "already-current"


def client_install_decision(installed_version, target_version, operator_chose_client, force_upgrade, is_v2_package):
    """Whether to install the target client: INSTALL, KEEP_INSTALLED or ALREADY_CURRENT.

    XRDM 1 packages keep this tool's original rule: install whenever the versions differ (after an uninstall).
    v2 packages keep a newer installed client, as the Device Setup App does, unless the operator chose a client
    (a /client override or --force-upgrade). Anything uncertain is an INSTALL attempt: for v2 packages the client
    is installed before it's wiped, so a failed attempt leaves the headset as it was.
    """
    if installed_version is None:
        return INSTALL

    if not is_v2_package:
        return INSTALL if installed_version != target_version or force_upgrade else ALREADY_CURRENT

    if operator_chose_client:
        return INSTALL
    if (compare_versions(installed_version, target_version) or 0) > 0:
        return KEEP_INSTALLED
    if installed_version == target_version:
        return ALREADY_CURRENT
    return INSTALL


def is_downgrade_error(adb_install_output):
    """Whether `adb install` failed because the APK is older than the installed version."""
    return "INSTALL_FAILED_VERSION_DOWNGRADE" in adb_install_output.upper()
