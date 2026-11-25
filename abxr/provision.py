#!/usr/bin/env python3
#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

import argparse
import os
import tempfile
import time

from pathlib import Path

from abxr.configuration_package import AbxrClientApk, AbxrLauncherApk, ConfigurationPackage
from abxr.device import Device, \
                        DeviceInstallException, \
                        DeviceUninstallException, \
                        DeviceConfigureException, \
                        DeviceSetDeviceOwnerException, \
                        DeviceGrantPermissionException, \
                        DeviceClientDowngradeException, \
                        DeviceWipeClientException
from abxr.client_setup import SetupProgress, clean_up_after_failure, prepare_client
from abxr.device_policy import is_older_firmware
from abxr.display import display
from abxr.version import version
from abxr.station import Station, list_adb_devices


ASSETS_PATH = os.environ.get("ABXR_ASSETS_PATH", Path.home() / "abxr")
CONFIG_PACKAGE_PATH = ASSETS_PATH / Path("configuration-packages")
CLIENT_OVERRIDE_PATH = ASSETS_PATH / Path("client")

POLL_SECONDS = 2


def complete_setup(device):
    """The Device Setup App's CompleteSetup: sleep and Guardian come back on in provision_device's `finally`; a VIVE
    Flow on firmware older than 1.98.8888.01 reboots, so the Holoride app doesn't auto-launch after setup."""
    if device.is_vive_flow() and is_older_firmware(device.vive_flow_firmware_version(), "1.98.8888.01"):
        device.reboot()


def get_client_apk_override(args):
    if args.client:
        return AbxrClientApk(Path(args.client))

    for f in CLIENT_OVERRIDE_PATH.glob("*.apk"):
        return AbxrClientApk(f)

    return None


XRDM1_UNSUPPORTED = "XRDM 1 configuration packages are no longer supported. Build a new package in the ArborXR portal."


def load_configuration_package(path):
    package = ConfigurationPackage(path)
    if not package.is_xrdm2:
        raise Exception(f"{path}: {XRDM1_UNSUPPORTED}")
    return package


def get_configuration_packages(args):
    packages = []
    models = []

    if args.config_package:
        try:
            packages.append(load_configuration_package(args.config_package))
        except Exception as e:
            print(f"Error loading configuration package: {e}")
    else:
        for f in CONFIG_PACKAGE_PATH.glob("*.zip"):
            try:
                package = load_configuration_package(f)
                if package.model_name() in models:
                    print(f"Duplicate configuration package detected for {package.model_name()} at {package.path}")
                    print("Automatic device package selection is unavailable.")
                    return []

                print(f"Configuration package for {package.model_name()}, {package.path.name}, created: {package.created_at()}")
                packages.append(package)
                models.append(package.model_name())
            except Exception as e:
                print(f"Error loading configuration package: {e}")
                continue

    return packages


def get_configuration_package_for_device(device, packages):
    print(f"Finding configuration package for device: {device.model_name}")

    for package in packages:
        if package.model_name() == device.model_name:
            return package
        elif package.model_name() == device.model_name.replace("-", " "):
            return package
        elif device.model_name in package.model_names():
            return package
        
    return None


FAILURE_MESSAGES = [
    (DeviceWipeClientException, "Failed to wipe client"),
    (DeviceUninstallException, "Failed to uninstall apk"),
    (DeviceClientDowngradeException, "Headset client is newer. Remove the /client override or --force-upgrade."),
    (DeviceInstallException, "Failed to install apk"),
    (DeviceGrantPermissionException, "Failed to grant client permissions"),
    (DeviceSetDeviceOwnerException, "Failed to set device owner"),
    (DeviceConfigureException, "Failed to configure device"),
]


def provision_device(device, package, args, log):
    """Provision one headset with one package. Returns True on success. Each call runs on its own thread and opens
    its own handle on the package zip, so several headsets can be provisioned at once."""
    package = ConfigurationPackage(package.path)
    timer = time.time()

    try:
        with tempfile.TemporaryDirectory() as tempdir:
            # Resolve inputs before touching the headset: a bad --client path or package fails here, with no
            # cleanup, as in the Device Setup App.
            launcher_apk_path = package.extract_item(package.launcher_apk, tempdir) if package.launcher_apk else None
            if not args.package_only:
                client_override = get_client_apk_override(args)
                client_apk = client_override or package.extract_client_apk_from_zip(tempdir)
                operator_chose_client = client_override is not None or args.force_upgrade
                log(f"Using ArborXR client APK {client_apk.path} (version {client_apk.version})")

            # The Device Setup App's setup steps (InstallDependencies). On a failure, clean up like it does.
            progress = SetupProgress()
            try:
                if not args.package_only:
                    if device.is_quest():
                        progress.step = "disabling-sleep"
                        device.set_quest_sleep_enabled(False)
                        device.set_quest_guardian_enabled(False)

                    is_hms = device.is_hms()
                    if is_hms:
                        log("Enrolled through Meta Horizon managed services (HMS).")
                    elif is_hms is None:
                        log("Couldn't tell whether this headset is enrolled through HMS.")

                    prepare_client(device, client_apk, launcher_apk_path, operator_chose_client=operator_chose_client, progress=progress)
                elif launcher_apk_path:
                    if device.is_packaged_installed(AbxrLauncherApk.PACKAGE_NAME):
                        device.uninstall_apk(AbxrLauncherApk.PACKAGE_NAME)
                    device.install_apk(launcher_apk_path)

                progress.step = "installing-content"
                device.push_content(package)
            except DeviceClientDowngradeException:
                # Refused before the client changed; the launcher was put back.
                raise
            except Exception:
                if not args.package_only and progress.should_clean_up():
                    clean_up_after_failure(device, has_launcher=launcher_apk_path is not None)
                raise

            # BootstrapFromPackage, then CompleteSetup. Like the Device Setup App, no cleanup if these fail.
            device.hand_off_settings(package)
            complete_setup(device)

        log("Provisioned.")
        return True

    except Exception as e:
        message = next((text for kind, text in FAILURE_MESSAGES if isinstance(e, kind)), "Unhandled error")
        log(f"{message}: {e}")
        return False

    finally:
        try:
            if device.is_quest():
                device.set_quest_sleep_enabled(True)
                device.set_quest_guardian_enabled(True)
        except Exception as e:
            log(f"Couldn't turn sleep and Guardian back on: {e}")

        elapsed = int(time.time() - timer)
        log(f"Finished in {elapsed // 60}m {elapsed % 60}s")


def provision(args):
    print("ArborXR Field Provisioning Tools")
    print(f"Version: {version}")
    display.write(["ArborXR", "Field Provisioning", f"Version: {version}"], wait=5)

    packages = get_configuration_packages(args)
    if len(packages) == 0:
        print("No configuration packages found.")
        display.write("No configuration packages found.")
        if args.once:
            exit(1)

    def run(serial, log):
        device = Device(serial)
        package = get_configuration_package_for_device(device, packages)
        if package is None:
            log(f"No configuration package for device model {device.model_name}.")
            return False
        log(f"Using configuration package {package.path.name}")
        return provision_device(device, package, args, log)

    station = Station(run, max_parallel=args.max_parallel, only_serial=args.device_serial)
    print(f"Provisioning up to {args.max_parallel} headsets at a time. " + ("Press Ctrl+C to stop." if not args.once else ""))

    try:
        while True:
            station.update(list_adb_devices())
            summary = station.summary()
            display.write(["ArborXR provisioning", summary])
            if args.once and station.is_idle():
                print(summary)
                exit(0 if station.failed_count() == 0 else 1)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        running = station.running_count()
        if running:
            print(f"Stopping with {running} headset(s) still running. Re-run them; they aren't finished.")
        print(station.summary())


def main():
    parser = argparse.ArgumentParser(description="ArborXR Field Provisioning Tools")
    parser.add_argument("-p", "--config-package", help="Path to configuration packages", type=str)
    parser.add_argument("-o", "--package-only", help="Only install configuration package do not provision", action="store_true")
    parser.add_argument("-c", "--client", help="Path to client APK for override", type=str)
    parser.add_argument("-s", "--device-serial", help="Serial number of device to provision (implies --once)", type=str)
    parser.add_argument("-f", "--force-upgrade", help="Force client install even if already installed", action="store_true")
    parser.add_argument("-l", "--list-connected-devices", help="List connected devices", action="store_true")
    parser.add_argument("-n", "--max-parallel", help="How many headsets to provision at once (default 8)", type=int, default=8)
    parser.add_argument("--once", help="Provision the headsets connected now, then exit", action="store_true")
    args = parser.parse_args()

    if args.device_serial:
        args.once = True
    if args.max_parallel < 1:
        parser.error("--max-parallel must be at least 1")

    if not Path(ASSETS_PATH).exists():
        parser.print_usage()
        print(f"Error: ABXR_ASSETS_PATH is not set to a valid path: {ASSETS_PATH}")
        exit(1)

    if args.list_connected_devices:
        for serial, state in list_adb_devices():
            if state == "device":
                print(serial)
        exit(0)

    provision(args)


if __name__ == "__main__":
    main()
