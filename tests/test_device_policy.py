import unittest

from abxr.device_policy import is_client_admin, is_downgrade_error, is_newer_version, is_older_firmware, parse_command_id, parse_command_progress, parse_device_owner, parse_is_hms, parse_service_result

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

    def test_reads_the_client_service_result(self):
        answered = "SERVICE app.xrdm.client/xrdm.adb.AdbService 7c1e2f pid=4321 user=0\n  Client:\n  OK TAG: 0f3a9c\n"
        self.assertEqual("OK TAG: 0f3a9c", parse_service_result(answered))
        # Right after an install the service isn't running yet; dumpsys still exits 0.
        self.assertIsNone(parse_service_result("No services match: xrdm.adb.AdbService\n"))
        self.assertIsNone(parse_service_result("SERVICE app.xrdm.client/xrdm.adb.AdbService 7c1e2f pid=4321 user=0\n  Client:\n  ERROR: unknown command\n"))

    def test_follows_a_client_command_to_done(self):
        self.assertEqual("0f3a9c", parse_command_id("OK TAG: 0f3a9c"))
        self.assertIsNone(parse_command_id("OK"))
        self.assertEqual("Wiping database", parse_command_progress("I/0f3a9c: Wiping database\n", "0f3a9c"))
        self.assertEqual("DONE", parse_command_progress("I/0f3a9c: DONE\n", "0f3a9c"))
        self.assertEqual("ERROR: no space", parse_command_progress("I/0f3a9c: ERROR: no space", "0f3a9c"))
        self.assertIsNone(parse_command_progress("I/ActivityManager: Start proc", "0f3a9c"))
        self.assertIsNone(parse_command_progress("--------- beginning of main", "0f3a9c"))

    def test_compares_release_versions_only(self):
        self.assertTrue(is_newer_version("2026.48.0", "2026.45.1"))
        self.assertFalse(is_newer_version("2026.47.0", "2026.47.0"))
        self.assertFalse(is_newer_version("2026.9.0", "2026.10.0"))
        self.assertFalse(is_newer_version(None, "2026.47.0"))
        self.assertFalse(is_newer_version("2026.48.0-dev", "2026.47.0"))

    def test_compares_vive_flow_firmware(self):
        self.assertTrue(is_older_firmware("1.97.1234.01", "1.98.8888.01"))
        self.assertFalse(is_older_firmware("1.98.8888.01", "1.98.8888.01"))
        self.assertFalse(is_older_firmware("2.03.623.01", "1.98.8888.01"))
        self.assertFalse(is_older_firmware("unknown", "1.98.8888.01"))

    def test_recognises_a_client_downgrade(self):
        self.assertTrue(is_downgrade_error("adb: failed to install c.apk: Failure [INSTALL_FAILED_VERSION_DOWNGRADE: Downgrade detected]"))
        self.assertFalse(is_downgrade_error("adb: failed to install c.apk: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]"))
        self.assertFalse(is_downgrade_error("adb: failed to install /client/app.xrdm.client-downgrade.apk: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]"))


if __name__ == "__main__":
    unittest.main()
