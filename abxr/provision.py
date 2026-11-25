#!/usr/bin/env python3
#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

import argparse
import os
import platform
import subprocess
import tempfile
import time

from pathlib import Path
from threading import Semaphore

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


ASSETS_PATH = os.environ.get("ABXR_ASSETS_PATH", Path.home() / "abxr")
CONFIG_PACKAGE_PATH = ASSETS_PATH / Path("configuration-packages")
CLIENT_OVERRIDE_PATH = ASSETS_PATH / Path("client")

usb_event_handled = 0
usb_semaphore = Semaphore(0)
hotplug = False

def complete_setup(device):
    """The Device Setup App's CompleteSetup: sleep and Guardian come back on in the `finally` below; a VIVE Flow on
    firmware older than 1.98.8888.01 reboots, so the Holoride app doesn't auto-launch after setup."""
    if device.is_vive_flow() and is_older_firmware(device.firmware_version, "1.98.8888.01"):
        device.reboot()


def get_client_apk_override(args):
    if args.client:
        return AbxrClientApk(Path(args.client))

    for f in CLIENT_OVERRIDE_PATH.glob("*.apk"):
        return AbxrClientApk(f)
    
    return None


def get_connected_devices(args):
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    lines = result.stdout.strip().split("\n")[1:]
    serial_numbers = [line.split("\t")[0] for line in lines if "device" in line]

    devices = []

    for serial in serial_numbers:
        devices.append(Device(serial))

    if args.device_serial:
        devices = [d for d in devices if d.serial == args.device_serial]

    return devices


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


def trigger_device_plug_event():
    global usb_event_handled
    if usb_event_handled == 0:
        usb_event_handled = 1
        print("Waking up due to USB plug event...")
        usb_semaphore.release()


def usb_event_observer(action, device):
    if action == "add":
        trigger_device_plug_event()


def provision(args):
    print("ArborXR Field Provisioning Tools")
    print(f"Version: {version}")
 
    display.write([ "ArborXR", "Field Provisioning", f"Version: {version}"], wait=5)

    devices = get_connected_devices(args)
    if len(devices) > 0:
        usb_semaphore.release()

    packages = get_configuration_packages(args)
    if len(packages) == 0:
        print("No configuration packages found.")
        display.write("No configuration packages found.")
        if not hotplug:
            exit(0)

    number_of_config_packages = len(packages)

    while True:
        print("Waiting for device to be connected...")
        display.write([f"{number_of_config_packages} packages loaded", "", "Waiting for device to be connected."])

        global usb_event_handled
        usb_event_handled = 0
        usb_semaphore.acquire()
 
        if hotplug:
            print("Waiting for ADB device detection to settle...")
            display.write(["Waiting for ADB", "device detection."])
            time.sleep(5)
        
        devices = get_connected_devices(args)
        if len(devices) == 0:
            print("No devices connected.")
            display.write("No devices connected.", wait=5)
            if not hotplug:
                exit(0)
            continue

        for device in devices:
            package = get_configuration_package_for_device(device, packages)
            if package is None:
                print(f"No matching configuration package found for device model: {device.model_name} sn: {device.serial}")
                display.write([f"No package found for device: {device.serial}"], wait=5)
                continue
            
            print(f"Using configuration package: {package.path}")
            
            timer = time.time()

            try:
                with tempfile.TemporaryDirectory() as tempdir:
                    # Resolve inputs before touching the headset: a bad --client path or package fails here, with
                    # no cleanup, as in the Device Setup App.
                    launcher_apk_path = package.extract_item(package.launcher_apk, tempdir) if package.launcher_apk else None
                    if not args.package_only:
                        client_override = get_client_apk_override(args)
                        client_apk = client_override or package.extract_client_apk_from_zip(tempdir)
                        operator_chose_client = client_override is not None or args.force_upgrade

                        print("Using ArborXR client APK:", client_apk.path)
                        display.write(["Provisioning device:", device.model_name, device.serial, f"XRDM: {client_apk.version}"])

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
                                print(f"Device {device} is enrolled through Meta Horizon managed services (HMS).")
                            elif is_hms is None:
                                print(f"Couldn't tell whether device {device} is enrolled through HMS.")

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

                display.write(["Device provisioned!", device.serial], wait=2)
                        
            except DeviceWipeClientException as e:
                print(f"Failed to wipe client: {e}")
                display.write("Failed to wipe client", wait=5)

            except DeviceUninstallException as e:
                print(f"Failed to uninstall apk: {e}")
                display.write("Failed to uninstall apk", wait=5)

            except DeviceClientDowngradeException as e:
                print(f"Client downgrade refused: {e}")
                display.write(["Headset client is newer.", "Remove /client override", "or --force-upgrade."], wait=5)
            except DeviceInstallException as e:
                print(f"Failed to install apk: {e}")
                display.write("Failed to install apk", wait=5)

            except DeviceGrantPermissionException as e:
                print(f"Failed to grant client permissions: {e}")
                display.write("Failed to grant client permissions", wait=5)
            except DeviceSetDeviceOwnerException as e:
                print(f"Failed to set device owner: {e}")
                display.write("Failed to set device owner", wait=5)

            except DeviceConfigureException as e:
                print(f"Failed to configure device: {e}")
                display.write("Failed to configure device", wait=5)

            except Exception as e:
                print(f"Unhandled Error: {e}")
                display.write("Unhandled Error", wait=5)

            finally:
                if device.is_quest():
                    device.set_quest_sleep_enabled(True)
                    device.set_quest_guardian_enabled(True)
                

                elapsed_time_sec = time.time() - timer
                elapsed_time_min = elapsed_time_sec // 60
                elapsed_time_sec = elapsed_time_sec % 60

                print(f"Provisioning complete for {device} in {elapsed_time_min:.0f}m {elapsed_time_sec:.0f}s")

        else:
            print("No more devices to provision.")
            print("\n")
            display.write(["No more devices", "to provision."], wait=2)
            
        if not hotplug:
            exit(0)


def main():
    parser = argparse.ArgumentParser(description="ArborXR Field Provisioning Tools")
    parser.add_argument("-p", "--config-package", help="Path to configuration packages", type=str)
    parser.add_argument("-o", "--package-only", help="Only install configuration package do not provision", action="store_true")
    parser.add_argument("-c", "--client", help="Path to client APK for override", type=str)
    parser.add_argument("-s", "--device-serial", help="Serial number of device to provision", type=str)
    parser.add_argument("-f", "--force-upgrade", help="Force client install even if already installed", action="store_true")
    parser.add_argument("-l", "--list-connected-devices", help="List connected devices", action="store_true")
    args = parser.parse_args()

    if not Path(ASSETS_PATH).exists():
        parser.print_usage()
        print(f"Error: ABXR_ASSETS_PATH is not set to a valid path: {ASSETS_PATH}")
        exit(1)

    if platform.system() == "Linux":        
        import pyudev
        global hotplug

        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem='usb')

        observer = pyudev.MonitorObserver(monitor, usb_event_observer)
        observer.start()

        hotplug = True
    else:
        usb_semaphore.release()

    if args.list_connected_devices:
        devices = get_connected_devices(args)
        for device in devices:
            print(device)
        exit(0)

    provision(args)

if __name__ == "__main__":
    main()
