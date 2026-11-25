#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#
"""Getting the ArborXR client ready before a configuration package is loaded.

For v2 packages this follows the Device Setup App step for step (device repo, SetupApp.Core/Device.fs,
GetDeviceSetupSteps and SetupDevice), because that's what customers' headsets are set up with today.
"""

from abxr.configuration_package import AbxrClientApk, AbxrLauncherApk
from abxr.device import DeviceInstallException


def prepare_client(device, package, client_apk, launcher_apk_path, operator_chose_client, force_upgrade):
    """Install the client (and launcher), make the client the device owner and, for v2 packages on a headset that
    already had the client, wipe it so it enrolls into the package's group. Returns whether a client was
    installed."""
    if package.is_xrdm2:
        return _prepare_v2(device, client_apk, launcher_apk_path, operator_chose_client)
    return _prepare_v1(device, client_apk, launcher_apk_path, force_upgrade)


def _prepare_v2(device, client_apk, launcher_apk_path, operator_chose_client):
    is_reinstall = device.abxr_client_version() is not None

    # 1. Clean up dependencies: the Device Setup App removes the launcher before reinstalling it.
    if launcher_apk_path and device.is_packaged_installed(AbxrLauncherApk.PACKAGE_NAME):
        device.uninstall_apk(AbxrLauncherApk.PACKAGE_NAME)

    # 2. Install dependencies: always the package's client and launcher. A refused downgrade of the package's own
    # client is ignored (the headset keeps its newer one); a client the operator chose must install.
    installed = device.install_client_apk(client_apk.path, keep_newer_installed=not operator_chose_client)
    if installed:
        _check_installed_version(device, client_apk)
    if launcher_apk_path:
        device.install_client_apk(launcher_apk_path, keep_newer_installed=True)

    # 3. Start the client, 4. make it the device owner (a no-op when it already is, as on every HMS headset).
    device.start_client_app()
    device.set_device_owner()

    # 5. Wipe a client that was already there, so it enrolls into the package's group. Never uninstall it: on HMS
    # headsets the client keeps the HMS provisioning record through a wipe (client CL-1355), not an uninstall.
    if is_reinstall:
        device.wipe_client()

    if installed:
        device.set_production_environment()
    return installed


def _prepare_v1(device, client_apk, launcher_apk_path, force_upgrade):
    # XRDM 1 packages keep this tool's original steps.
    installed_version = device.abxr_client_version()
    installed = False

    if installed_version != client_apk.version or force_upgrade:
        if installed_version is not None:
            device.remove_device_owner()
            device.uninstall_apk(AbxrClientApk.PACKAGE_NAME)
        installed = device.install_client_apk(client_apk.path, keep_newer_installed=False)
        _check_installed_version(device, client_apk)
        device.set_device_owner()
        device.set_production_environment()
    else:
        print(f"Device {device} already has the expected ArborXR Client APK version {client_apk.version}")

    if launcher_apk_path:
        if device.is_packaged_installed(AbxrLauncherApk.PACKAGE_NAME):
            device.uninstall_apk(AbxrLauncherApk.PACKAGE_NAME)
        device.install_apk(launcher_apk_path)

    return installed


def _check_installed_version(device, client_apk):
    installed_version = device.abxr_client_version() or ""
    if client_apk.version and not installed_version.startswith(client_apk.version):
        raise DeviceInstallException(f"Failed to install ArborXR Client APK {client_apk.version} on {device} (it reports {installed_version or 'nothing'})")


def clean_up_after_failure(device, package):
    """Like the Device Setup App after a failed run: wipe the client so a half-provisioned headset can't be shipped
    looking enrolled. Never uninstall it (HMS)."""
    if not package.is_xrdm2:
        return
    try:
        if device.abxr_client_version() is not None:
            device.wipe_client()
    except Exception as e:
        print(f"Couldn't wipe the client on {device} after the failure: {e}")
