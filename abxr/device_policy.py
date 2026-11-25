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


def compare_versions(installed_version, target_version):
    """-1, 0 or 1 as the installed client version is older than, equal to or newer than the target, or None
    when either can't be read (e.g. "2026.47.0" versus "2026.45.1")."""
    def parse(version):
        try:
            return tuple(int(part) for part in str(version).split("-")[0].split("."))
        except (TypeError, ValueError):
            return None

    installed, target = parse(installed_version), parse(target_version)
    if installed is None or target is None:
        return None
    return (installed > target) - (installed < target)


INSTALL = "install"
KEEP_INSTALLED = "keep-installed"
ALREADY_CURRENT = "already-current"


class ClientDowngradeRefused(Exception):
    pass


def client_install_decision(installed_version, target_version, operator_chose_client, force_upgrade, is_v2_package):
    """What to do with the client before loading a package, decided before anything is wiped.

    INSTALL, KEEP_INSTALLED (the headset has a newer client than the package's own, which the Device Setup App also
    keeps) or ALREADY_CURRENT. Raises ClientDowngradeRefused when the operator chose an older client (a /client
    override or --force-upgrade) for a v2 package: that needs an uninstall, which this tool never does for v2
    packages because it would lose an HMS headset's provisioning record.
    """
    if installed_version is None:
        return INSTALL

    comparison = compare_versions(installed_version, target_version)

    if comparison is None:
        return INSTALL if installed_version != target_version or force_upgrade else ALREADY_CURRENT
    if comparison > 0:
        if not operator_chose_client:
            return KEEP_INSTALLED
        if is_v2_package:
            raise ClientDowngradeRefused(f"The headset has client {installed_version}, newer than {target_version}. Can't downgrade it with a v2 package.")
        return INSTALL
    if comparison < 0 or force_upgrade:
        return INSTALL
    return ALREADY_CURRENT


def is_downgrade_error(adb_install_output):
    """Whether `adb install` failed because the APK is older than the installed version."""
    return "INSTALL_FAILED_VERSION_DOWNGRADE" in adb_install_output.upper()
