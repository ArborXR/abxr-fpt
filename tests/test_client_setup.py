import sys
import types
import unittest

try:
    import abxr.apk  # noqa: F401  needs androguard
except ImportError:
    sys.modules["abxr.apk"] = types.SimpleNamespace(get_package_name=lambda path: None)

from abxr.client_setup import clean_up_after_failure, prepare_client  # noqa: E402
from abxr.device import DeviceClientDowngradeException  # noqa: E402

LAUNCHER = "app.xrdm.launcher"


class FakeDevice:
    def __init__(self, client_version, launcher_installed=False, install_result=True):
        self.version = client_version
        self.launcher_installed = launcher_installed
        self.install_result = install_result
        self.calls = []

    def __str__(self):
        return "fake"

    def abxr_client_version(self):
        return self.version

    def is_packaged_installed(self, package_name):
        return package_name == LAUNCHER and self.launcher_installed

    def install_client_apk(self, path, keep_newer_installed):
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

    def start_client_app(self):
        self.calls.append("start_client_app")

    def set_device_owner(self):
        self.calls.append("set_device_owner")

    def wipe_client(self):
        self.calls.append("wipe_client")

    def remove_device_owner(self):
        self.calls.append("remove_device_owner")

    def set_production_environment(self):
        self.calls.append("set_production_environment")


class FakeApk:
    def __init__(self, version):
        self.version = version
        self.path = f"app.xrdm.client-{version}"


class FakePackage:
    def __init__(self, is_xrdm2):
        self.is_xrdm2 = is_xrdm2


V2 = FakePackage(is_xrdm2=True)
V1 = FakePackage(is_xrdm2=False)
LAUNCHER_APK = "app.xrdm.launcher-2026.40.1"


def prepare(device, package, version, launcher=None, chose=False, force=False):
    return prepare_client(device, package, FakeApk(version), launcher, operator_chose_client=chose, force_upgrade=force)


class PrepareClientV2Test(unittest.TestCase):
    """The Device Setup App's order: clean up the launcher, install client and launcher, start the client, set the
    device owner, wipe (only when the client was already there)."""

    def test_reinstall_follows_the_device_setup_app(self):
        device = FakeDevice("2026.45.0", launcher_installed=True)
        prepare(device, V2, "2026.47.0", launcher=LAUNCHER_APK)
        self.assertEqual(
            [
                ("uninstall", LAUNCHER),
                ("install", "app.xrdm.client-2026.47.0", True),
                ("install", LAUNCHER_APK, True),
                "start_client_app",
                "set_device_owner",
                "wipe_client",
                "set_production_environment",
            ],
            device.calls,
        )

    def test_newer_client_on_the_headset_is_kept_and_wiped(self):
        # An HMS headset whose client is newer than the package's: the refused downgrade is ignored.
        device = FakeDevice("2026.48.0", install_result=False)
        self.assertFalse(prepare(device, V2, "2026.47.0"))
        self.assertEqual(
            [("install", "app.xrdm.client-2026.47.0", True), "start_client_app", "set_device_owner", "wipe_client"],
            device.calls,
        )

    def test_fresh_headset_isnt_wiped(self):
        device = FakeDevice(None)
        prepare(device, V2, "2026.47.0")
        self.assertNotIn("wipe_client", device.calls)

    def test_operator_chosen_downgrade_fails_before_the_wipe(self):
        device = FakeDevice("2026.48.0", install_result=DeviceClientDowngradeException("newer"))
        with self.assertRaises(DeviceClientDowngradeException):
            prepare(device, V2, "2026.40.0", chose=True)
        self.assertEqual([("install", "app.xrdm.client-2026.40.0", False)], device.calls)

    def test_failure_cleanup_wipes_but_never_uninstalls(self):
        device = FakeDevice("2026.47.0")
        clean_up_after_failure(device, V2)
        self.assertEqual(["wipe_client"], device.calls)


class PrepareClientV1Test(unittest.TestCase):
    def test_keeps_the_original_uninstall_and_reinstall(self):
        device = FakeDevice("2026.48.0")
        prepare(device, V1, "2025.10.0")
        self.assertEqual(
            [
                "remove_device_owner",
                ("uninstall", "app.xrdm.client"),
                ("install", "app.xrdm.client-2025.10.0", False),
                "set_device_owner",
                "set_production_environment",
            ],
            device.calls,
        )

    def test_current_client_is_left_alone(self):
        device = FakeDevice("2025.10.0")
        prepare(device, V1, "2025.10.0")
        self.assertEqual([], device.calls)

    def test_failure_cleanup_does_nothing(self):
        device = FakeDevice("2025.10.0")
        clean_up_after_failure(device, V1)
        self.assertEqual([], device.calls)


if __name__ == "__main__":
    unittest.main()
