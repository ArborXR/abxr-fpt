#
# Copyright (c) 2024-2025 ABXR Labs, Inc.
# Released under the MIT License. See LICENSE file for details.
#

import re
import subprocess
import time
import json
from pathlib import Path
import tempfile
import zipfile

from abxr.apk import get_package_name

from abxr.configuration_package import AbxrClientApk, ConfigurationPackage
from abxr.device_commands import RemoveDeviceOwnership, WipeClient
from abxr.device_policy import CLIENT_ADMIN_RECEIVER, CLIENT_PACKAGE_NAME, is_client_admin, is_downgrade_error, parse_device_owner, parse_is_hms, parse_service_result

# Same components the Device Setup App uses (device repo, Core/Configuration.fs and SetupApp.Core/Configuration.fs).
CLIENT_FINISHING_ACTIVITY = f"{CLIENT_PACKAGE_NAME}/xrdm.app.client.FinishingActivity"
CLIENT_ADB_SERVICE = "xrdm.adb.AdbService"
CLIENT_SETUP_DEVICE_RECEIVER = f"{CLIENT_PACKAGE_NAME}/.SetupDeviceReceiver"

# create custom exception for apk install failure
class DeviceInstallException(Exception):
    pass

class DeviceUninstallException(Exception):
    pass

class DeviceConfigureException(Exception):
    pass

class DeviceSetDeviceOwnerException(Exception):
    pass

class DeviceSetEnvironmentException(Exception):
    pass

class DeviceRemoveDeviceOwnerException(Exception):
    pass

class DeviceConfigureApiTokenException(Exception):
    pass

class DeviceConfigurationObjectException(Exception):
    pass

class DeviceClientDowngradeException(DeviceInstallException):
    pass

class DeviceGrantPermissionException(Exception):
    pass

class DeviceWipeClientException(Exception):
    pass



class Version:
    def __init__(self, version_str):
        parts = version_str.split('.')
        self.major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
        self.minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        self.build = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        self.revision = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

    def __repr__(self):
        return f"Version(major={self.major}, minor={self.minor}, build={self.build}, revision={self.revision})"


class SystemVersion:
    @staticmethod
    def sanitize(version):
        sanitized = re.sub(r'[^0-9.]', '', version)
        parts = sanitized.split('.')
        parts = parts[:4]
        
        return '.'.join(parts)

    @staticmethod
    def parse(version):
        try:
            sanitized_version = SystemVersion.sanitize(version)
            version_obj = Version(sanitized_version)
            return version_obj
        except Exception:
            return None    
    

class Device:
    def __init__(self, serial):
        self.serial = serial

        self.manufacturer_name = None
        self.model_name = None
        self.firmware_version = None
        self.system_version = None
        self.abi = None

        self._load_manufacturer_name()
        self._load_model_name()
        self._load_firmware_and_system_version()
        self._load_abi()

    def is_quest(self):
        return "Quest" in self.model_name
    
    def is_vive_flow(self):
        return "VIVE Flow" in self.model_name
    
    def is_pico(self):
        return "Pico" in self.model_name
    
    def is_vive_xr_elite(self):
        return "VIVE XR Series" in self.model_name
    
    def is_vive_focus_3(self):
        return "Focus 3" in self.model_name
    
    def is_magic_leap_2(self):
        return "Magic Leap 2" in self.model_name
    
    def prop(self, prop_name):
        result = subprocess.run(["adb", "-s", self.serial, "shell", "getprop", prop_name], capture_output=True, text=True)
        return result.stdout.strip()

    def _load_manufacturer_name(self):
        self.manufacturer_name = self.prop("ro.product.manufacturer")

    def _load_model_name(self):
        model_name = self.prop("pxr.vendorhw.product.model")
        
        if not model_name:
            model_name = self.prop("ro.product.model")
        
        self.model_name = model_name
    
    def _load_firmware_and_system_version(self):
        if self.is_vive_flow() or self.is_vive_xr_elite() or self.is_vive_focus_3():
            self.firmware_version = self.prop("ro.product.version")
        elif self.is_magic_leap_2():
            self.firmware_version = self.prop("ro.build.version.lumin")
        elif self.is_quest():
            self.firmware_version = self.get_installed_version("com.oculus.vrshell")
        else:
            self.firmware_version = self.get_installed_version("com.htc.mobilevr.launcher")

        if not self.firmware_version:
            self.firmware_version = self.prop("ro.build.display.id")

        self.system_version = SystemVersion.parse(self.firmware_version)

    def _load_abi(self):
        self.abi = self.prop("ro.product.cpu.abi")
    
    def is_abxr_provisioned(self):
        if self.abxr_client_version() is not None:
            return True
        return False
    
    def mkdir(self, path):
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "mkdir", "-p", path])
        if proc.returncode:
            raise Exception(f"Failed to create directory {path} on device {self.serial}")
    
    def install_apk_obb_package(self, bundle_path, fallback_package_name=None):
        """Install an app bundle zip. Its OBBs go to the package name of the APK inside it, or, like the Device
        Setup App, to the bundle's own name when it has no APK."""
        if type(bundle_path) == str:
            bundle_path = Path(bundle_path)

        if not bundle_path.suffix.lower() == ".zip":
            print(f"Skipping non-ZIP packaged file. {bundle_path}")
            raise DeviceInstallException(f"non-ZIP packaged file. {bundle_path}")

        with tempfile.TemporaryDirectory() as extract_path:
            try:
                with zipfile.ZipFile(bundle_path, 'r') as bundle:
                    bundle.extractall(extract_path)
                package_name = fallback_package_name
                for file in Path(extract_path).rglob("*.apk"):
                    if not file.name.startswith("."):
                        package_name = get_package_name(file)
                        self.install_apk(file)

                for file in Path(extract_path).rglob("*.obb"):
                    if not file.name.startswith("."):
                        print(f"Installing OBB: {file}")
                        self.mkdir(f"/sdcard/Android/obb/{package_name}")
                        self.push_file(file, f"/sdcard/Android/obb/{package_name}/{file.name}")        
            
            except NotImplementedError:
                print(f"Skipping invalid zip package format. {fallback_package_name or bundle_path}")
            except zipfile.BadZipFile as e:
                raise DeviceInstallException(f"App bundle {fallback_package_name or bundle_path} isn't a valid zip: {e}")            
        
    
    def install_apk(self, package_name):
        if type(package_name) == str:
            package_name = Path(package_name)

        if not package_name.suffix.lower() == ".apk":
            print(f"Skipping non-APK file. {package_name}")
            raise DeviceInstallException(f"non-APK file. {package_name}")

        print(f"Installing APK: {package_name}")
        proc = subprocess.run(["adb", "-s", self.serial, "install", "-r", "-t", "-g", package_name], capture_output=True, text=True)
        if proc.returncode:
            raise DeviceInstallException(f"Failed to install {package_name} on device {self.serial} - {proc.stderr}")
        
    def push_file(self, local_file, remote_file):
        proc = subprocess.run(["adb", "-s", self.serial, "push", local_file, remote_file])
        if proc.returncode:
            raise DeviceInstallException(f"Failed to push {local_file} to {remote_file} on device {self.serial}")
        
    def set_google_play_protect(self, enable):
        if enable:
            proc = subprocess.run(["adb", "-s", self.serial, "shell", "settings", "put", "global", "verifier_verify_adb_installs", "1", "&&", "settings", "put", "global", "package_verifier_enable", "1"])
        else:
            proc = subprocess.run(["adb", "-s", self.serial, "shell", "settings", "put", "global", "verifier_verify_adb_installs", "0", "&&", "settings", "put", "global", "package_verifier_enable", "0"])
        
        if proc.returncode:
            raise Exception("Failed to toggle Google Play Protect.")
        
    def set_quest_sleep_enabled(self, enable):
        if enable:
            proc = subprocess.run(["adb", "-s", self.serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.automation_disable", "&&", "svc", "power", "stayon", "false"])
        else:
            proc = subprocess.run(["adb", "-s", self.serial, "shell", "svc", "power", "stayon", "true", "&&", "am", "broadcast", "-a", "com.oculus.vrpowermanager.prox_close"])   
        
        if proc.returncode:
            raise Exception("Failed to toggle Quest sleep.")
        
    def set_quest_guardian_enabled(self, enable):
        if enable:
            proc = subprocess.run(["adb", "-s", self.serial, "shell", "setprop", "debug.oculus.guardian_pause", "0"])
        else:
            proc = subprocess.run(["adb", "-s", self.serial, "shell", "setprop", "debug.oculus.guardian_pause", "1"])
        
        if proc.returncode:
            raise Exception("Failed to toggle Guardian.")
    
    def device_sleep(self, seconds):
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "sleep", str(seconds)])
        if proc.returncode:
            raise Exception("Failed to sleep device.")
        
    def send_keycode_and_sleep(self, keycode, seconds):
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "input", "keyevent", str(keycode)])
        if proc.returncode:
            raise Exception("Failed to send keycode.")
        
        self.device_sleep(seconds)

    def set_package_enabled(self, package_name, enable):
        if enable:
            proc = subprocess.run(["adb", "-s", self.serial, "shell", "pm", "disable-user", "--user 0", package_name])
        else:
            proc = subprocess.run(["adb", "-s", self.serial, "shell", "pm", "enable", "--user 0", package_name])
        
        if proc.returncode:
            raise Exception(f"Failed to toggle {package_name} enablement.")

    def delete_quest_accounts(self):
        home = (3, 3)
        up = (19, 0.5)
        down = (20, 0.5)
        right = (22, 0.5)
        enter = (66, 0.5)

    
        requires_extra_down = False
        if self.system_version and self.system_version.major >= 62:
            requires_extra_down = True

        account_delete_steps = [
            home,
            "am start -n 'com.android.settings/.Settings$AccountDashboardActivity'",
            "sleep 5",
            down,
            up,
            down,
        ]

        if requires_extra_down:
            account_delete_steps.append(down)

        account_delete_steps += [
            enter,
            down,
            down,
            enter,
            down,
            right,
            enter,
            enter,
            down,
            down,
            enter,
            down,
            right,
            enter,
            enter,
            down,
            down,
            enter,
            down,
            right,
            enter,
            enter,
            down,
            down,
            enter,
            down,
            right,
            enter,
            "sleep 5",
        ]

        for step in account_delete_steps:
            if type(step) == tuple:
                self.send_keycode_and_sleep(*step)
            elif type(step) == str:
                proc = subprocess.run(["adb", "-s", self.serial, "shell", step])
                if proc.returncode:
                    raise Exception(f"Failed to execute step: {step}")
            else:
                raise Exception(f"Invalid step: {step}")


    def send_configuration_package(self, config_pkg):
        if isinstance(config_pkg, (str, Path)):
            config_pkg = ConfigurationPackage(config_pkg)

        if not isinstance(config_pkg, ConfigurationPackage):
            raise Exception("You must provide a ConfigurationPackage object.")

        if config_pkg.is_xrdm2:
            client_settings_file_location = "/sdcard/Setup/settings.json"
        else:
            client_settings_file_location = "/sdcard/ArborXR/Settings/settings.json"

        for app in config_pkg.apps:
            with tempfile.TemporaryDirectory() as extract_path:
                item = config_pkg.extract_item_flat(app, extract_path)
                self.install_apk(item)

        for obb_packaged_app in config_pkg.obb_packaged_apps:
            with tempfile.TemporaryDirectory() as extract_path:
                item = config_pkg.extract_item_flat(obb_packaged_app, extract_path)
                self.install_apk_obb_package(item, fallback_package_name=Path(obb_packaged_app).stem)

        # Loose OBBs, files, videos, images and launcher media, to the same paths the Device Setup App uses.
        for entry, device_path in config_pkg.pushes():
            with tempfile.TemporaryDirectory() as extract_path:
                item = config_pkg.extract_item_flat(entry, extract_path)
                self.push_file(item, device_path)

        # Write settings.json to a closed file: on Windows adb can't read a NamedTemporaryFile that's still open.
        with tempfile.TemporaryDirectory() as settings_dir:
            settings_path = Path(settings_dir) / "settings.json"
            settings_path.write_bytes(config_pkg.read_settings_json_from_zip())
            self.push_file(settings_path, client_settings_file_location)

        # Same hand-off as the Device Setup App for both package versions: the client reads settings.json, applies
        # its configurations and enrolls with its token. Start the client first so the broadcast is allowed.
        if config_pkg.is_xrdm2:
            self.start_client_app()
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "am", "broadcast", "-n", CLIENT_SETUP_DEVICE_RECEIVER, "-a", "CONFIGURE_DEVICE", "-e", "ClientSettingsFile", client_settings_file_location], capture_output=True, text=True)
        if proc.returncode or "Exception" in proc.stdout or "Error" in proc.stdout:
            raise DeviceConfigureException(f"Failed to configure device with settings.json. {proc.stdout}{proc.stderr}")

    def force_stop_and_sleep(self, package_name, seconds):
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "am", "force-stop", package_name])
        if proc.returncode:
            raise Exception(f"Failed to force stop {package_name} on device {self.serial}")
        
        self.device_sleep(seconds)

    def reboot(self):
        proc = subprocess.run(["adb", "-s", self.serial, "reboot"])
        if proc.returncode:
            raise Exception(f"Failed to reboot device {self.serial}")

    def device_owner(self):
        """The device owner's component, or None. Same check as the Device Setup App."""
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "dumpsys", "-t", "3", "device_policy"], capture_output=True, text=True)
        if proc.returncode:
            return None
        return parse_device_owner(proc.stdout)

    def is_hms(self):
        """Whether the headset is managed through Meta Horizon managed services (HMS): True, False, or None when
        Meta's OEMConfig provider gives no answer."""
        if not self.is_quest():
            return False
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "content", "query", "--uri", "content://com.oculus.oemconfig.provider/managed"], capture_output=True, text=True)
        if proc.returncode:
            return None
        return parse_is_hms(proc.stdout, proc.stderr)

    def android_major_version(self):
        try:
            return int(self.prop("ro.build.version.release").split(".")[0])
        except ValueError:
            return 0

    def grant_client_permissions(self):
        # Like the Device Setup App: on Android 11+ the client needs REQUEST_INSTALL_PACKAGES to write to
        # Android/obb and Android/data. `adb install -g` doesn't cover it because it isn't a runtime permission.
        if self.android_major_version() >= 11:
            proc = subprocess.run(["adb", "-s", self.serial, "shell", "appops", "set", CLIENT_PACKAGE_NAME, "REQUEST_INSTALL_PACKAGES", "allow"], capture_output=True, text=True)
            if proc.returncode or proc.stdout.strip():
                raise DeviceGrantPermissionException(f"Failed to grant REQUEST_INSTALL_PACKAGES to the client. {proc.stdout}{proc.stderr}")

    def install_client_apk(self, client_apk_path, keep_newer_installed=True):
        """Install the client or launcher. Returns False when the headset already has a newer one and
        keep_newer_installed is set: like the Device Setup App, a refused downgrade of a package's own client or
        launcher is ignored. A client the operator chose (a /client override, --force-upgrade) must install, so its
        downgrade still fails."""
        proc = subprocess.run(["adb", "-s", self.serial, "install", "-r", "-t", "-g", client_apk_path], capture_output=True, text=True)
        if not proc.returncode:
            return True
        if is_downgrade_error(proc.stdout + proc.stderr):
            if keep_newer_installed:
                print(f"Device {self.serial} has a newer ArborXR client than the package. Keeping it.")
                return False
            raise DeviceClientDowngradeException(f"Device {self.serial} has a newer ArborXR client than {client_apk_path}. Remove the /client override or --force-upgrade.")
        raise DeviceInstallException(f"Failed to install {client_apk_path} on device {self.serial} - {proc.stderr}")

    def set_device_owner(self):
        self.grant_client_permissions()

        owner = self.device_owner()
        if is_client_admin(owner):
            # HMS headsets, and headsets provisioned before: our client already owns the device, and
            # `dpm set-device-owner` would fail.
            print(f"Device {self.serial} is already owned by the ArborXR client.")
            return
        if owner:
            raise DeviceSetDeviceOwnerException(f"Device {self.serial} is managed by {owner}. Factory reset it, then enroll it (through HMS on Meta Quest) before provisioning.")

        proc = subprocess.run(["adb", "-s", self.serial, "shell", "dpm", "set-device-owner", CLIENT_ADMIN_RECEIVER], capture_output=True, text=True)
        if proc.returncode:
            if "Not allowed to set the device owner because there are already some accounts on the device" in proc.stderr:
                if self.is_quest():
                    self.force_stop_and_sleep("com.oculus.shellenv", 10.0)
                    self.delete_quest_accounts()
                    self.set_device_owner()

                elif self.is_vive_flow():
                    htcLauncherPackageName = "com.htc.vrs.launcher"

                    self.set_package_enabled(htcLauncherPackageName, False)
                    time.sleep(1)
                    self.set_device_owner()
                    self.set_package_enabled(htcLauncherPackageName, True)
                    self.send_keycode_and_sleep(3, 0.0)

            else:
                raise DeviceSetDeviceOwnerException("Failed to set device owner." + proc.stderr)

    def set_production_environment(self):
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "echo production > /sdcard/.xrdm-environment"])
        if proc.returncode:
            raise DeviceSetEnvironmentException("Failed to set production environment.")

    def _refuse_on_hms(self, action, exception_class):
        # HMS records how the headset was provisioned only at enrollment. Our client keeps it through a
        # WipeClient (client CL-1355), but removing device ownership or uninstalling the client loses it.
        # Refuse on a definite HMS answer only: these steps run only for XRDM 1 packages, which can't be HMS
        # enrolled, and the Device Setup App also treats an unclear answer as not HMS.
        if self.is_hms() is True:
            raise exception_class(f"Not allowed to {action} on HMS headset {self.serial}. Use WipeClient instead.")

    def remove_device_owner(self):
        self._refuse_on_hms("remove device ownership", DeviceRemoveDeviceOwnerException)
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "am", "broadcast", "-n", "app.xrdm.client/.AdminRemover", "-a", "REMOVE_DEVICE_OWNER"])
        max_wait_sec = 10
        wait_sec = 0
        if proc.returncode == 0:
            while True and wait_sec < max_wait_sec:
                proc = subprocess.run(["adb", "-s", self.serial, "shell", "dumpsys", "device_policy", "|", "grep", "\"app.xrdm.client/.AdminReceiver\""], capture_output=True, text=True)
                if proc.stdout == "":
                    break
                print("Waiting for device owner removal...")
                time.sleep(1)
                wait_sec += 1
            
            print("Device owner removal complete.")
            return True
        raise DeviceRemoveDeviceOwnerException("Failed to remove device owner.")
    
    def start_client_app(self):
        """Start the client in the foreground, as the Device Setup App does before talking to it."""
        subprocess.run(["adb", "-s", self.serial, "shell", "am", "start", "-n", CLIENT_FINISHING_ACTIVITY], capture_output=True, text=True)

    def _start_adb_service(self):
        try:
            sdk = int(self.prop("ro.build.version.sdk"))
        except ValueError:
            sdk = 0
        start_command = "start-foreground-service" if sdk >= 26 else "startservice"
        proc = subprocess.run(["adb", "-s", self.serial, "shell", "am", start_command, "-n", f"{CLIENT_PACKAGE_NAME}/{CLIENT_ADB_SERVICE}"], capture_output=True, text=True)
        if proc.returncode or "error" in proc.stdout.lower():
            raise Exception(f"Failed to start the client's AdbService. {proc.stdout}{proc.stderr}")

    def run_client_command(self, command, exception_class):
        """Send a command to the client's AdbService the way the Device Setup App does: start the service, check
        that it answered, and retry up to 3 times, restarting the client in between. Right after an install the
        service isn't running yet, and dumpsys then exits 0 with "No services match"."""
        command_json = json.dumps(command.to_dict())
        last_output = ""
        for attempt in range(3):
            if attempt:
                time.sleep(1)
                self.start_client_app()
            try:
                self._start_adb_service()
                proc = subprocess.run(["adb", "-s", self.serial, "shell", "dumpsys", "activity", "service", CLIENT_ADB_SERVICE, f"'''{command_json}'''"], capture_output=True, text=True)
                last_output = proc.stdout + proc.stderr
                result = parse_service_result(proc.stdout)
                if result is not None:
                    return result
            except Exception as e:
                last_output = str(e)
        raise exception_class(f"The client on {self.serial} didn't accept {command}. {last_output}")

    def wipe_client(self):
        print(f"Wiping client data on device {self.serial}...")
        self.run_client_command(WipeClient(), DeviceWipeClientException)
        print("Client data wiped.")

    def remove_device_owner_v2(self):
        self._refuse_on_hms("remove device ownership", DeviceRemoveDeviceOwnerException)
        self.run_client_command(RemoveDeviceOwnership(), DeviceRemoveDeviceOwnerException)
        for _ in range(10):
            if not is_client_admin(self.device_owner()):
                print("Device owner removal complete.")
                return True
            print("Waiting for device owner removal...")
            time.sleep(1)
        raise DeviceRemoveDeviceOwnerException("The client is still the device owner after RemoveDeviceOwnership.")

    def uninstall_apk(self, package_name):
        if package_name == AbxrClientApk.PACKAGE_NAME:
            self._refuse_on_hms("uninstall the ArborXR client", DeviceUninstallException)
        proc = subprocess.run(["adb", "-s", self.serial, "uninstall", package_name], capture_output=True, text=True)
        if proc.returncode:
            raise DeviceUninstallException(f"Failed to uninstall {package_name} on device {self.serial} - {proc.stderr}")

    def configure_api_token_authentication(self, config_pkg):
        """XRDM 1 packages only. A v2 package enrolls from settings.json (the CONFIGURE_DEVICE broadcast), as in the Device
        Setup App."""
        if isinstance(config_pkg, (str, Path)):
            config_pkg = ConfigurationPackage(config_pkg)

        if not isinstance(config_pkg, ConfigurationPackage):
            raise Exception("You must provide a ConfigurationPackage object.")

        if config_pkg.is_xrdm2:
            return

        settings = config_pkg.settings
        api_token_auth = {
            "apiToken": settings["apiToken"],
            "deviceGroup": {"id": settings["deviceGroup"]["id"]},
        }
        api_token_auth_json = json.dumps(api_token_auth)

        proc = subprocess.run(["adb", "-s", self.serial, "shell", "am", "broadcast", "-n", "app.xrdm.client/.SetupDeviceReceiver", "-a", "CONFIGURE_API_TOKEN", "-e", "ApiTokenAuth", f"'''{api_token_auth_json}'''"])
        if proc.returncode:
            raise DeviceConfigureApiTokenException("Failed to configure device with API token authentication.")

    def get_installed_version(self, package_name):
        result = subprocess.run(["adb", "-s", self.serial, "shell", "dumpsys", "package", package_name], capture_output=True, text=True)
        if result.returncode != 0:
            return None
        
        for line in result.stdout.split("\n"):
            if "versionName=" in line:
                return line.split("=")[1].strip()
    
        return None
    
    def abxr_client_version(self):
        return self.get_installed_version(AbxrClientApk.PACKAGE_NAME)
    
    def is_packaged_installed(self, package_name):
        return self.get_installed_version(package_name) is not None
    
    def __str__(self):
        return self.serial

