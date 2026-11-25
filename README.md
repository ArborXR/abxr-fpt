# ArborXR Field Provisioning Tools

This project is a collection of tools to help provision and recover Android devices on ArborXR's XRDM. The provisioning tools can be used interactively on a computer, or deployed onto the ArborXR Field Provisioning Device (FPD). The tools are intended to be used without the need for network connectivity to the ArborXR XRDM backend.

### Features
- Provision new Android devices (XR, Phone, Tablet) with an XRDM configuration package.
- Re-provision existing devices with a configuration package.
- Replace the ArborXR client with a newer build, or reinstall the same one.

Only v2 configuration packages (built in the ArborXR portal) are supported. XRDM 1 packages are rejected.


## Table of Contents
- [Features](#features)
- [Field Provisioning Device (FPD)](#field-provisioning-device-fpd)
  - [Hardware Information](#hardware-information)
  - [Setup Mode](#setup-mode)
  - [Provision Mode](#provision-mode)
- [Development Environment Setup](#development-environment-setup)
- [Running the Provisioning Tool](#running-the-provisioning-tool)

## Field Provisioning Device (FPD)

The ArborXR Field Provisioning Device is a headless computer which can deploy XRDM Configuration Packages without the need for internet access. 

### Hardware Information

Currently supported hardware is currently a Raspberry Pi Zero 2 W running RBPI OS 64-bit. There are custom modifications made to the base image to support the dual mode USB (host/gadget). The image customizations are currenly not well documented, and in the future should be captured in code to be able to apply to a fresh RBPI OS image. 

`device_start.sh` - This is a specific script which is launched by `systemd` to automatically start the provisioning tool on the FPD. There is a check to see if a certain GPIO is set to check for "Setup" or "Provision" mode is set.

### Setup Mode

When the FPD selector switch is in "Setup" Mode, the device can be connected to any computer and will show up as a "Mass Storage Device". This is where the user can place XRDM Configuration Packages and/or an alternate client build. 

You must follow a specific directory structure:
```
/configuration-packages
```
Place XRDM configuration packages here. Currently undetermined behavior if you place multiple configuration packages which apply to the same device. We don't have logic which can select the "best" package. Make sure you only place one per device type
```
/client
```
(Optional) You can place an alternate client to use instead of what's included in the configuration package, for example a newer build. It can't be older than the client on the headset: a downgrade would need an uninstall, which loses an HMS headset's enrollment.
```
field-provisioning-tools-update.zip
```
This is the update package. It will be read as soon as the device boots into "Provision" mode. It will automatically be deleted as soon as its applied.

### Provision Mode

When the FPD selector switch is in "Provision" Mode, the device can be connected to any Android device which USB debugging is enabled, and it will automatically start provisioning the device with any available configuration package that matches the device model connected.

This all happens in a headless manner, but once the device is provisioned the FPD will stop, and wont start another provisioning run until a new device is detected.

Currently XR devices require USB power injection due to the FPD HW not being able to supply enough current. Please use the included wall outlet and connector.

## Development Environment Setup

Python 3.x is required. 

1. Clone the repository:

2. Create and activate a virtual environment:
    ```sh
    python3 -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. Install the dependencies:
    ```sh
    pip install -r requirements.txt
    ```

## Running the Provisioning Tool

To run the provisioning tool, use the following command to install it into the path:

```sh
install.sh
```

Then it can be run using

```sh
abxr-provision
```
On non-Linux systems (MacOS/Windows) will start the provisioner in "single shot mode". It loads with the default options:
- Searches for configuration packages in $HOME/abxr/configuration-packages
- Searches for any special client APK overrides in $HOME/abxr/client

You can override the base path by setting the `ABXR_ARCHIVE_PATH` environment variable before starting the provisioning tool.

You can also pass arguments to the application which allow to specify exact locations of the configuration packages, client, or specific device serial numbers to match. This is useful when using the application in a multi-device environment

```sh
abxr-provision --config-package <path-to-config-packages> --client <path-to-client-for-override> --device-serial <specific-device-to-target> --force-upgrade
```
All of the command line switches are optional, and can be used interchangably. The force upgrade option will always reinstall the client even if the versions match.

### How a headset is provisioned (same as the ArborXR Device Setup App)

The ArborXR Device Setup App is the source of truth, because customers use it today. `abxr-provision` follows its steps in the same order:

1. On a headset that already has the client, remove the launcher.
2. Install the package's client and launcher. A refused downgrade is ignored, so a newer client on the headset is kept.
3. Start the client.
4. Grant `REQUEST_INSTALL_PACKAGES` and make the client the device owner. This is skipped when the client already owns the headset, as it always does after HMS enrollment. If another MDM owns it, the run stops.
5. Wipe the client's data if it was already installed, so it enrolls into the package's group.
6. Install the apps and push the OBBs, files, videos and images to the Device Setup App's paths.
7. Push `settings.json` to `/sdcard/Setup/` and send the client `BootstrapViaJsonFile`. The client applies the package's configurations and enrolls with its token.

**Talking to the client:** commands go through the client's `AdbService`, as in the Device Setup App. The tool starts the service, checks that the client took the command, and follows the client's log until the command reports `DONE`. An `ERROR`, or no `DONE` within 20 seconds, counts as a failure. A failed command is retried 3 times, with the client restarted in between.

**When a run fails:** if steps 2–6 fail, the tool wipes the client and removes the launcher, like the Device Setup App, so the headset can't be shipped looking enrolled. Re-run it. Failures in step 1, in step 7, or in bad input such as a wrong `--client` path aren't cleaned up, also like the Device Setup App. Afterwards, sleep and Guardian come back on, and a VIVE Flow on firmware older than 1.98.8888.01 reboots, as in the Device Setup App's last step. Google Play Protect and the client's environment file aren't touched, because the Device Setup App's v2 flow leaves them alone too.

**Meta Quest headsets enrolled through Horizon managed services (HMS):**
- **HMS is detected** through Meta's OEMConfig provider (`content://com.oculus.oemconfig.provider/managed`) and logged.
- **The client is never uninstalled and device ownership is never removed.** It re-provisions with `WipeClient`. The client keeps HMS's one-time provisioning record through a wipe (client CL-1355), but not through an uninstall.
- **A client you choose must install.** A `/client` override or `--force-upgrade` that's older than the headset's client is refused before anything on the headset changes.

The headset needs USB debugging on (turn on Developer mode in the ArborXR group it enrolled into) and "Allow USB debugging" accepted on the headset.

## Running the tests

```sh
python3 -m unittest discover -s tests
```

## Building a update package for the provisioning hardware

```sh
build_update_package.sh
```
This will package the project into a zip archive called `field-provisioning-tools-update.zip` that can be placed in the root directory of the HW provisioning device when mounted in "Setup Mode". When the device is booted back in provisioning mode, the update will automatically be applied.
