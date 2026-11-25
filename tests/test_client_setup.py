import sys
import types
import unittest

try:
    import abxr.apk  # noqa: F401  needs androguard
except ImportError:
    sys.modules["abxr.apk"] = types.SimpleNamespace(get_package_name=lambda path: None)

from abxr.client_setup import CLEANING_UP_DEPENDENCIES, SetupProgress, clean_up_after_failure, prepare_client  # noqa: E402
from abxr.device import DeviceClientDowngradeException  # noqa: E402

LAUNCHER = "app.xrdm.launcher"


class FakeDevice:
    def __init__(self, client_version, launcher_installed=False, install_result=True, uninstall_error=None):
        self.version = client_version
        self.launcher_installed = launcher_installed
        self.install_result = install_result
        self.uninstall_error = uninstall_error
        self.calls = []

    def __str__(self):
        return "fake"

    def abxr_client_version(self):
        return self.version

    def is_packaged_installed(self, package_name):
        return package_name == LAUNCHER and self.launcher_installed

    def install_client_apk(self, path, keep_newer_installed, label="ArborXR client"):
        self.calls.append(("install", path, keep_newer_installed))
        if "launcher" in path:
            return True
        if isinstance(self.install_result, Exception):
            raise self.install_result
        if self.install_result:
            self.version = path.split("-")[-1]
        return self.install_result

    def install_apk(self, path):
        self.calls.append(("install_apk", path))

    def uninstall_apk(self, package_name):
        self.calls.append(("uninstall", package_name))
        if self.uninstall_error:
            raise self.uninstall_error

    def start_client_app(self):
        self.calls.append("start_client_app")

    def set_device_owner(self):
        self.calls.append("set_device_owner")

    def wipe_client(self):
        self.calls.append("wipe_client")

    def remove_device_owner(self):
        self.calls.append("remove_device_owner")


class FakeApk:
    def __init__(self, version):
        self.version = version
        self.path = f"app.xrdm.client-{version}"


LAUNCHER_APK = "app.xrdm.launcher-2026.40.1"


def prepare(device, version, launcher=None, chose=False, progress=None):
    return prepare_client(device, FakeApk(version), launcher, operator_chose_client=chose, progress=progress)


class PrepareClientTest(unittest.TestCase):
    """The Device Setup App's order: clean up the launcher, install client and launcher, start the client, set the
    device owner, wipe (only when the client was already there)."""

    def test_reinstall_follows_the_device_setup_app(self):
        device = FakeDevice("2026.45.0", launcher_installed=True)
        prepare(device, "2026.47.0", launcher=LAUNCHER_APK)
        self.assertEqual(
            [
                ("uninstall", LAUNCHER),
                ("install", "app.xrdm.client-2026.47.0", True),
                ("install", LAUNCHER_APK, True),
                "start_client_app",
                "set_device_owner",
                "wipe_client",
            ],
            device.calls,
        )

    def test_newer_client_on_the_headset_is_kept_and_wiped(self):
        # An HMS headset whose client is newer than the package's: the refused downgrade is ignored.
        device = FakeDevice("2026.48.0", install_result=False)
        self.assertFalse(prepare(device, "2026.47.0"))
        self.assertEqual(
            [("install", "app.xrdm.client-2026.47.0", True), "start_client_app", "set_device_owner", "wipe_client"],
            device.calls,
        )

    def test_fresh_headset_isnt_wiped(self):
        device = FakeDevice(None)
        prepare(device, "2026.47.0")
        self.assertNotIn("wipe_client", device.calls)

    def test_operator_chosen_downgrade_is_refused_before_any_change(self):
        device = FakeDevice("2026.48.0", launcher_installed=True)
        with self.assertRaises(DeviceClientDowngradeException):
            prepare(device, "2026.40.0", launcher=LAUNCHER_APK, chose=True)
        self.assertEqual([], device.calls)

    def test_refused_install_of_a_chosen_client_stops_before_the_wipe(self):
        # Versions adb can't compare up front: the install itself is refused.
        device = FakeDevice("2026.48.0-dev", install_result=DeviceClientDowngradeException("newer"))
        with self.assertRaises(DeviceClientDowngradeException):
            prepare(device, "2026.40.0", chose=True)
        self.assertNotIn("wipe_client", device.calls)

    def test_launcher_is_only_removed_on_a_reinstall(self):
        device = FakeDevice(None, launcher_installed=True)
        prepare(device, "2026.47.0", launcher=LAUNCHER_APK)
        self.assertNotIn(("uninstall", LAUNCHER), device.calls)

    def test_refused_chosen_client_puts_the_launcher_back(self):
        device = FakeDevice("2026.48.0-rc.1", launcher_installed=True, install_result=DeviceClientDowngradeException("newer"))
        with self.assertRaises(DeviceClientDowngradeException):
            prepare(device, "2026.47.1", launcher=LAUNCHER_APK, chose=True)
        self.assertEqual(
            [("uninstall", LAUNCHER), ("install", "app.xrdm.client-2026.47.1", False), ("install", LAUNCHER_APK, True)],
            device.calls,
        )

    def test_no_cleanup_when_the_launcher_cleanup_itself_fails(self):
        progress = SetupProgress()
        device = FakeDevice("2026.45.0", launcher_installed=True, uninstall_error=Exception("adb"))
        with self.assertRaises(Exception):
            prepare(device, "2026.47.0", launcher=LAUNCHER_APK, progress=progress)
        self.assertEqual(CLEANING_UP_DEPENDENCIES, progress.step)
        self.assertFalse(progress.should_clean_up())

    def test_cleanup_once_a_later_step_fails(self):
        progress = SetupProgress()
        self.assertFalse(progress.should_clean_up())
        progress.step = "installing-dependencies"
        self.assertTrue(progress.should_clean_up())

    def test_failure_cleanup_wipes_and_removes_the_launcher_but_never_uninstalls_the_client(self):
        device = FakeDevice("2026.47.0", launcher_installed=True)
        clean_up_after_failure(device, has_launcher=True)
        self.assertEqual(["wipe_client", ("uninstall", LAUNCHER)], device.calls)


if __name__ == "__main__":
    unittest.main()
