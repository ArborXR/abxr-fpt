import unittest

from abxr.device_policy import ALREADY_CURRENT, INSTALL, KEEP_INSTALLED, ClientDowngradeRefused, client_install_decision, compare_versions, is_client_admin, is_downgrade_error, parse_device_owner, parse_is_hms

DUMPSYS_OWNED_BY_CLIENT = """Current Device Policy Manager state:
  Immutable state:
    mHasFeature=true
  Device Owner: 
    admin=ComponentInfo{app.xrdm.client/app.xrdm.client.AdminReceiver}
    name=
    package=app.xrdm.client
  Enabled Device Admins (User 0, provisioningState: 3):
    app.xrdm.client/.AdminReceiver:
"""

DUMPSYS_OWNED_BY_OTHER_MDM = DUMPSYS_OWNED_BY_CLIENT.replace(
    "app.xrdm.client/app.xrdm.client.AdminReceiver", "com.managexr.agent/com.managexr.agent.AdminReceiver"
)

DUMPSYS_NO_OWNER = """Current Device Policy Manager state:
  Immutable state:
    mHasFeature=true
  Enabled Device Admins (User 0, provisioningState: 0):
"""


class DevicePolicyTest(unittest.TestCase):
    def test_reads_the_device_owner(self):
        self.assertEqual("app.xrdm.client/app.xrdm.client.AdminReceiver", parse_device_owner(DUMPSYS_OWNED_BY_CLIENT))
        self.assertIsNone(parse_device_owner(DUMPSYS_NO_OWNER))
        self.assertIsNone(parse_device_owner("Can't find service: device_policy"))

    def test_recognises_our_admin_receiver_in_both_forms(self):
        self.assertTrue(is_client_admin("app.xrdm.client/.AdminReceiver"))
        self.assertTrue(is_client_admin("app.xrdm.client/app.xrdm.client.AdminReceiver"))
        self.assertFalse(is_client_admin(parse_device_owner(DUMPSYS_OWNED_BY_OTHER_MDM)))
        self.assertFalse(is_client_admin(None))

    def test_reads_hms_from_the_oemconfig_provider(self):
        self.assertTrue(parse_is_hms("Row: 0 managed=1"))
        self.assertFalse(parse_is_hms("Row: 0 managed=-1"))

    def test_no_answer_from_the_provider_is_unknown(self):
        self.assertIsNone(parse_is_hms("", "Error while accessing provider:com.oculus.oemconfig.provider\nCould not find provider"))
        self.assertIsNone(parse_is_hms(""))
        self.assertIsNone(parse_is_hms("No result found."))

    def test_compares_client_versions(self):
        self.assertEqual(1, compare_versions("2026.48.0", "2026.45.1"))
        self.assertEqual(0, compare_versions("2026.47.0", "2026.47.0"))
        self.assertEqual(-1, compare_versions("2026.9.0", "2026.10.0"))
        self.assertIsNone(compare_versions(None, "2026.47.0"))
        self.assertIsNone(compare_versions("2026.47.0", "unknown"))

    def test_decides_the_client_install_before_any_wipe(self):
        def decide(installed, target, chose=False, force=False, v2=True):
            return client_install_decision(installed, target, operator_chose_client=chose, force_upgrade=force, is_v2_package=v2)

        self.assertEqual(INSTALL, decide(None, "2026.47.0"))
        self.assertEqual(INSTALL, decide("2026.45.0", "2026.47.0"))
        self.assertEqual(ALREADY_CURRENT, decide("2026.47.0", "2026.47.0"))
        self.assertEqual(INSTALL, decide("2026.47.0", "2026.47.0", chose=True, force=True))
        # HMS installs whatever client is current, which can be newer than the package's.
        self.assertEqual(KEEP_INSTALLED, decide("2026.48.0", "2026.47.0"))
        # An older client the operator chose: refused for v2 (no uninstall), allowed for v1 (uninstall, reinstall).
        with self.assertRaises(ClientDowngradeRefused):
            decide("2026.48.0", "2026.40.0", chose=True)
        self.assertEqual(INSTALL, decide("2026.48.0", "2026.40.0", chose=True, v2=False))
        self.assertEqual(INSTALL, decide("2026.48.0", None))
        self.assertEqual(ALREADY_CURRENT, decide("custom", "custom"))

    def test_recognises_a_client_downgrade(self):
        self.assertTrue(is_downgrade_error("adb: failed to install c.apk: Failure [INSTALL_FAILED_VERSION_DOWNGRADE: Downgrade detected]"))
        self.assertFalse(is_downgrade_error("adb: failed to install c.apk: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]"))
        self.assertFalse(is_downgrade_error("adb: failed to install /client/app.xrdm.client-downgrade.apk: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]"))


if __name__ == "__main__":
    unittest.main()
