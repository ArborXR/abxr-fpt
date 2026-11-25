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


def parse_is_hms(oemconfig_query_output):
    """Whether Meta's OEMConfig provider reports the headset as managed by Horizon managed services (HMS).

    Same check as the Device Setup App (SetupApp.Core/Adb.fs, GetIsHms): the query for
    content://com.oculus.oemconfig.provider/managed returns -1 or "not found" when the headset isn't managed.
    """
    return not ("-1" in oemconfig_query_output or "not found" in oemconfig_query_output)
