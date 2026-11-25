# ArborXR Field Provisioning Tools

`abxr-provision` loads an ArborXR configuration package onto Android headsets over USB, from the command line. It does what the ArborXR Device Setup App does, step for step, and can run several headsets at once as an unattended station. It runs on a Windows, macOS or Linux computer, or on the ArborXR Field Provisioning Device (FPD). Everything goes over USB. The computer doesn't need to reach ArborXR.

### Features
- Provision new Android devices (XR, phone, tablet) with a configuration package built in the ArborXR portal.
- Re-provision devices that already have the ArborXR client, including Meta Quest headsets enrolled through Meta Horizon managed services (HMS).
- Provision several headsets at once in one process, as a station that keeps running.
- Replace the ArborXR client with a newer build, or reinstall the same one.

Only v2 configuration packages are supported. XRDM 1 packages are rejected; build a new package in the ArborXR portal.

## Table of Contents
- [Requirements](#requirements)
- [Installing](#installing)
- [Running the Provisioning Tool](#running-the-provisioning-tool)
- [Meta Quest with HMS: start to finish](#meta-quest-with-hms-start-to-finish)
- [How a headset is provisioned](#how-a-headset-is-provisioned)
- [Disk space checks](#disk-space-checks)
- [Limits](#limits)
- [Field Provisioning Device (FPD)](#field-provisioning-device-fpd)
- [Development](#development)

## Requirements

- **Python 3.9 or later.**
- **adb on the PATH** (Android SDK Platform-Tools). The tool runs one adb server for every headset, like the Device Setup App. Avoid running the Device Setup App, or another tool that ships its own adb, at the same time: two adb versions can stop each other's server.
- **USB debugging on each headset.** For headsets enrolled in ArborXR, turn on Developer mode in the group they enrolled into, and accept "Allow USB debugging" (with "Always allow from this computer") on the headset.
- **Disk space:**
  - On the computer, for the package itself plus temp space for each headset running at once.
  - On each headset, for everything the package loads.
  - The tool checks both before it starts (see [Disk space checks](#disk-space-checks)).

## Installing

```sh
pip install -e .
```

(`install.sh` does the same.) This puts `abxr-provision` on the PATH.

## Running the Provisioning Tool

```sh
abxr-provision
```

It runs as a station:
- **Watching:** every 2 seconds it checks `adb devices`, on Windows, macOS and Linux.
- **In parallel:** it provisions each headset that's plugged in, several at once.
- **No repeats:** a headset that's done isn't touched again while it stays plugged in, or if it drops off for less than 2 minutes (a reboot, a loose cable). Unplug it for longer and plug it back in to run it again.
- **Retrying:** a headset that failed is retried by unplugging it and plugging it back in.
- **Waiting for the headset:** headsets adb can't use yet get a message saying what to do. That covers "Allow USB debugging" not tapped, "no permissions" (on Linux, add udev rules) and "offline".
- **If adb doesn't answer** for a moment, the station waits for it. Headsets that are done stay done.
- **Stopping:** press Ctrl+C to stop starting new headsets, queued ones included, and wait for the running ones to finish. Press it again to quit at once; headsets that were still running aren't finished and need a re-run.

Every log line starts with the headset's serial. On the FPD, the display shows what's running, queued, done, failed and not ready, plus the last failure and its reason.

Exit status:
- **`--once` exits 0** when every headset it saw was provisioned.
- **It exits 1** when any headset failed or was never ready, or when none was connected and ready within 10 seconds (with `--device-serial`, when that headset wasn't). It also exits 1 if adb doesn't answer for 60 seconds while no headset is running.
- **Ctrl+C exits 130.**

By default it looks for:
- configuration packages in `$HOME/abxr/configuration-packages` (one per device model; two packages for the same model stop it from choosing).
- a client APK override in `$HOME/abxr/client` (optional).

Set `ABXR_ASSETS_PATH` to use another base folder.

Options (all optional):

```sh
abxr-provision --config-package <package.zip> --client <client.apk> --max-parallel 8 --once
```

- `--config-package`, `-p`: use this package instead of searching the folder.
- `--client`, `-c`: use this client APK instead of the package's. It can't be older than the client on the headset; a downgrade would need an uninstall, which loses an HMS headset's enrollment.
- `--max-parallel`, `-n`: how many headsets to provision at once (default 8). On one USB 3 hub, 8 headsets share about 300 MB/s, so a powered USB 3 hub and good cables matter more than this number. A USB 2 hub caps everything at about 40 MB/s.
- `--once`: provision the headsets connected now, then exit. It waits up to 60 seconds for a headset that isn't ready (e.g. "Allow USB debugging" not tapped).
- `--device-serial`, `-s`: provision only this headset. Implies `--once`.
- `--force-upgrade`, `-f`: reinstall the client even when the versions match.
- `--package-only`, `-o`: load the package onto a headset that's already set up, without touching the client.
- `--list-connected-devices`, `-l`: list the headsets that are ready (authorized) and exit. With `--device-serial`, only that one.
- `--skip-space-check`: don't check the headset's free space. Use it when re-provisioning a headset that already has this package's content: the check counts the whole package as new, so it can refuse a headset that would fit.

## Meta Quest with HMS: start to finish

Meta only enrolls a Quest into an MDM during its first-time setup, through Meta Horizon managed services. The recommended station for HMS headsets:

1. **In ArborXR, make two groups:**
   - A **staging** group with Developer mode on, no content, and a Home banner or background that says the headset isn't ready.
   - The **final** group your headsets ship in, with Developer mode off.
2. **Enrollment file:** download the HMS enrollment file from the staging group and add it as a third-party enrollment in Meta's Device Manager.
3. **Build the package:** build the configuration package from the final group in the ArborXR portal and put it in `configuration-packages`.
4. **Enroll with Meta's tool:** enroll new or factory-reset headsets with Meta's Horizon Device Setup app (fastboot), into the staging enrollment. Tap "Accept and continue" on ArborXR's consent screen during setup; declining factory-resets the headset. Each headset comes up in Shared Mode with the ArborXR client, in the staging group, with USB debugging on.
5. **Provision:** keep the headsets plugged into the hub and run `abxr-provision`.
   - Tap "Allow USB debugging" (and "Always allow from this computer") on each headset.
   - The tool loads the package over USB, and each headset moves into the final group with nothing left to download.
   - Developer mode turns off as the headset joins the final group.
6. **Before packing,** check in the portal that the staging group is empty.

## How a headset is provisioned

The ArborXR Device Setup App is the source of truth, because customers use it today. `abxr-provision` follows its steps in the same order:

1. On a headset that already has the client, remove the launcher.
2. Install the package's client and launcher. A refused downgrade is ignored, so a newer client on the headset is kept.
3. Start the client.
4. Grant `REQUEST_INSTALL_PACKAGES` and make the client the device owner. This is skipped when the client already owns the headset, as it always does after HMS enrollment. If another MDM owns it, the run stops: factory reset the headset and enroll it again.
5. Wipe the client's data if it was already installed, so it enrolls into the package's group.
6. Install the apps and push the OBBs, files, videos and images to the Device Setup App's paths.
7. Push `settings.json` to `/sdcard/Setup/` and send the client `BootstrapViaJsonFile`. The client applies the package's configurations, treats the content just loaded as installed, and enrolls with the package's token.

**Talking to the client:** commands go through the client's `AdbService`, as in the Device Setup App:
- The tool starts the service, checks that the client took the command, and follows the client's log until the command reports `DONE`.
- An `ERROR`, or no `DONE` within 20 seconds, counts as a failure.
- A failed command is retried 3 times, with the client restarted in between.

**When a run fails:**
- **Steps 2–6:** the tool wipes the client and removes the launcher, like the Device Setup App, so the headset can't be shipped looking enrolled. Re-run it.
- **Not cleaned up:** failures in step 1, in step 7, or in bad input such as a wrong `--client` path, also like the Device Setup App.
- **Afterwards:** sleep and Guardian come back on. A VIVE Flow on firmware older than 1.98.8888.01 reboots, as in the Device Setup App's last step.
- **Not touched:** Google Play Protect and the client's environment file, because the Device Setup App's v2 flow leaves them alone too.

**Meta Quest headsets enrolled through HMS:**
- **HMS is detected** through Meta's OEMConfig provider (`content://com.oculus.oemconfig.provider/managed`) and logged.
- **The client is never uninstalled and device ownership is never removed.** Re-provisioning uses `WipeClient`. The client keeps HMS's one-time provisioning record through a wipe (client CL-1355), but not through an uninstall.
- **A client you choose must install.** A `/client` override or `--force-upgrade` that's older than the headset's client is refused before anything on the headset changes.

## Disk space checks

A large package that can't fit should stop at the start with a clear message, not fail an hour in. The tool checks three times.

**This computer, at startup:**
- **The rule:** each headset that's running holds the client, the launcher and one item of the package in the temp folder. An app bundle needs room for its zip plus what it unpacks to.
- **The check:** the temp folder needs that much for every headset `--max-parallel` allows, plus 1 GB.
- **If fewer headsets fit,** the tool runs that many at a time instead and prints what's needed and what's free. The FPD runs with no options, so it adjusts itself the same way and shows "Low PC disk space".
- **If not even one fits,** the tool won't start. The FPD display shows "Not enough space".
- **To run more at once,** free up space or point the temp folder at a bigger drive: `TMPDIR` on macOS and Linux, `TEMP` on Windows.

**Each headset, before anything on it changes:**
- **The check:** the tool reads the headset's free storage (`df -k /sdcard`). It needs the package's apps, unpacked app bundles and files, plus the client and launcher, plus 5% and 1 GB.
- **If it doesn't fit,** that headset fails with the numbers ("this package needs 74.5 GB and the headset has 61.0 GB free"). Nothing on it is changed. The FPD display shows "Headset full".
- **If the free space can't be read,** the tool logs that and carries on.
- **Re-provisioning:** the check counts the whole package as new. To re-provision a headset that already has this content, pass `--skip-space-check`.

**During the run:**
- **The check:** before each item is copied out of the package, and again before an app bundle is unpacked, the tool checks the temp folder's free space. That catches another program filling the disk mid-run.
- **If it doesn't fit,** that headset fails with "PC disk full" and is cleaned up like any other failure in steps 2–6.

## Limits

- **Temp files:** each file in the package is copied to a temporary file before it's pushed, one file at a time. The computer needs temp space for the largest single file in the package (an app bundle's zip plus what it unpacks to) for each headset running at once, not for the whole package. Packages aren't streamed straight to the headset yet.
- **Speed:** throughput is set by USB. One headset on its own cable takes about 37 MB/s, so 70 GB takes roughly 30 minutes.
- **Interruptions:** a run that's stopped or unplugged partway isn't finished. Re-run that headset.

## Field Provisioning Device (FPD)

The ArborXR Field Provisioning Device is a headless computer that runs `abxr-provision` without a laptop.

### Hardware Information

The supported hardware is a Raspberry Pi Zero 2 W running Raspberry Pi OS 64-bit. The base image has custom changes to support dual-mode USB (host and gadget). They aren't well documented yet, and should be captured in code so they can be applied to a fresh image.

`device_start.sh` is launched by `systemd` to start the tool on the FPD. It reads a GPIO to tell whether the selector switch is in "Setup" or "Provision" mode.

### Setup Mode

With the selector switch in "Setup" mode, connect the FPD to a computer. It shows up as a mass storage device, with this structure:

```
/configuration-packages
```
Configuration packages, one per device model. Two packages for the same model stop the tool from choosing.

```
/client
```
(Optional) A client APK to use instead of the package's, for example a newer build. It can't be older than the client on the headset.

```
field-provisioning-tools-update.zip
```
A tool update. It's applied the next time the FPD boots into "Provision" mode, then deleted.

### Provision Mode

With the selector switch in "Provision" mode, the FPD runs `abxr-provision` as a station. It provisions every headset plugged into it with the package that matches its model, several at once. Its display shows running, queued, done, failed and not-ready counts, plus the last failure and its reason. A finished headset isn't provisioned again unless it's unplugged for more than 2 minutes.

XR devices need USB power injection, because the FPD can't supply enough current. Use the included wall outlet and connector.

## Development

1. Clone the repository.
2. Create and activate a virtual environment:
    ```sh
    python3 -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```
3. Install the dependencies:
    ```sh
    pip install -r requirements.txt
    pip install -e .
    ```

### Running the tests

```sh
python3 -m unittest discover -s tests
```

The tests don't need a headset or adb. They cover package parsing and device paths, the HMS and device-owner checks, the Device Setup App's step order and cleanup, the client command protocol, the disk space checks, and the station's parallel runs.

GitHub Actions runs them on every pull request and on pushes to `main`, on Python 3.9 (the minimum) and 3.14. It installs the package first, then checks from outside the checkout that `abxr-provision` and `abxr-display-setup-mode` load (`.github/workflows/tests.yml`).

### Building an update package for the FPD

```sh
build_update_package.sh
```

This packages the project into `field-provisioning-tools-update.zip`. Put it in the root of the FPD while it's mounted in "Setup" mode, and it's applied when the FPD boots back into "Provision" mode.
