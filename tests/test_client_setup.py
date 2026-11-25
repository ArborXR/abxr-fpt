import sys
import types
import unittest

# abxr.apk needs androguard, which these tests don't use.
sys.modules.setdefault("abxr.apk", types.SimpleNamespace(get_package_name=lambda path: None))

from abxr.client_setup import prepare_client  # noqa: E402
from abxr.device import DeviceClientDowngradeException  # noqa: E402


class FakeDevice:
    def __init__(self, installed_version, install_result=True, newer_on_install=None):
        self.version = installed_version
        self.install_result = install_result
        self.calls = []

    def __str__(self):
        return "fake"

    def abxr_client_version(self):
        return self.version

    def install_client_apk(self, path, keep_newer_installed):
        self.calls.append(("install", keep_newer_installed))
        if isinstance(self.install_result, Exception):
            raise self.install_result
        if self.install_result:
            self.version = path.split("-")[-1]
        return self.install_result

    def set_device_owner(self):
        self.calls.append("set_device_owner")

    def wipe_client(self):
        self.calls.append("wipe_client")

    def remove_device_owner(self):
        self.calls.append("remove_device_owner")

    def uninstall_apk(self, package_name):
        self.calls.append(("uninstall", package_name))

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


class PrepareClientTest(unittest.TestCase):
    def test_v2_installs_before_wiping(self):
        device = FakeDevice("2026.45.0")
        self.assertTrue(prepare_client(device, V2, FakeApk("2026.47.0"), operator_chose_client=False, force_upgrade=False))
        self.assertEqual(
            [("install", True), "set_device_owner", "wipe_client", "set_production_environment"],
            device.calls,
        )

    def test_v2_keeps_a_newer_client_and_still_wipes_it(self):
        # An HMS headset whose client is newer than the package's.
        device = FakeDevice("2026.48.0")
        self.assertFalse(prepare_client(device, V2, FakeApk("2026.47.0"), operator_chose_client=False, force_upgrade=False))
        self.assertEqual(["set_device_owner", "wipe_client"], device.calls)

    def test_v2_refused_downgrade_wipes_nothing(self):
        device = FakeDevice("2026.48.0", install_result=DeviceClientDowngradeException("newer"))
        with self.assertRaises(DeviceClientDowngradeException):
            prepare_client(device, V2, FakeApk("2026.40.0"), operator_chose_client=True, force_upgrade=False)
        self.assertNotIn("wipe_client", device.calls)

    def test_v2_fresh_headset_isnt_wiped(self):
        device = FakeDevice(None)
        prepare_client(device, V2, FakeApk("2026.47.0"), operator_chose_client=False, force_upgrade=False)
        self.assertEqual([("install", True), "set_device_owner", "set_production_environment"], device.calls)

    def test_v1_uninstalls_before_reinstalling(self):
        device = FakeDevice("2026.48.0")
        prepare_client(device, V1, FakeApk("2025.10.0"), operator_chose_client=False, force_upgrade=False)
        self.assertEqual(
            ["remove_device_owner", ("uninstall", "app.xrdm.client"), ("install", False), "set_device_owner", "set_production_environment"],
            device.calls,
        )


if __name__ == "__main__":
    unittest.main()
