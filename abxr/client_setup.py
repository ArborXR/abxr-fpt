#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#
"""Getting the ArborXR client ready before a configuration package is loaded."""

from abxr.configuration_package import AbxrClientApk
from abxr.device import DeviceInstallException
from abxr.device_policy import ALREADY_CURRENT, INSTALL, KEEP_INSTALLED, client_install_decision


def prepare_client(device, package, client_apk, operator_chose_client, force_upgrade):
    """Install or keep the client, make it the device owner and, for v2 packages, wipe it so it enrolls into the
    package's group. Returns whether a client was installed."""
    installed_version = device.abxr_client_version()
    decision = client_install_decision(
        installed_version,
        client_apk.version,
        operator_chose_client=operator_chose_client,
        force_upgrade=force_upgrade,
        is_v2_package=package.is_xrdm2,
    )

    if decision == KEEP_INSTALLED:
        print(f"Device {device} has client {installed_version}, newer than the package's {client_apk.version}. Keeping it.")
    elif decision == ALREADY_CURRENT:
        print(f"Device {device} already has the expected ArborXR Client APK version {client_apk.version}")

    installed = False

    if package.is_xrdm2:
        # Install first, then wipe, as the Device Setup App does: `adb install -r` keeps the client's data, so a
        # failed install (a refused downgrade, a bad APK) leaves the headset exactly as it was.
        if decision == INSTALL:
            installed = _install(device, client_apk, keep_newer_installed=not operator_chose_client)

        # A no-op when our client already owns the device, which is always true on HMS headsets.
        device.set_device_owner()

        if installed_version is not None:
            # Wipe an existing client's data so it enrolls into the package's group. Never uninstall it: on HMS
            # headsets the client keeps the HMS provisioning record through a wipe (client CL-1355) but not
            # through an uninstall.
            device.wipe_client()
    else:
        if decision == INSTALL:
            if installed_version is not None:
                device.remove_device_owner()
                device.uninstall_apk(AbxrClientApk.PACKAGE_NAME)
            installed = _install(device, client_apk, keep_newer_installed=False)

        device.set_device_owner()

    if installed:
        device.set_production_environment()

    return installed


def _install(device, client_apk, keep_newer_installed):
    installed = device.install_client_apk(client_apk.path, keep_newer_installed=keep_newer_installed)
    if installed and device.abxr_client_version() != client_apk.version:
        raise DeviceInstallException(f"Failed to install ArborXR Client APK {client_apk.version} on {device}")
    return installed
