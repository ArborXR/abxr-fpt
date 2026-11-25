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


# The result block `dumpsys activity service xrdm.adb.AdbService '<command>'` prints when the client's AdbService
# took the command. Same pattern as the Device Setup App (SetupApp.Core/Adb.fs, ServiceResultRegex).
_SERVICE_RESULT = re.compile(r"(?m)^SERVICE.*(?:\r\n|[\r\n]).+Client:(?:\r\n|[\r\n])(?P<output>.*)")


def parse_service_result(dumpsys_output):
    """The client's answer to an AdbService command, or None when the service didn't answer (e.g. it isn't
    running yet, so dumpsys prints "No services match") or answered with an error."""
    match = _SERVICE_RESULT.search(dumpsys_output)
    if not match or not match.group("output").strip():
        return None
    result = match.group("output").strip()
    return None if "ERROR" in result else result


def parse_command_id(service_result):
    """The command id AdbService reports for an accepted command ("... TAG: <id>"), or None."""
    if "TAG: " not in service_result:
        return None
    return service_result.split("TAG: ")[-1].strip() or None


def parse_command_progress(logcat_line, command_id):
    """The message in a `logcat -v tag` line ("I/<command id>: <message>") for this command, or None. The client logs
    progress there and ends with DONE, or a message starting with ERROR."""
    line = logcat_line.rstrip("\r\n")
    if len(line) < 3 or not line[2:].startswith(command_id) or ":" not in line:
        return None
    return line[line.index(":") + 2:]


_RELEASE_VERSION = re.compile(r"^\d{4}\.\d+\.\d+$")


def is_newer_version(installed_version, target_version):
    """Whether the installed client is a newer release than the target. False unless both are plain release
    versions (YYYY.W.N, as in the client's release tags)."""
    if not (installed_version and target_version):
        return False
    if not (_RELEASE_VERSION.match(installed_version) and _RELEASE_VERSION.match(target_version)):
        return False
    return tuple(map(int, installed_version.split("."))) > tuple(map(int, target_version.split(".")))


def is_older_firmware(firmware_version, threshold):
    """Whether a dotted firmware version (e.g. "1.97.1234.01") is older than the threshold, compared like the
    Device Setup App's NuGetVersion: an unreadable version counts as 0 (older), and a pre-release suffix
    ("1.98.8888.01-beta") is older than the same release."""
    def parse(version):
        base, _, prerelease = str(version or "").partition("-")
        try:
            return tuple(int(part) for part in base.split(".")), bool(prerelease)
        except ValueError:
            return (0,), False

    (firmware, firmware_prerelease), (minimum, _) = parse(firmware_version), parse(threshold)
    length = max(len(firmware), len(minimum))
    firmware += (0,) * (length - len(firmware))
    minimum += (0,) * (length - len(minimum))
    return firmware < minimum or (firmware == minimum and firmware_prerelease)


def is_downgrade_error(adb_install_output):
    """Whether `adb install` failed because the APK is older than the installed version."""
    return "INSTALL_FAILED_VERSION_DOWNGRADE" in adb_install_output.upper()
