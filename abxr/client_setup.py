#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#
"""Getting the ArborXR client ready before a configuration package is loaded.

This follows the Device Setup App step for step (device repo, SetupApp.Core/Device.fs: GetDeviceSetupSteps,
SetupDevice and CleanUpDependencies), because that's what customers' headsets are set up with today.
"""

from abxr.configuration_package import AbxrLauncherApk
from abxr.device import DeviceClientDowngradeException, DeviceInstallException
from abxr.device_policy import is_newer_version


def prepare_client(device, client_apk, launcher_apk_path, operator_chose_client):
    """Install the client and launcher, make the client the device owner and, on a headset that already had the
    client, wipe it so it enrolls into the package's group. Returns whether the client was installed."""
    installed_version = device.abxr_client_version()

    # A client the operator chose must install, and a downgrade needs an uninstall, which this tool never does: on
    # HMS headsets the client keeps HMS's provisioning record through a wipe (client CL-1355), not an uninstall.
    # Refuse here, before anything on the headset changes, when the versions say it can't work.
    if operator_chose_client and is_newer_version(installed_version, client_apk.version):
        raise DeviceClientDowngradeException(f"Device {device} has client {installed_version}, newer than {client_apk.version}. Remove the /client override or --force-upgrade.")

    # 1. Clean up dependencies: remove the launcher before reinstalling it.
    if launcher_apk_path and device.is_packaged_installed(AbxrLauncherApk.PACKAGE_NAME):
        device.uninstall_apk(AbxrLauncherApk.PACKAGE_NAME)

    # 2. Install dependencies: always the package's client and launcher. A refused downgrade of the package's own
    # client or launcher is ignored, so the headset keeps its newer one.
    installed = device.install_client_apk(client_apk.path, keep_newer_installed=not operator_chose_client)
    if installed:
        _check_installed_version(device, client_apk)
    if launcher_apk_path:
        device.install_client_apk(launcher_apk_path, keep_newer_installed=True, label="ArborXR launcher")

    # 3. Start the client. 4. Make it the device owner (a no-op when it already is, as on every HMS headset).
    device.start_client_app()
    device.set_device_owner()

    # 5. Wipe a client that was already there, so it enrolls into the package's group.
    if installed_version is not None:
        device.wipe_client()

    if installed:
        device.set_production_environment()
    return installed


def _check_installed_version(device, client_apk):
    if not client_apk.version:
        return
    installed_version = device.abxr_client_version() or ""
    release = installed_version.split("-")[0].split("+")[0]
    if release != client_apk.version:
        raise DeviceInstallException(f"Failed to install ArborXR Client APK {client_apk.version} on {device} (it reports {installed_version or 'nothing'})")


def clean_up_after_failure(device, has_launcher):
    """Like the Device Setup App after a failed setup step: wipe the client and remove the launcher, so a
    half-provisioned headset can't be shipped looking enrolled. Never uninstall the client (HMS)."""
    try:
        if device.abxr_client_version() is not None:
            device.wipe_client()
    except Exception as e:
        print(f"Couldn't wipe the client on {device} after the failure: {e}")

    if has_launcher:
        try:
            if device.is_packaged_installed(AbxrLauncherApk.PACKAGE_NAME):
                device.uninstall_apk(AbxrLauncherApk.PACKAGE_NAME)
        except Exception as e:
            print(f"Couldn't remove the launcher on {device} after the failure: {e}")
